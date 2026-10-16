"""Active learning selection (docs/05 §5) on a synthetic capture archive."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from common.mqtt import VisionResult
from edge.archive import Archive
from vision.labeling.active_learning import build_tasks, load_candidates, select, uncertainty

T0 = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)


def record(conf=0.9, entropie=0.1, anomalie=0.0):
    row = {"espece_conf": 0.95, "sante_conf": conf, "classe_conf": 0.9, "entropie": entropie}
    return {"resultat": {"score_anomalie": anomalie}, "extras": {"classifieur": [row]}}


def test_uncertainty_criteria():
    assert uncertainty(record())[1] == []
    prio, why = uncertainty(record(conf=0.55))
    assert why == ["confiance 0.55"] and prio == pytest.approx(0.45)
    assert uncertainty(record(entropie=0.9))[1] == ["entropie 0.90"]
    prio, why = uncertainty(record(anomalie=0.8))
    assert why == ["anomalie 0.80"] and prio == 0.8


def make_archive(tmp_path, n_per_cam=30):
    archive = Archive(tmp_path / "archive")
    rng = np.random.default_rng(0)
    img = np.zeros((100, 200, 3), np.uint8)
    for cam in ("cam-z1-a", "cam-z1-b"):
        for i in range(n_per_cam):
            ts = T0 + timedelta(hours=i)
            conf = float(rng.uniform(0.3, 1.0))
            res = VisionResult(
                ts=ts, camera=cam, image_id=f"{cam}-{i:03d}", modele="clf-v1",
                detections=[{"bbox": (0.1, 0.2, 0.5, 0.5), "espece": "tomate",
                             "espece_conf": 0.9, "sante": "anormal", "sante_conf": conf,
                             "classe": "tomate/maladie/mildiou", "classe_conf": 0.8}],
                score_anomalie=0.0, surface_verte_px=0,
            )  # fmt: skip
            extras = {"classifieur": [{"espece_conf": 0.9, "sante_conf": conf, "classe_conf": 0.8,
                                       "entropie": 0.1}], "taille_image": [100, 200]}  # fmt: skip
            archive.save(img, res, extras)
    return archive


def test_selection_cap_diversity_and_tasks(tmp_path):
    archive = make_archive(tmp_path)
    cands = load_candidates(archive.root)
    assert cands and all(c.raisons for c in cands)
    picked = select(cands, k=10)
    assert len(picked) == 10
    groups = {(c.camera, c.ts.hour // 3) for c in picked}
    assert len(groups) == 10  # one per (camera, slot) group before going deeper
    assert len({c.image_id for c in picked}) == 10
    assert len(select(cands, k=1000)) == len(cands)

    skip = [c.image_id for c in picked]
    assert not {c.image_id for c in load_candidates(archive.root, skip=skip)} & set(skip)
    late = load_candidates(archive.root, since=T0 + timedelta(hours=20))
    assert all(c.ts >= T0 + timedelta(hours=20) for c in late)

    tasks = build_tasks(picked[:2], archive.root, "/data/local-files/?d=archive/")
    t = tasks[0]
    assert t["data"]["image"].startswith("/data/local-files/?d=archive/2026-10-")
    assert t["data"]["camera"] in ("cam-z1-a", "cam-z1-b") and t["data"]["raisons"]
    box = t["predictions"][0]["result"][0]["value"]
    assert (box["x"], box["y"], box["width"], box["height"]) == (10, 20, 50, 50)
