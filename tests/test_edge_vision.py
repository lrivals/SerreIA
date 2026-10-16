"""Edge inference (docs/05 §2-3) on synthetic models and images: backends, classifier,
YOLO decoding, white balance, pipeline -> contract VisionResult."""

from datetime import UTC, datetime

import cv2
import numpy as np
import pytest

onnx = pytest.importorskip("onnx")
pytest.importorskip("onnxruntime")

from onnx import TensorProto, helper  # noqa: E402

from common.mqtt import VisionResult, decode, encode, vision_topic  # noqa: E402
from edge.vision.backends import MEAN, STD, OnnxBackend, normalize, order_outputs  # noqa: E402
from edge.vision.classifier import EdgeClassifier, entropy, softmax  # noqa: E402
from edge.vision.detector import (  # noqa: E402
    EdgeYolo,
    decode_yolov8,
    letterbox,
    parse_hailo_nms,
    unletterbox,
)
from edge.vision.pipeline import EdgePipeline, Plant, norm_bbox  # noqa: E402
from edge.vision.preprocess import gray_card_wb, resize_max  # noqa: E402

LABELS = {
    "especes": ["fraisier", "salade", "tomate"],
    "sante": ["anormal", "sain"],
    "classes": ["a/maladie/x", "b/maladie/y", "c/sain/sain", "tomate/maladie/mildiou"],
    "taxonomy_version": 1,
}
SIZE = 8


def tiny_classifier(path, batch=1):
    """GlobalAveragePool -> 3 Gemm heads (espece 3, sante 2, classe 4), fixed batch."""
    rng = np.random.default_rng(0)
    inits, nodes, outs = (
        [],
        [
            helper.make_node("GlobalAveragePool", ["image"], ["gap"]),
            helper.make_node("Flatten", ["gap"], ["feat"]),
        ],
        [],
    )
    for name, k in (("espece", 3), ("sante", 2), ("classe", 4)):
        w = rng.normal(size=(k, 3)).astype(np.float32)
        inits += [
            helper.make_tensor(f"W_{name}", TensorProto.FLOAT, w.shape, w.ravel()),
            helper.make_tensor(f"b_{name}", TensorProto.FLOAT, (k,), np.zeros(k)),
        ]
        nodes.append(helper.make_node("Gemm", ["feat", f"W_{name}", f"b_{name}"], [name], transB=1))
        outs.append(helper.make_tensor_value_info(name, TensorProto.FLOAT, [batch, k]))
    graph = helper.make_graph(
        nodes,
        "tiny",
        [helper.make_tensor_value_info("image", TensorProto.FLOAT, [batch, 3, SIZE, SIZE])],
        outs,
        inits,
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(path))
    return path


def identity_model(path, shape, name="out"):
    """Graph returning its input: checks the normalization done by OnnxBackend."""
    graph = helper.make_graph(
        [helper.make_node("Identity", ["x"], [name])],
        "id",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, shape)],
        [helper.make_tensor_value_info(name, TensorProto.FLOAT, shape)],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.save(model, str(path))
    return path


# --- backends ------------------------------------------------------------------


def test_onnx_backend_normalizes_like_training(tmp_path):
    be = OnnxBackend(identity_model(tmp_path / "id.onnx", [1, 3, 4, 4]), "imagenet")
    assert be.input_size == (4, 4)
    img = np.full((2, 4, 4, 3), (255, 0, 128), np.uint8)
    (out,) = be(img)  # fixed batch 1: run image by image then concatenated
    assert out.shape == (2, 3, 4, 4)
    expected = (np.array([1.0, 0.0, 128 / 255]) - MEAN) / STD
    np.testing.assert_allclose(out[:, :, 0, 0], np.tile(expected, (2, 1)), atol=1e-5)
    unit = normalize(img, "unit")
    assert unit.max() == pytest.approx(1.0) and unit.min() == 0.0


def test_order_outputs_by_name_and_by_size():
    sizes = {"espece": 3, "sante": 2, "classe": 4}
    a, b, c = np.zeros((1, 3)), np.zeros((1, 2)), np.zeros((1, 4))
    assert [o.shape[1] for o in order_outputs(["classe", "espece", "sante"], [c, a, b], sizes)] == [
        3,
        2,
        4,
    ]
    # HEF: renamed outputs, any order -> matched by size
    out = order_outputs(["clf/fc3", "clf/fc1", "clf/fc2"], [c, b, a], sizes)
    assert [o.shape[1] for o in out] == [3, 2, 4]
    with pytest.raises(ValueError, match="candidates"):
        order_outputs(["x", "y", "z"], [a, a, c], sizes)


def test_softmax_entropy():
    p = softmax(np.array([[0.0, 0.0], [10.0, -10.0]]))
    np.testing.assert_allclose(p.sum(1), 1)
    h = entropy(p)
    assert h[0] == pytest.approx(1.0) and h[1] < 0.01


def test_edge_classifier(tmp_path):
    clf = EdgeClassifier(OnnxBackend(tiny_classifier(tmp_path / "clf.onnx")), LABELS, batch=2)
    crops = [np.random.default_rng(i).integers(0, 255, (30 + i, 20, 3), np.uint8) for i in range(3)]
    rows = clf(crops)
    assert len(rows) == 3
    for r in rows:
        assert r["espece"] in LABELS["especes"] and r["classe"] in LABELS["classes"]
        assert 0 <= r["sante_conf"] <= 1 and 0 <= r["entropie"] <= 1
        p_anormal = r["sante_conf"] if r["sante"] == "anormal" else 1 - r["sante_conf"]
        assert r["p_anormal"] == pytest.approx(p_anormal, abs=1e-6)


