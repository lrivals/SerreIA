"""Dataset statistics (docs/19 §3–§4) on hand-made index, images and YOLO labels."""

import json
import math

import numpy as np
import pandas as pd
import pytest

from common.report import write_report
from vision.datasets import stats as st


def _index() -> pd.DataFrame:
    """Known imbalance; group 3 in train and val (leak); `b/sain/x` only in ccmt;
    group 7 carries two classes; `c/maladie/z` only in test_xdomain."""
    rows = []

    def add(n, classe, source, split, groupe, w=256, h=256, mask=None):
        for _ in range(n):
            rows.append({
                "path": f"{source}/{classe}/{len(rows)}.jpg", "source": source,
                "espece": classe.split("/")[0], "classe": classe,
                "sante": "sain" if "/sain/" in classe else "anormal",
                "ambigu": classe == "a/maladie/amb", "width": w, "height": h,
                "groupe": groupe if groupe is not None else 1000 + len(rows),
                "split": split, "mask_path": mask,
            })  # fmt: skip

    add(6, "a/sain/x", "plantvillage", "train", None, mask="m.jpg")
    add(2, "a/sain/x", "plantvillage", "test", None, mask="m.jpg")
    add(2, "a/maladie/y", "plantvillage", "train", None, w=128, h=192)
    add(1, "a/maladie/y", "ccmt", "train", 3)
    add(1, "a/maladie/y", "ccmt", "val", 3)
    add(2, "b/sain/x", "ccmt", "train", None)
    add(1, "a/maladie/amb", "ccmt", "train", 7)
    add(1, "b/sain/x", "ccmt", "train", 7)
    add(2, "c/maladie/z", "plantdoc", "test_xdomain", None, w=100, h=400)
    return pd.DataFrame(rows)


def test_imbalance_exact():
    r = st.imbalance([1, 1, 1, 1])
    assert r["gini"] == pytest.approx(0.0)
    assert r["entropie_norm"] == pytest.approx(1.0)
    assert r["n_effectif"] == pytest.approx(4.0)
    r = st.imbalance([1, 3])
    assert r["ratio_max_min"] == 3.0
    assert r["gini"] == pytest.approx(0.25)  # 2*(1+6)/(2*4) - 3/2
    h = -(0.25 * math.log(0.25) + 0.75 * math.log(0.75))
    assert r["entropie_norm"] == pytest.approx(h / math.log(2))
    assert r["n_effectif"] == pytest.approx(math.exp(h))
    assert st.imbalance([0, 5])["k"] == 1


def test_counts_and_levels():
    df = _index()
    c = st.counts(df, "source")
    assert c.loc["All", "All"] == len(df)
    assert c.loc["plantdoc", "test_xdomain"] == 2
    lv = st.imbalance_by_level(df)
    assert lv.loc["sante", "k"] == 2
    tail = st.long_tail(df)
    assert tail.index[0] == "a/sain/x" and tail.iloc[0]["n"] == 8
    assert tail.loc["a/sain/x", "source_majoritaire"] == "plantvillage"
    assert tail.loc["a/maladie/y", "part_majoritaire"] == pytest.approx(0.5)


def test_coverage_mono_source_and_masks():
    df = _index()
    ct, share = st.coverage(df)
    assert share.loc["a/maladie/y", "ccmt"] == pytest.approx(0.5)
    mono = st.mono_source(df)
    assert mono.loc["b/sain/x", "source"] == "ccmt" and mono.loc["b/sain/x", "n"] == 3
    assert "a/maladie/y" not in mono.index
    amb = st.ambiguous_weight(df)
    assert amb["classes"] == ["a/maladie/amb"] and amb["n_images"] == 1
    ms = st.mask_share(df)
    assert ms["plantvillage"] == pytest.approx(0.8) and ms["ccmt"] == 0.0


def test_split_consistency():
    df = _index()
    leaks = st.group_leaks(df)
    assert list(leaks.index) == [3] and leaks.loc[3, "splits"] == ["train", "val"]
    gaps = st.xdomain_gaps(df)
    assert gaps["xdomain_sans_train"] == ["c/maladie/z"]
    assert "a/sain/x" in gaps["train_sans_xdomain"]
    div = st.split_divergence(df)
    assert set(div["js"]) == {"test/train", "test/val", "train/val"} or set(div["js"]) == {
        "train/val",
        "train/test",
        "val/test",
    }
    assert 0 <= min(div["js"].values()) and max(div["js"].values()) <= 1


def test_js_bounds():
    assert st._js(np.array([1.0, 0]), np.array([0, 1.0])) == pytest.approx(1.0)
    assert st._js(np.array([1.0, 2]), np.array([2.0, 4])) == pytest.approx(0.0)


