"""Phase 2 detection (docs/04-detection-yolo.md §1–3) on synthetic data: no data/ needed."""

import json
import os
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import pytest
import yaml
from PIL import Image

pytest.importorskip("torch")
pytest.importorskip("albumentations")

from vision.datasets.prepare import voc_boxes  # noqa: E402
from vision.eval.two_stage import Scene, TwoStagePipeline, crop, evaluate, match  # noqa: E402
from vision.labeling import build_yolo_dataset as byd  # noqa: E402
from vision.labeling.label_studio import (  # noqa: E402
    Prediction,
    export_to_yolo,
    local_path,
    task_boxes,
    to_tasks,
)
from vision.labeling.pseudo_labels import Filters, cam_peaks, ls_url, refine  # noqa: E402
from vision.labeling.yolo_format import (  # noqa: E402
    CLASSES,
    box_iou,
    from_yolo,
    label_path,
    mask_to_box,
    nms,
    read_labels,
    to_yolo,
    write_data_yaml,
    write_labels,
)
from vision.train.config import ROOT, load_config  # noqa: E402

# ------------------------------------------------------------------------- YOLO format


def test_yolo_roundtrip():
    box = (10.0, 20.0, 50.0, 100.0)
    y = to_yolo(0, box, 200, 100)
    assert y == pytest.approx((0, 0.15, 0.6, 0.2, 0.8))
    assert from_yolo(y, 200, 100)[1] == pytest.approx(box)


def test_labels_io(tmp_path):
    img = tmp_path / "ds" / "images" / "train" / "a.jpg"
    lbl = label_path(img)
    assert lbl == tmp_path / "ds" / "labels" / "train" / "a.txt"
    boxes = [(0, 0.5, 0.5, 0.2, 0.3), (2, 0.1, 0.9, 0.05, 0.05)]
    write_labels(lbl, boxes)
    assert read_labels(lbl) == [pytest.approx(b) for b in boxes]
    write_labels(lbl, [])  # background image
    assert lbl.read_text() == "" and read_labels(lbl) == []


def test_data_yaml_has_no_path(tmp_path):
    cfg = yaml.safe_load(write_data_yaml(tmp_path).read_text(encoding="utf-8"))
    assert "path" not in cfg  # Ultralytics then resolves the splits next to the file
    assert cfg["train"] == "images/train" and cfg["names"] == dict(enumerate(CLASSES))


def test_mask_to_box():
    m = np.zeros((40, 60), np.uint8)
    assert mask_to_box(m) is None
    m[5:10, 20:31] = 1
    assert mask_to_box(m) == (20, 5, 31, 10)


def test_iou_and_nms():
    a = np.array([[0, 0, 10, 10], [5, 0, 15, 10], [50, 50, 60, 60]], float)
    iou = box_iou(a, a)
    assert np.diag(iou) == pytest.approx(1.0)
    assert iou[0, 1] == pytest.approx(50 / 150)
    assert iou[0, 2] == 0
    assert list(nms(a, np.array([0.9, 0.8, 0.7]), iou=0.5)) == [0, 1, 2]
    assert list(nms(a, np.array([0.9, 0.8, 0.7]), iou=0.3)) == [0, 2]
    assert list(nms(a, np.array([0.9, 0.95, 0.7]), iou=0.2)) == [1, 2]


# ------------------------------------------------------------------------- dataset build


def _voc(path: Path, size: tuple[int, int] | None, boxes: list[tuple[str, tuple]]) -> None:
    objs = "".join(
        f"<object><name>{n}</name><bndbox><xmin>{b[0]}</xmin><ymin>{b[1]}</ymin>"
        f"<xmax>{b[2]}</xmax><ymax>{b[3]}</ymax></bndbox></object>"
        for n, b in boxes
    )
    sz = f"<size><width>{size[0]}</width><height>{size[1]}</height></size>" if size else ""
    path.write_text(f"<annotation>{sz}{objs}</annotation>")


def _jpeg(path: Path, w: int, h: int, seed: int, exif_rotation: bool = False) -> None:
    rng = np.random.default_rng(seed)
    img = Image.fromarray(rng.integers(0, 255, (h, w, 3), dtype=np.uint8))
    exif = Image.Exif()
    if exif_rotation:
        exif[byd.EXIF_ORIENTATION] = 6
    img.save(path, quality=90, exif=exif)


