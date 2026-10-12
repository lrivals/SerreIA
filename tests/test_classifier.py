"""Phase 1 classifier (docs/03-classifieur.md) on synthetic data: no data/ needed."""

import cv2
import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("timm")
pytest.importorskip("albumentations")

from vision.datasets.augment import (  # noqa: E402
    BackgroundPaster,
    build_transform,
    leaf_mask,
)
from vision.datasets.batch_augment import (  # noqa: E402
    MEAN,
    STD,
    BatchAugment,
    coarse_dropout,
    jpeg,
    led_tint,
)
from vision.datasets.dataset import (  # noqa: E402
    IGNORE_INDEX,
    LabelSpace,
    PlantDataset,
    drop_contradictory_groups,
    sampler_weights,
)
from vision.datasets.taxonomy import load_taxonomy  # noqa: E402
from vision.eval.metrics import (  # noqa: E402
    Predictions,
    classe_metrics,
    expected_calibration_error,
    sante_metrics,
    top_k_accuracy,
)
from vision.models.multihead import MultiHeadClassifier  # noqa: E402
from vision.train.config import ROOT, apply_overrides, deep_merge, load_config  # noqa: E402

SIZE = 64
SAIN, MILDIOU, BRULURE = "tomate/sain/sain", "tomate/maladie/mildiou", "tomate/maladie/brulure_ccmt"
ROWS = {  # classe -> (source, espece, etat, sante, ambigu)
    SAIN: ("plantvillage", "tomate", "sain", "sain", False),
    MILDIOU: ("plantvillage", "tomate", "maladie", "anormal", False),
    BRULURE: ("ccmt", "tomate", "maladie", "anormal", True),
}


@pytest.fixture(scope="module")
def labels():
    return LabelSpace.from_taxonomy(load_taxonomy())


def _leaf(color, bg) -> tuple[np.ndarray, np.ndarray]:
    """Colour image (leaf on a uniform background) and its segmented/ counterpart."""
    img = np.full((SIZE, SIZE, 3), bg, np.uint8)
    seg = np.zeros_like(img)
    for canvas in (img, seg):
        cv2.ellipse(canvas, (32, 32), (20, 12), 30, 0, 360, color, -1)
    return img, seg


def _write(path, rgb):
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))


@pytest.fixture()
def data_dir(tmp_path):
    """Tiny index: 3 classes x splits, PlantDoc crops, masks and backgrounds."""
    rng = np.random.default_rng(0)
    rows, g = [], 0
    for classe, (source, espece, etat, sante, ambigu) in ROWS.items():
        color = (40, 160, 40) if sante == "sain" else (150, 120, 30)
        for split, n in (("train", 6), ("val", 3), ("test", 3), ("test_xdomain", 3)):
            if split == "test_xdomain" and ambigu:
                continue
            src = "plantdoc" if split == "test_xdomain" else source
            for k in range(n):
                rel = f"{src}/{classe.replace('/', '_')}/{split}_{k}.png"
                img, seg = _leaf(color, tuple(int(v) for v in rng.integers(100, 200, 3)))
                _write(tmp_path / rel, img)
                mask = None
                if src == "plantvillage":
                    mask = rel.replace(".png", "_seg.png")
                    _write(tmp_path / mask, seg)
                rows.append(
                    dict(path=rel, source=src, espece=espece, etat=etat, classe=classe,
                         sante=sante, ambigu=ambigu, groupe=g, split=split, mask_path=mask)
                )  # fmt: skip
                g += 1
    pd.DataFrame(rows).to_parquet(tmp_path / "index.parquet")
    for i, c in enumerate([(200, 30, 30), (30, 30, 200)]):
        _write(tmp_path / "backgrounds" / f"bg{i}.png", np.full((96, 128, 3), c, np.uint8))
    return tmp_path


# --- labels and dataset ---


def test_label_space_ambiguous(labels):
    df = pd.DataFrame(
        {"espece": ["tomate", "tomate"], "sante": ["sain", "anormal"], "classe": [SAIN, BRULURE]}
    )
    y = labels.encode(df)
    assert BRULURE not in labels.classes
    assert y[0, 2] == labels.classes.index(SAIN)
    assert y[1, 2] == IGNORE_INDEX
    assert y[1, 1] == labels.sante.index("anormal")
    assert LabelSpace.from_dict(labels.to_dict()) == labels


