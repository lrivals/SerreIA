"""PatchCore (docs/04-detection-yolo.md §4) on synthetic leaves: no data/, no download."""

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("timm")

from vision.anomaly.patchcore import PatchCore, PatchCoreConfig, greedy_coreset  # noqa: E402

SIZE = 64
CFG = PatchCoreConfig(backbone="resnet18", layers=(2, 3), size=SIZE, pretrained=False)


def _healthy(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = np.empty((SIZE, SIZE, 3), np.uint8)
    img[:] = (40, 140, 50)
    return np.clip(img + rng.normal(0, 6, img.shape), 0, 255).astype(np.uint8)


def _spotted(seed: int) -> np.ndarray:
    img = _healthy(seed)
    img[36:52, 36:52] = (150, 110, 40)  # brown lesion, bottom right
    return img


@pytest.fixture(scope="module")
def model():
    torch.manual_seed(0)
    m = PatchCore(CFG).fit([_healthy(i) for i in range(6)])
    m.calibrate([_healthy(i) for i in range(10, 14)])
    return m


def test_greedy_coreset_covers_clusters():
    x = torch.cat([torch.randn(50, 8) * 0.01 + c for c in (0.0, 10.0, -10.0)])
    idx = greedy_coreset(x, 3, proj_dim=4)
    assert len(set(idx.tolist())) == 3
    assert sorted(round(float(v)) for v in x[idx, 0]) == [-10, 0, 10]


def test_anomaly_scores_and_map(model):
    scores, maps = model.score([_healthy(100), _spotted(101)])
    assert scores[1] > 2 * scores[0] and scores[1] > model.threshold
    assert model.is_anomalous(scores)[1]
    assert maps.shape == (2, SIZE, SIZE)
    m = maps[1]
    assert m[36:52, 36:52].mean() > 2 * m[:24, :24].mean()  # the map points at the lesion


def test_save_load(model, tmp_path):
    path = tmp_path / "tomate.pt"
    model.save(path)
    torch.manual_seed(0)  # random backbone (pretrained=False): same init as the fixture
    loaded = PatchCore.load(path)
    assert loaded.threshold == model.threshold and loaded.cfg.layers == CFG.layers
    a, _ = model.score([_spotted(5)])
    b, _ = loaded.score([_spotted(5)])
    assert b == pytest.approx(a, rel=1e-4)