def test_voc_boxes_rescaled_and_clipped(tmp_path):
    _jpeg(tmp_path / "a.jpg", 200, 100, 0)
    # Annotated on a half-size copy; the second box overflows the image.
    boxes = [("Tomato leaf", (10, 5, 20, 15)), ("x", (90, 40, 120, 60))]
    _voc(tmp_path / "a.xml", (100, 50), boxes)
    img, size, boxes = voc_boxes(tmp_path / "a.xml")
    assert img == tmp_path / "a.jpg" and size == (200, 100)
    assert boxes[0] == ("Tomato leaf", (20, 10, 40, 30))
    assert boxes[1][1] == (180, 80, 200, 100)
    (tmp_path / "a.jpg").unlink()
    assert voc_boxes(tmp_path / "a.xml") is None


def test_plantdoc_splits_grouped_without_test_leak():
    n = 40
    rng = np.random.default_rng(0)
    phash = rng.integers(0, 2**63, n, dtype=np.uint64)
    dhash = rng.integers(0, 2**63, n, dtype=np.uint64)
    phash[1], dhash[1] = phash[0], dhash[0]  # train 0 ~ train 1: same group
    phash[30], dhash[30] = phash[2], dhash[2]  # train 2 ~ test 30: train 2 dropped
    df = pd.DataFrame({"path": [f"p{i}" for i in range(n)],
                       "orig": ["train"] * 30 + ["test"] * 10})  # fmt: skip
    out = byd.plantdoc_splits(df, np.stack([phash, dhash], 1))
    assert "p2" not in set(out["path"])
    assert set(out.loc[out["orig"] == "test", "split"]) == {"test"}
    assert set(out.loc[out["orig"] == "train", "split"]) == {"train", "val"}
    assert (out.groupby("groupe")["split"].nunique() == 1).all()
    s = out.set_index("path")["split"]
    assert s["p0"] == s["p1"]


def _truncate(path: Path) -> None:
    data = path.read_bytes()
    path.write_bytes(data[:-2])


def test_needs_copy(tmp_path):
    _jpeg(tmp_path / "ok.jpg", 32, 32, 0)
    _jpeg(tmp_path / "rot.jpg", 32, 32, 1, exif_rotation=True)
    _jpeg(tmp_path / "cut.jpg", 32, 32, 2)
    _truncate(tmp_path / "cut.jpg")
    Image.new("RGB", (8, 8)).save(tmp_path / "a.png")
    assert not byd.needs_copy(tmp_path / "ok.jpg")
    assert byd.needs_copy(tmp_path / "rot.jpg")
    assert byd.needs_copy(tmp_path / "cut.jpg")
    assert not byd.needs_copy(tmp_path / "a.png")


@pytest.fixture
def data_dir(tmp_path):
    """Tiny data/: 6 PlantDoc TRAIN, 2 TEST images and 2 PlantVillage leaves with masks."""
    d = tmp_path / "data"
    for split, n in (("train", 6), ("test", 2)):
        (d / "plantdoc" / split).mkdir(parents=True)
        for i in range(n):
            stem = f"{split}{i}"
            _jpeg(d / "plantdoc" / split / f"{stem}.jpg", 64, 48, hash(stem) % 1000,
                  exif_rotation=(stem == "train0"))  # fmt: skip
            _voc(d / "plantdoc" / split / f"{stem}.xml", (64, 48),
                 [("Tomato leaf", (4, 4, 30, 30)), ("Tomato leaf", (1, 1, 3, 3))])  # fmt: skip
    rows = []
    for i, split in enumerate(("train", "test")):
        cls = "Tomato___healthy"
        for sub in ("color", "segmented"):
            (d / "plantvillage" / sub / cls).mkdir(parents=True, exist_ok=True)
        seg = np.zeros((40, 40, 3), np.uint8)
        cv2.circle(seg, (20, 20), 10, (0, 160, 0), -1)
        Image.fromarray(seg).save(d / "plantvillage" / "segmented" / cls / f"l{i}_final_masked.png")
        _jpeg(d / "plantvillage" / "color" / cls / f"l{i}.jpg", 40, 40, i)
        rows.append(
            {
                "path": f"plantvillage/color/{cls}/l{i}.jpg",
                "source": "plantvillage",
                "classe": "tomate/sain/sain",
                "split": split,
                "mask_path": f"plantvillage/segmented/{cls}/l{i}_final_masked.png",
            }
        )
    pd.DataFrame(rows).to_parquet(d / "index.parquet")
    return d