def test_drop_contradictory_groups():
    df = pd.DataFrame(
        {
            "groupe": [1, 1, 2, 2, 3],
            "classe": ["a", "b", "a", "a", "c"],
            "source": ["ccmt"] * 5,
        }
    )
    assert drop_contradictory_groups(df)["groupe"].tolist() == [2, 2, 3]


def test_sampler_weights():
    w = sampler_weights(pd.Series(["a"] * 4 + ["b"]))
    assert w[0] == pytest.approx(0.5)
    assert w[4] == pytest.approx(1.0)
    # each class's total mass is proportional to sqrt(count)
    assert w[:4].sum() / w[4] == pytest.approx(2.0)


def test_dataset_item(data_dir, labels):
    df = pd.read_parquet(data_dir / "index.parquet")
    ds = PlantDataset(df, labels, build_transform("eval", 32), data_dir)
    x, y = ds[0]
    assert x.shape == (3, 32, 32) and x.dtype == torch.uint8
    assert y.shape == (3,) and y.dtype == torch.int64


# --- augmentations ---


@pytest.mark.parametrize("level", ["eval", "light", "strong"])
def test_build_transform(level):
    img = np.random.default_rng(0).integers(0, 255, (80, 100, 3), dtype=np.uint8)
    out = build_transform(level, 48)(image=img)["image"]
    assert out.shape == (3, 48, 48) and out.dtype == torch.uint8


@pytest.mark.parametrize("level", ["eval", "light", "strong"])
def test_batch_augment(level):
    torch.manual_seed(0)
    x = torch.randint(0, 256, (6, 3, 48, 48), dtype=torch.uint8)
    out = BatchAugment(level)(x)
    assert out.shape == x.shape and out.dtype == torch.float32
    assert torch.isfinite(out).all()
    lo = (0 - torch.tensor(MEAN)) / torch.tensor(STD)
    hi = (1 - torch.tensor(MEAN)) / torch.tensor(STD)
    assert (out >= lo.view(1, 3, 1, 1) - 1e-5).all() and (out <= hi.view(1, 3, 1, 1) + 1e-5).all()
    if level != "strong":  # normalization only, as albumentations' Normalize
        ref = (x.float() / 255 - torch.tensor(MEAN).view(1, 3, 1, 1)) / torch.tensor(STD).view(
            1, 3, 1, 1
        )
        assert torch.allclose(out, ref, atol=1e-6)


def test_build_transform_unknown():
    with pytest.raises(ValueError):
        build_transform("extreme", 48)


def test_led_tint_boosts_red_blue():
    out = led_tint(torch.full((16, 3, 4, 4), 0.4))
    assert (out[:, 0] >= 0.4).all() and (out[:, 1] <= 0.4).all() and (out[:, 2] >= 0.4).all()


def test_jpeg_and_dropout():
    x = torch.rand(4, 3, 32, 32)
    out = jpeg(x, torch.tensor([1.0, 0.0, 1.0, 0.0]))
    assert torch.equal(out[1], x[1]) and not torch.equal(out[0], x[0])
    holes = coarse_dropout(torch.ones(8, 3, 40, 40))
    zero = (holes == 0).float().mean((1, 2, 3))
    assert ((zero > 0) & (zero < 0.5)).all()


def test_leaf_mask_fills_lesions():
    _, seg = _leaf((40, 160, 40), 0)
    cv2.circle(seg, (32, 32), 4, (0, 0, 0), -1)  # dark lesion inside the leaf
    seg[2, 2] = 255  # isolated speck outside
    m = leaf_mask(seg)
    assert m[32, 32] == 1
    assert m[2, 2] == 0
    assert m[0, 63] == 0


def test_background_paster(data_dir):
    img, seg = _leaf((40, 160, 40), (128, 128, 128))
    paster = BackgroundPaster(data_dir / "backgrounds", p=1.0, p_multi=0.0, feather=0, harmonize=0)
    out = paster(img, seg)
    assert out.shape == img.shape
    assert (out[32, 32] == img[32, 32]).all()  # leaf kept
    corner = out[0, 0].tolist()
    assert corner in ([200, 30, 30], [30, 30, 200])  # background replaced