# --- YOLO ------------------------------------------------------------------------


def test_letterbox_roundtrip():
    img = np.zeros((300, 600, 3), np.uint8)
    out, r, pad = letterbox(img, (640, 640))
    assert out.shape == (640, 640, 3) and r == pytest.approx(640 / 600)
    assert pad == (0, 160)
    box = np.array([[60, 30, 300, 150]], np.float32)
    in_lb = box * r + np.array([pad[0], pad[1], pad[0], pad[1]])
    np.testing.assert_allclose(unletterbox(in_lb, r, pad, img.shape), box, atol=1e-3)


def test_decode_yolov8_filters_class_and_nms():
    # 4 anchors, 3 classes: two overlapping leaves, one far leaf, one fruit
    raw = np.zeros((7, 4), np.float32)
    raw[:4] = np.array(
        [[100, 100, 40, 40], [102, 101, 40, 40], [300, 300, 50, 50], [200, 200, 30, 30]]
    ).T
    raw[4, :3] = [0.9, 0.8, 0.6]  # feuille
    raw[6, 3] = 0.95  # fruit
    boxes, conf = decode_yolov8(raw, conf=0.25, keep_class=0, iou=0.7)
    assert len(boxes) == 2
    np.testing.assert_allclose(conf, [0.9, 0.6])
    np.testing.assert_allclose(boxes[0], [80, 80, 120, 120])


def test_parse_hailo_nms():
    per_class = [np.array([[0.1, 0.2, 0.5, 0.6, 0.9], [0.0, 0.0, 0.1, 0.1, 0.1]]), np.zeros((0, 5))]
    boxes, conf = parse_hailo_nms(per_class, (640, 640), conf=0.25, keep_class=0)
    np.testing.assert_allclose(boxes, [[128, 64, 384, 320]])
    assert conf.tolist() == pytest.approx([0.9])


def test_edge_yolo_maps_back_to_image():
    class FakeBackend:
        input_size = (640, 640)
        output_names = ["out"]

        def __call__(self, batch):
            raw = np.zeros((1, 5, 1), np.float32)
            raw[0, :, 0] = [320, 320, 64, 64, 0.9]  # centre of the letterboxed input
            return [raw]

    boxes, conf = EdgeYolo(FakeBackend())(np.zeros((320, 640, 3), np.uint8))
    np.testing.assert_allclose(boxes, [[288, 128, 352, 192]], atol=1e-3)


# --- preprocess --------------------------------------------------------------------


def test_gray_card_white_balance():
    img = np.full((40, 40, 3), (180, 120, 200), np.uint8)  # pink LED cast on a grey card
    out = gray_card_wb(img, (0, 0, 10, 10))
    patch = out[:10, :10].reshape(-1, 3).mean(0)
    assert patch.max() - patch.min() <= 2
    small, s = resize_max(np.zeros((1000, 2000, 3), np.uint8), 500)
    assert small.shape[:2] == (250, 500) and s == 0.25
    with pytest.raises(ValueError):
        gray_card_wb(img, (5, 5, 5, 5))


# --- pipeline ------------------------------------------------------------------------


def fake_classifier(crops):
    return [
        {
            "espece": "tomate",
            "espece_conf": 0.9,
            "sante": "anormal",
            "sante_conf": 0.8,
            "classe": "tomate/maladie/mildiou",
            "classe_conf": 0.7,
            "p_anormal": 0.8,
            "entropie": 0.7,
        }
        for _ in crops
    ]


def scene():
    img = np.full((200, 300, 3), (110, 90, 70), np.uint8)
    cv2.circle(img, (75, 100), 30, (50, 150, 40), -1)
    return img


TS = datetime(2026, 10, 12, 14, 0, tzinfo=UTC)


def test_pipeline_with_detector_gives_contract_message():
    det = lambda img: (np.array([[10, 20, 110, 120]], float), np.array([0.9]))  # noqa: E731
    pipe = EdgePipeline(fake_classifier, "clf-test-v1", det, anomaly=lambda imgs, e: 0.3)
    result, extras = pipe(scene(), "cam-z1-a", TS)
    assert result.image_id == "cam-z1-a-20261012T140000"
    assert result.detections[0].bbox == pytest.approx((10 / 300, 20 / 200, 100 / 300, 100 / 200))
    assert result.score_anomalie == 0.3 and extras["anomalie_evaluee"]
    assert result.surface_verte_px == pytest.approx(np.pi * 30**2, rel=0.05)
    topic = vision_topic("z1", "cam-z1-a")
    assert decode(topic, encode(result)) == result


def test_pipeline_fallbacks_without_leaf():
    no_leaf = lambda img: (np.zeros((0, 4)), np.zeros(0))  # noqa: E731
    pipe = EdgePipeline(fake_classifier, "clf-test-v1", no_leaf)
    result, extras = pipe(scene(), "cam-z1-a", TS)
    assert len(result.detections) == 1 and result.detections[0].bbox is None  # whole image
    assert result.score_anomalie == 0.0 and not extras["anomalie_evaluee"]

    plants = [Plant("t1", (0, 0, 150, 200)), Plant("t2", (150, 0, 300, 200))]
    result, extras = pipe(scene(), "cam-z1-a", TS, plants)
    assert [d.bbox for d in result.detections] == [(0, 0, 0.5, 1), (0.5, 0, 0.5, 1)]
    assert extras["croissance"]["t2"]["surface_px"] == 0
    assert extras["croissance"]["t2"]["teinte_moy"] is None  # NaN cleaned for strict JSON
    assert isinstance(result, VisionResult)


def test_norm_bbox_clips():
    assert norm_bbox((-10, -10, 400, 100), (200, 300)) == (0, 0, 1, 0.5)