def test_build_yolo_dataset(data_dir):
    out = data_dir / "yolo"
    manifest = byd.build(data_dir, out, pv_per_class=5, workers=1)
    assert set(manifest["split"]) <= {"train", "val", "test"}
    assert (manifest.loc[manifest["source"] == "plantdoc", "n_boxes"] == 1).all()  # tiny box out
    pv = manifest[manifest["source"] == "plantvillage"].set_index("path")["split"]
    assert pv["plantvillage/color/Tomato___healthy/l1.jpg"] == "test"  # split of the index
    for r in manifest.itertuples():
        img = out / r.image
        assert img.exists() and label_path(img).exists()
    # EXIF-rotated image: real file; others: relative symlinks inside data/.
    rotated = manifest.loc[manifest["path"].str.endswith("train0.jpg"), "image"].item()
    assert not (out / rotated).is_symlink()
    linked = [out / i for i in manifest["image"] if (out / i).is_symlink()]
    assert linked and all(not os.readlink(p).startswith("/") for p in linked)
    # PlantVillage box: the disk of radius 10 at (20, 20).
    pv_img = out / manifest.loc[manifest["source"] == "plantvillage", "image"].iloc[0]
    ((_, box),) = [from_yolo(b, 40, 40) for b in read_labels(label_path(pv_img))]
    assert box == pytest.approx((10, 10, 31, 31), abs=1)
    assert yaml.safe_load((out / "data.yaml").read_text())["val"] == "images/val"
    # Rebuild from scratch: idempotent.
    again = byd.build(data_dir, out, pv_per_class=5, workers=1)
    assert len(again) == len(manifest)


# ------------------------------------------------------------------------- Label Studio


def test_label_studio_roundtrip(tmp_path):
    img_dir = tmp_path / "imgs"
    img_dir.mkdir()
    Image.new("RGB", (200, 100)).save(img_dir / "a.jpg")
    pred = Prediction("/data/local-files/?d=imgs/a.jpg", 200, 100,
                      boxes=[(10, 20, 50, 100)], labels=["feuille"], scores=[0.8])  # fmt: skip
    (task,) = to_tasks([pred])
    r = task["predictions"][0]["result"][0]
    assert r["value"]["x"] == pytest.approx(5) and r["value"]["height"] == pytest.approx(80)
    assert task["predictions"][0]["score"] == pytest.approx(0.8)
    # Export: the annotator accepted the prediction; a second task is not annotated.
    task["annotations"] = [{"result": task["predictions"][0]["result"]}]
    other = {"data": {"image": "/data/local-files/?d=imgs/b.jpg"}, "annotations": []}
    assert task_boxes(task) == [pytest.approx(to_yolo(0, (10, 20, 50, 100), 200, 100))]
    export = tmp_path / "export.json"
    export.write_text(json.dumps([task, other]))
    out = tmp_path / "ds"
    assert export_to_yolo(export, out, images_root=tmp_path) == 1
    assert (out / "images" / "train" / "a.jpg").exists()
    assert len(read_labels(out / "labels" / "train" / "a.txt")) == 1
    assert yaml.safe_load((out / "data.yaml").read_text()).keys() == {"train", "names"}


def test_local_path(tmp_path):
    url = "/data/local-files/?d=serre/x%20y.jpg"
    assert local_path(url, tmp_path) == tmp_path / "serre" / "x y.jpg"
    assert local_path("/data/upload/3/abcd1234-photo.jpg", tmp_path) == tmp_path / "photo.jpg"
    assert ls_url(tmp_path / "a" / "b.jpg", tmp_path) == "/data/local-files/?d=a/b.jpg"


# ------------------------------------------------------------------------- pseudo-labels


def _blob(shape, center, sigma, amp=1.0):
    yy, xx = np.mgrid[: shape[0], : shape[1]]
    return amp * np.exp(-((xx - center[0]) ** 2 + (yy - center[1]) ** 2) / (2 * sigma**2))


def test_cam_peaks():
    cam = _blob((100, 100), (20, 30), 5) + _blob((100, 100), (70, 60), 5, 0.8)
    cam += _blob((100, 100), (80, 10), 3, 0.3)  # below the threshold
    peaks = cam_peaks(cam, k=5, thresh=0.5)
    assert peaks.tolist() == [[20, 30], [70, 60]]
    assert len(cam_peaks(cam, k=1)) == 1
    assert len(cam_peaks(np.zeros((10, 10)), k=3)) == 0


class FakeSegmenter:
    """Point -> disk of radius 10; box -> the box itself; fixed score."""

    def __init__(self, score=0.9):
        self.score = score

    def set_image(self, img):
        self.shape = img.shape[:2]

    def from_point(self, xy):
        m = np.zeros(self.shape, np.uint8)
        cv2.circle(m, (int(xy[0]), int(xy[1])), 10, 1, -1)
        return m.astype(bool), self.score

    def from_box(self, box):
        m = np.zeros(self.shape, bool)
        x0, y0, x1, y1 = map(int, box)
        m[y0:y1, x0:x1] = True
        return m, self.score