def test_background_paster_multi_leaf(data_dir):
    img, seg = _leaf((40, 160, 40), (128, 128, 128))
    pool = sorted(data_dir.rglob("*_seg.png"))
    paster = BackgroundPaster(
        data_dir / "backgrounds", pool, p=1.0, p_multi=1.0, extra_leaves=(2, 3), harmonize=0.5
    )
    for _ in range(5):
        assert paster(img, seg).shape == img.shape


def test_background_paster_requires_backgrounds(tmp_path):
    with pytest.raises(FileNotFoundError, match="backgrounds"):
        BackgroundPaster(tmp_path / "vide")


# --- model ---


def test_model_outputs_and_freeze(labels):
    sizes = labels.sizes()
    model = MultiHeadClassifier("efficientnet_b0", **{f"n_{k}": v for k, v in sizes.items()},
                                pretrained=False)  # fmt: skip
    out = model(torch.zeros(2, 3, SIZE, SIZE))
    assert [o.shape for o in out] == [
        (2, sizes["espece"]),
        (2, sizes["sante"]),
        (2, sizes["classe"]),
    ]
    model.set_backbone_trainable(False)
    assert not any(p.requires_grad for p in model.backbone.parameters())
    assert all(p.requires_grad for p in model.heads.parameters())
    n_groups = sum(len(g["params"]) for g in model.param_groups(1e-3, 3e-4, 0.05))
    assert n_groups == len(list(model.parameters()))
    assert min(model.last_conv(SIZE).weight.shape) >= 1


# --- metrics ---


def _preds(sante_logits, sante_y, classe_logits=None, classe_y=None) -> Predictions:
    n = len(sante_y)
    classe_logits = np.zeros((n, 3)) if classe_logits is None else np.asarray(classe_logits)
    classe_y = np.zeros(n, int) if classe_y is None else np.asarray(classe_y)
    logits = {
        "espece": np.zeros((n, 2), np.float32),
        "sante": np.asarray(sante_logits, np.float32),
        "classe": classe_logits.astype(np.float32),
    }
    targets = np.stack([np.zeros(n, int), np.asarray(sante_y), classe_y], 1)
    return Predictions(logits, targets)


def test_sante_metrics_recall_anormal():
    # 3 anormal: 2 found; 1 sain wrongly flagged
    p = _preds([[0, 5], [0, 5], [5, 0], [0, 5], [5, 0]], [1, 1, 1, 0, 0])
    m = sante_metrics(p)
    assert m["sante/recall_anormal"] == pytest.approx(2 / 3)
    assert m["sante/precision_anormal"] == pytest.approx(2 / 3)


def test_classe_metrics_ignore_and_restrict(labels):
    logits = [[3, 2, 0], [0, 1, 3], [0, 3, 1], [5, 0, 0]]
    y = [0, 1, 1, IGNORE_INDEX]
    m = classe_metrics(_preds(np.zeros((4, 2)), [0] * 4, logits, y), labels)
    assert m["classe/n"] == 3
    assert m["classe/accuracy"] == pytest.approx(2 / 3)
    assert m["classe/top3"] == 1.0
    only_first = classe_metrics(
        _preds(np.zeros((4, 2)), [0] * 4, logits, y), labels, [labels.classes[0]]
    )
    assert only_first["classe/n"] == 1


def test_top_k_and_ece():
    probs = np.array([[0.6, 0.3, 0.1], [0.2, 0.3, 0.5]])
    assert top_k_accuracy(probs, np.array([1, 0]), 1) == 0.0
    assert top_k_accuracy(probs, np.array([1, 0]), 2) == 0.5
    # always right with confidence 1 -> perfectly calibrated
    assert expected_calibration_error(np.eye(3), np.arange(3)) == pytest.approx(0.0)
    # always wrong with confidence 0.9 -> ECE 0.9
    wrong = np.array([[0.9, 0.1]] * 4)
    assert expected_calibration_error(wrong, np.ones(4, int)) == pytest.approx(0.9)


# --- config ---


def test_config_inheritance(tmp_path):
    (tmp_path / "base.yaml").write_text("a: {b: 1, c: 2}\nd: 3\n")
    (tmp_path / "child.yaml").write_text("_base_: base.yaml\na: {c: 5}\n")
    cfg = load_config(tmp_path / "child.yaml")
    assert cfg == {"a": {"b": 1, "c": 5}, "d": 3}
    cfg = apply_overrides(cfg, ["a.b=0.5", "e.f=[1, 2]"])
    assert cfg["a"]["b"] == 0.5 and cfg["e"]["f"] == [1, 2]
    assert deep_merge({"x": {"y": 1}}, {"x": 2}) == {"x": 2}