def test_geometry():
    g = st.geometry(_index(), input_size=224)
    assert g.loc["plantdoc", ("aspect", "median")] == pytest.approx(0.25)
    assert g.loc["plantdoc", ("petite", "part<224")] == 1.0
    assert g.loc["plantvillage", ("petite", "part<224")] == pytest.approx(0.2)


def test_groups_and_contradictions():
    df = _index()
    gs = st.group_sizes(df)
    assert gs["max"] == 2 and gs["n_groupes_doublons"] == 2
    c = st.contradictory_groups(df)
    assert c["n_groupes"] == 1 and c["n_images"] == 2
    assert c["paires"].iloc[0][["classe_a", "classe_b"]].tolist() == ["a/maladie/amb", "b/sain/x"]


def test_candidate_pair_distances():
    ph = np.array([0, 0b111, 2**64 - 1, 0b1], dtype=np.uint64)
    dh = np.array([0, 0xFFFF, 0, 0b11], dtype=np.uint64)
    pairs = st.candidate_pair_distances(ph, dh, max_dist=3)
    got = {(int(r.i), int(r.j)): (r.d_phash, r.d_dhash) for r in pairs.itertuples()}
    assert got == {(0, 1): (3, 16), (0, 3): (1, 2), (1, 3): (2, 14)}


def test_read_rejects(tmp_path):
    p = tmp_path / "rej.txt"
    p.write_text("ccmt/raw/Maize/healthy/a.jpg\tOSError: x\nplantdoc/b/c.jpg\tdoublon\n")
    r = st.read_rejects(p)
    assert r["source"].tolist() == ["ccmt", "plantdoc"]
    assert r.loc[0, "dossier"] == "healthy"
    assert st.read_rejects(tmp_path / "absent").empty


def test_photometry_uniform_and_hue():
    gray = np.full((40, 40, 3), 128, np.uint8)
    d = st.photometry(gray)
    assert d["luminosite"] == pytest.approx(128, abs=0.5)
    assert d["contraste"] == 0 and d["nettete"] == 0 and d["fond_uni"] == 1.0
    assert d["teinte"] is None and d["saturation"] == 0
    red = np.zeros((20, 20, 3), np.uint8)
    red[..., 0] = 255
    assert st.photometry(red)["teinte"] == 0.0
    green = np.zeros((20, 20, 3), np.uint8)
    green[..., 1] = 255
    assert st.photometry(green)["teinte"] == 120.0
    assert st.photometry(gray.astype(np.float32) / 255)["luminosite"] == pytest.approx(128, abs=1)


def test_photometry_sharpness_and_background():
    board = (np.indices((40, 40)).sum(axis=0) % 2 * 255).astype(np.uint8)
    board = np.repeat(board[..., None], 3, axis=2)
    d = st.photometry(board)
    assert d["nettete"] > 1000 and d["contraste"] == pytest.approx(127.5, abs=0.5)
    assert d["fond_uni"] == 0.0  # border alternates black / white: nothing near the median
    framed = np.full((40, 40, 3), 90, np.uint8)
    framed[10:30, 10:30] = board[10:30, 10:30]
    assert st.photometry(framed)["fond_uni"] == 1.0


def test_photometry_table_pca_and_gap():
    df = _index()
    rng = np.random.default_rng(0)

    def read(path):
        base = 200 if "plantdoc" in str(path) else 60
        return np.clip(rng.normal(base, 20, (32, 32, 3)), 0, 255).astype(np.uint8)

    t = st.photometry_table(df, data_dir=".", n=len(df), read=read)
    assert len(t) == len(df) and set(st.DESCRIPTORS) <= set(t.columns)
    proj = st.descriptor_pca(t)
    assert proj.shape[0] == len(t) and len(proj.attrs["variance"]) == 2
    gap = st.domain_gap(t)
    assert gap.loc["luminosite", "mediane_cible"] > gap.loc["luminosite", "mediane_ref"]
    assert gap.loc["luminosite", "hors_plage_ref"] == 1.0
    sub = st.stratified_sample(df, 5, 0)
    assert sub.groupby(["source", "classe"]).ngroups == df.groupby(["source", "classe"]).ngroups


# ------------------------------------------------------------------------------- YOLO


