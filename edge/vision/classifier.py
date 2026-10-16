"""Phase 1 multi-head classifier on the edge (docs/03, docs/05 §3), on any Backend."""

from collections.abc import Sequence

import cv2
import numpy as np

from .backends import Backend, order_outputs

HEADS = ("espece", "sante", "classe")  # order of the exported outputs (vision.datasets.dataset)


def softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(1, keepdims=True)


def entropy(p: np.ndarray) -> np.ndarray:
    """Entropy of each row, normalized to [0, 1] by log(k)."""
    k = p.shape[1]
    h = -(p * np.log(np.clip(p, 1e-12, 1))).sum(1)
    return h / np.log(k) if k > 1 else np.zeros(len(p))


class EdgeClassifier:
    """Crops -> per-crop dict: espece/sante/classe, their confidences, p_anormal, and the
    normalized entropy of sante (uncertainty used by active learning, docs/05 §5).

    labels: LabelSpace.to_dict() of the checkpoint (stored in the bundle manifest).
    """

    def __init__(self, backend: Backend, labels: dict, batch: int = 16):
        self.backend, self.batch = backend, batch
        self.vocab = {
            "espece": labels["especes"],
            "sante": labels["sante"],
            "classe": labels["classes"],
        }
        self.sizes = {h: len(self.vocab[h]) for h in HEADS}
        self.i_anormal = list(self.vocab["sante"]).index("anormal")
        h, w = backend.input_size
        self.size = (w, h)

    def __call__(self, crops: Sequence[np.ndarray]) -> list[dict]:
        out = []
        for i in range(0, len(crops), self.batch):
            # Same resize as the eval transform of training (albumentations Resize, bilinear).
            x = np.stack([cv2.resize(c, self.size, interpolation=cv2.INTER_LINEAR)
                          for c in crops[i : i + self.batch]])  # fmt: skip
            raw = self.backend(x)
            logits = order_outputs(self.backend.output_names, raw, self.sizes)
            probs = {
                h: softmax(np.asarray(z, np.float32)) for h, z in zip(HEADS, logits, strict=True)
            }
            h_sante = entropy(probs["sante"])
            for j in range(len(x)):
                row: dict = {}
                for h in HEADS:
                    k = int(probs[h][j].argmax())
                    row[h], row[f"{h}_conf"] = self.vocab[h][k], float(probs[h][j, k])
                row["p_anormal"] = float(probs["sante"][j, self.i_anormal])
                row["entropie"] = float(h_sante[j])
                out.append(row)
        return out