def test_repo_ablation_configs():
    a = load_config(ROOT / "configs/ablations/A_baseline.yaml")
    d = load_config(ROOT / "configs/ablations/D_ccmt.yaml")
    e = load_config(ROOT / "configs/ablations/E_convnext.yaml")
    assert a["augment"]["level"] == "light" and not a["augment"]["background"]["enabled"]
    assert d == load_config(ROOT / "configs/clf_effnet_b0.yaml")
    assert e["model"]["backbone"] == "convnext_nano"


# --- end to end: train, reload, evaluate, Grad-CAM, ONNX ---


def test_end_to_end(data_dir, tmp_path):
    pytest.importorskip("mlflow")
    from vision.eval.cross_domain_eval import run_eval
    from vision.eval.gradcam import compute_cams
    from vision.export.to_onnx import compare, export_onnx
    from vision.train.train_classifier import load_checkpoint, make_loader, run

    cfg = apply_overrides(
        load_config(ROOT / "configs/clf_effnet_b0.yaml"),
        [
            f"data.index={data_dir / 'index.parquet'}",
            f"data.data_dir={data_dir}",
            "data.size=64",
            "data.num_workers=0",
            f"augment.background.dir={data_dir / 'backgrounds'}",
            "augment.background.p=1.0",
            "model.pretrained=false",
            "train.epochs=2",
            "train.freeze_epochs=1",
            "train.batch_size=4",
            f"mlflow.tracking_uri={tmp_path / 'mlruns' / 'mlflow.db'}",
        ],
    )
    run_dir = run(cfg, torch.device("cpu"), runs_dir=tmp_path / "runs")
    assert (run_dir / "best.pt").exists() and (run_dir / "last.pt").exists()

    model, labels, cfg2 = load_checkpoint(run_dir / "best.pt")
    assert cfg2["data"]["size"] == 64

    payload = run_eval(run_dir / "best.pt", torch.device("cpu"), out_dir=tmp_path / "rep")
    assert set(payload["results"]) == {"test", "test_xdomain"}
    assert "ambigu" in payload["results"]["test"]
    assert payload["classes_communes_plantdoc"] == [MILDIOU, SAIN]
    assert (tmp_path / "rep" / "metrics.json").exists()
    assert list((tmp_path / "rep").glob("cm_test_xdomain_plantdoc_*.png"))

    df = pd.read_parquet(data_dir / "index.parquet").head(4)
    x = torch.stack([make_loader(df, labels, cfg2, train=False).dataset[i][0] for i in range(4)])
    x = BatchAugment("eval")(x)
    cams = compute_cams(model, "sante", x, [0, 1, 0, 1])
    assert cams.shape == (4, 64, 64)

    onnx_path = tmp_path / "model.onnx"
    export_onnx(model, onnx_path, 64)
    res = compare(model, onnx_path, [x])
    assert res["n"] == 4
    assert max(res[f"{h}/max_abs_gap"] for h in ("espece", "sante", "classe")) < 1e-3


# --- phase 1 report ---


def test_phase1_report(tmp_path):
    import json

    from vision.eval.ablation_report import load_registry, save_registry, write_phase1_report

    def metrics(f1_sante, recall):
        return {
            "results": {
                "test": {"all": {"sante/f1_macro": f1_sante, "classe/f1_macro": 0.9}},
                "test_xdomain": {"all": {"sante/recall_anormal": recall}},
            }
        }

    for run_id, m in {"run_a": metrics(0.98, 0.85), "run_b": metrics(0.95, 0.6)}.items():
        (tmp_path / run_id).mkdir()
        (tmp_path / run_id / "metrics.json").write_text(json.dumps(m))
    runs = {"A_baseline": "run_a", "B_strong_aug": "run_b", "C_background": "absent"}
    save_registry(runs, tmp_path / "ablations.json")
    assert load_registry(tmp_path / "ablations.json") == runs

    text = write_phase1_report(reports_dir=tmp_path).read_text(encoding="utf-8")
    assert "| A_baseline | `run_a` | 0.980 | 0.900 | 0.850 |" in text
    assert "**A_baseline** : ✅" in text and "❌ rappel" in text
    assert "C_background (absent)" in text