@pytest.fixture
def yolo(tmp_path):
    """3 images: a (4 boxes: duplicate pair, a nested box, an overflowing one), b (one
    degenerate box, manifest says 2), c (no labels file)."""
    lab = tmp_path / "labels" / "train"
    lab.mkdir(parents=True)
    (tmp_path / "images" / "train").mkdir(parents=True)
    (lab / "a.txt").write_text(
        "0 0.5 0.5 0.4 0.4\n0 0.5 0.5 0.4 0.39\n0 0.5 0.5 0.1 0.1\n0 0.95 0.5 0.2 0.2\n"
    )
    (lab / "b.txt").write_text("0 0.5 0.5 0.001 0.5\n")
    manifest = pd.DataFrame({
        "path": ["plantdoc/a.jpg", "plantvillage/color/x/b.jpg", "plantdoc/c.jpg"],
        "image": ["images/train/a.jpg", "images/train/b.jpg", "images/train/c.jpg"],
        "split": ["train", "train", "val"], "source": ["plantdoc", "plantvillage", "plantdoc"],
        "width": [640, 256, 320], "height": [320, 256, 320], "n_boxes": [4, 2, 0],
        "groupe": [0.0, np.nan, 0.0],
    })  # fmt: skip
    return tmp_path, manifest


def test_yolo_counts_and_consistency(yolo):
    root, manifest = yolo
    boxes = st.read_yolo_labels(root, manifest)
    assert len(boxes) == 5
    c = st.yolo_counts(manifest, boxes, ("feuille", "plante", "fruit"))
    assert c["classes_sans_annotation"] == ["plante", "fruit"]
    assert c["images_sans_boite"]["image"].tolist() == ["images/train/c.jpg"]
    assert c["n_boites"] == 5 and c["images"].loc["All", "All"] == 3
    bad = st.nboxes_consistency(manifest, boxes)
    assert bad["image"].tolist() == ["images/train/b.jpg"] and bad.loc[0, "n_lignes"] == 1


def test_box_geometry_coco(yolo):
    root, manifest = yolo
    g = st.box_geometry(st.read_yolo_labels(root, manifest), img_size=640)
    a = g[g["image"] == "images/train/a.jpg"]
    # 640x320 at 640: scale 1, box 0.4 -> 256 x 128 px: large; 0.1 -> 64 x 32: medium
    assert a.iloc[0]["w_px"] == pytest.approx(256) and a.iloc[0]["h_px"] == pytest.approx(128)
    # last box: 128 x 64 = 8192 px² < 96²: medium
    assert a["coco"].tolist() == ["large", "large", "medium", "medium"]
    b = g[g["image"] == "images/train/b.jpg"].iloc[0]
    # 256x256 at 640: scale 2.5, w = 0.001 * 256 * 2.5 = 0.64 px
    assert b["w_px"] == pytest.approx(0.64) and b["coco"] == "small"
    share = st.coco_share(g)
    assert share.loc["plantdoc"].sum() == pytest.approx(1.0)
    hm = st.center_heatmap(g, bins=2)
    assert hm.sum() == pytest.approx(1.0) and hm.shape == (2, 2)


def test_box_quality(yolo):
    root, manifest = yolo
    q = st.box_quality(st.read_yolo_labels(root, manifest), img_size=640)
    assert len(q["doublons"]) == 1 and q["doublons"].iloc[0]["iou"] > 0.9
    assert len(q["imbriquees"]) == 2  # the small box inside each of the duplicates
    assert len(q["degenerees"]) == 1 and len(q["debordantes"]) == 1


def test_yolo_group_leaks(yolo):
    _, manifest = yolo
    r = st.yolo_group_leaks(manifest)
    assert r["n_fuites"] == 1 and r["non_controlees"] == 1
    assert r["non_controlees_par_source"] == {"plantvillage": 1}
    index = pd.DataFrame({"path": ["plantvillage/color/x/b.jpg"], "groupe": [0]})
    r = st.yolo_group_leaks(manifest, index)
    # index group 0 is not YOLO group 0: still one leak, nothing left unchecked
    assert r["n_fuites"] == 1 and r["non_controlees"] == 0


def test_embed_2d_fallback():
    feats = np.random.default_rng(0).normal(size=(30, 8))
    xy, method = st.embed_2d(feats, method="tsne")
    assert xy.shape == (30, 2) and method == "tsne"


def test_write_report(tmp_path):
    out = write_report(
        tmp_path / "classifieur",
        {"n_images": np.int64(3), "gini": np.float64(0.5), "nan": float("nan"), "l": [1, 2]},
        {"Effectifs": pd.DataFrame({"a": [1]}), "Note": "texte"},
    )
    data = json.loads((out / "summary.json").read_text())
    assert data["n_images"] == 3 and data["nan"] is None and "date" in data
    md = (out / "summary.md").read_text()
    assert "## Effectifs" in md and "| n_images | 3 |" in md