def test_refine_filters_and_nms():
    img = np.zeros((100, 100, 3), np.uint8)
    pts = np.array([[30, 30], [31, 30], [70, 70]], np.float32)  # first two: same leaf
    boxes, scores = refine(FakeSegmenter(), img, points=pts)
    assert len(boxes) == 2 and scores == pytest.approx([0.9, 0.9])
    # Area filter: a disk of radius 10 covers ~4 % of the image.
    boxes, _ = refine(FakeSegmenter(), img, points=pts, filters=Filters(min_area=0.1))
    assert len(boxes) == 0
    # Box prompts: score = SAM score × detector confidence.
    det = np.array([[0, 0, 50, 50], [60, 60, 99, 99]], float)
    boxes, scores = refine(FakeSegmenter(), img, boxes=det, prior=np.array([0.9, 0.3]))
    assert len(boxes) == 1 and scores[0] == pytest.approx(0.81)


# ------------------------------------------------------------------------- two stages


def test_crop_margin_clipped():
    img = np.zeros((100, 200, 3), np.uint8)
    assert crop(img, (10, 10, 30, 50), 0.1).shape == (48, 24, 3)
    assert crop(img, (0, 0, 200, 100), 0.5).shape == (100, 200, 3)


def test_match_one_to_one():
    gt = np.array([[0, 0, 10, 10], [20, 20, 30, 30]], float)
    pred = np.array([[1, 1, 10, 10], [0, 0, 9, 9], [50, 50, 60, 60]], float)
    pairs = match(gt, pred)
    assert pairs == [(0, 0)]
    assert match(gt, np.zeros((0, 4))) == []


def _fake_pipeline(boxes):
    """Detector returns fixed boxes; classifier: crop mean > 100 -> anormal."""

    def detector(img):
        return np.array(boxes, float).reshape(-1, 4), np.full(len(boxes), 0.9)

    def classifier(crops):
        out = []
        for c in crops:
            p = float(c.mean() > 100)
            out.append(
                {
                    "espece": "tomate",
                    "sante": "anormal" if p else "sain",
                    "classe": "tomate/sain/sain",
                    "p_anormal": p,
                    "classe_conf": 1.0,
                }
            )
        return out

    return TwoStagePipeline(detector, classifier, margin=0.0)


def test_two_stage_pipeline_and_evaluation(tmp_path):
    img = np.zeros((100, 100, 3), np.uint8)
    img[60:90, 60:90] = 200  # bright leaf -> anormal
    path = tmp_path / "scene.png"
    cv2.imwrite(str(path), img)
    pipe = _fake_pipeline([[10, 10, 40, 40], [60, 60, 90, 90]])
    res = pipe(img)
    assert [leaf.sante for leaf in res.leaves] == ["sain", "anormal"]
    assert res.plante_anormale and res.p_anormal_max == 1.0

    scenes = [
        Scene(path, np.array([[10, 10, 40, 40], [60, 60, 90, 90]], float), ["sain", "anormal"]),
        Scene(path, np.array([[10, 10, 40, 40]], float), ["sain"]),  # healthy scene
    ]
    metrics, results = evaluate(pipe, scenes)
    assert metrics["detection/recall_feuille"] == 1.0
    assert metrics["detection/precision_feuille"] == pytest.approx(3 / 4)
    assert metrics["feuilles/sante_accuracy"] == 1.0
    assert metrics["image/recall_plante_anormale"] == 1.0
    assert metrics["image/faux_positifs_sain"] == 1.0  # the extra bright leaf is detected
    assert evaluate(_fake_pipeline([]), scenes)[0]["detection/recall_feuille"] == 0.0


# ------------------------------------------------------------------------- YOLO training


def test_yolo_config_keys_known_by_ultralytics():
    pytest.importorskip("ultralytics")
    from ultralytics.cfg import DEFAULT_CFG_DICT

    cfg = load_config(ROOT / "configs" / "yolo_v8n.yaml")
    assert set(cfg["yolo"]) <= set(DEFAULT_CFG_DICT)
    assert {"model", "data", "led_tint", "mlflow", "seed"} <= set(cfg)


def test_tint_batch():
    torch = pytest.importorskip("torch")
    pytest.importorskip("ultralytics")
    from vision.train.train_yolo import tint_batch

    x = torch.full((8, 3, 4, 4), 0.5)
    assert torch.equal(tint_batch(x, 0.0), x)
    y = tint_batch(x, 1.0)
    assert (y[:, 1] <= 0.5).all() and (y[:, 0] >= 0.5).all()  # green down, red up
