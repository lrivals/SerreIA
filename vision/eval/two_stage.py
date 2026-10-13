"""Two-stage pipeline: YOLO leaves -> crops -> phase 1 classifier (docs/04 §1, §3).

python -m vision.eval.two_stage --detector runs/<yolo_run>/best.pt --classifier <clf_run>
    [--split test] [--limit 50] [--device cpu]

End-to-end evaluation on annotated scenes, today PlantDoc TEST (VOC labels -> sante through
the taxonomy), later greenhouse images: leaf recall (IoU >= 0.5), sante of the matched
leaves, and per image "abnormal plant" recall. Writes reports/<clf_run>/two_stage_<split>.json
and an example sheet.
"""

import argparse
import json
import logging
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import torch

from vision.datasets.augment import build_transform
from vision.datasets.batch_augment import BatchAugment
from vision.datasets.build_index import DATA_DIR
from vision.datasets.dataset import HEADS, read_rgb
from vision.datasets.prepare import voc_boxes
from vision.datasets.taxonomy import load_taxonomy
from vision.eval.cross_domain_eval import REPORTS_DIR
from vision.labeling.yolo_format import box_iou
from vision.train.train_classifier import RUNS_DIR, load_checkpoint, pick_device

log = logging.getLogger(__name__)

IOU_MATCH = 0.5
Detector = Callable[[np.ndarray], tuple[np.ndarray, np.ndarray]]  # RGB -> (boxes, conf)
Classifier = Callable[[list[np.ndarray]], list[dict]]  # crops -> per-crop head outputs


@dataclass
class Leaf:
    box: tuple[float, float, float, float]
    conf: float
    espece: str
    sante: str
    p_anormal: float
    classe: str
    classe_conf: float


@dataclass
class SceneResult:
    leaves: list[Leaf] = field(default_factory=list)
    plante_anormale: bool = False
    p_anormal_max: float = 0.0


class YoloDetector:
    """Leaves (class `feuille`) of an Ultralytics model, boxes in pixels."""

    def __init__(self, weights: Path, conf: float = 0.25, imgsz: int = 640, device=None):
        from ultralytics import YOLO

        self.model, self.conf, self.imgsz, self.device = YOLO(str(weights)), conf, imgsz, device

    def __call__(self, img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        res = self.model.predict(
            img[..., ::-1], conf=self.conf, imgsz=self.imgsz, device=self.device, verbose=False
        )[0]
        keep = (res.boxes.cls == 0).cpu().numpy()  # feuille
        return res.boxes.xyxy.cpu().numpy()[keep], res.boxes.conf.cpu().numpy()[keep]


class CropClassifier:
    """Phase 1 multi-head classifier applied to crops (same eval transform as phase 1)."""

    def __init__(self, ckpt: Path, device: torch.device, batch: int = 64):
        self.model, self.labels, cfg = load_checkpoint(ckpt, device)
        self.tf = build_transform("eval", cfg["data"]["size"])
        self.norm = BatchAugment("eval").to(device)
        self.device, self.batch = device, batch
        self.i_anormal = self.labels.sante.index("anormal")

    @torch.no_grad()
    def __call__(self, crops: list[np.ndarray]) -> list[dict]:
        out = []
        for i in range(0, len(crops), self.batch):
            x = torch.stack([self.tf(image=c)["image"] for c in crops[i : i + self.batch]])
            logits = self.model(self.norm(x.to(self.device)))
            probs = {
                h: torch.softmax(z.float(), 1).cpu().numpy()
                for h, z in zip(HEADS, logits, strict=True)
            }
            for j in range(len(x)):
                row = {h: self.labels.vocab(h)[int(probs[h][j].argmax())] for h in HEADS}
                row["p_anormal"] = float(probs["sante"][j, self.i_anormal])
                row["classe_conf"] = float(probs["classe"][j].max())
                out.append(row)
        return out


def crop(img: np.ndarray, box, margin: float) -> np.ndarray:
    """Box enlarged by margin (fraction of its size) on each side, clipped to the image."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    mx, my = margin * (x1 - x0), margin * (y1 - y0)
    x0, y0 = int(max(0, x0 - mx)), int(max(0, y0 - my))
    x1, y1 = int(min(w, x1 + mx)), int(min(h, y1 + my))
    return img[y0 : max(y1, y0 + 1), x0 : max(x1, x0 + 1)]


class TwoStagePipeline:
    def __init__(
        self, detector: Detector, classifier: Classifier, margin: float = 0.1,
        seuil_anormal: float = 0.5,
    ):  # fmt: skip
        self.detector, self.classifier = detector, classifier
        self.margin, self.seuil = margin, seuil_anormal

    def __call__(self, img: np.ndarray) -> SceneResult:
        boxes, conf = self.detector(img)
        if len(boxes) == 0:
            return SceneResult()
        heads = self.classifier([crop(img, b, self.margin) for b in boxes])
        leaves = [
            Leaf(tuple(map(float, b)), float(c), r["espece"], r["sante"], r["p_anormal"],
                 r["classe"], r["classe_conf"])
            for b, c, r in zip(boxes, conf, heads, strict=True)
        ]  # fmt: skip
        p_max = max(leaf.p_anormal for leaf in leaves)
        return SceneResult(leaves, p_max >= self.seuil, p_max)


@dataclass
class Scene:
    """Annotated image: pixel boxes and the sante of each box."""

    path: Path
    boxes: np.ndarray
    sante: list[str]


def plantdoc_scenes(data_dir: Path, split: str = "test") -> list[Scene]:
    taxo = load_taxonomy()
    scenes = []
    for xml_path in sorted((data_dir / "plantdoc" / split).glob("*.xml")):
        try:
            found = voc_boxes(xml_path)
        except (ET.ParseError, OSError, TypeError, ValueError):
            continue
        if found is None or not found[2]:
            continue
        img_path, _, boxes = found
        known = [(lbl, b) for lbl, b in boxes if taxo.has("plantdoc", lbl)]
        if known:
            scenes.append(Scene(
                img_path,
                np.array([b for _, b in known], float),
                [taxo.lookup("plantdoc", lbl).sante for lbl, _ in known],
            ))  # fmt: skip
    return scenes


def match(gt: np.ndarray, pred: np.ndarray, iou: float = IOU_MATCH) -> list[tuple[int, int]]:
    """Greedy one-to-one (gt, pred) pairs by decreasing IoU, IoU >= iou."""
    if len(gt) == 0 or len(pred) == 0:
        return []
    m = box_iou(gt, pred)
    pairs, used_g, used_p = [], set(), set()
    for flat in np.argsort(-m, axis=None):
        g, p = np.unravel_index(flat, m.shape)
        if m[g, p] < iou:
            break
        if g not in used_g and p not in used_p:
            pairs.append((int(g), int(p)))
            used_g.add(g)
            used_p.add(p)
    return pairs


def ratio(a: float, b: float) -> float:
    return float(a / b) if b else float("nan")


def evaluate(pipeline: TwoStagePipeline, scenes: Sequence[Scene]) -> tuple[dict, list]:
    """End-to-end metrics and per-scene results."""
    n_gt = n_found = n_pred = 0
    sante_ok = anormal_gt = anormal_hit = 0
    img_anormal = img_anormal_hit = img_sain = img_sain_fp = 0
    results = []
    for sc in scenes:
        res = pipeline(read_rgb(sc.path))
        results.append(res)
        pred = np.array([leaf.box for leaf in res.leaves], float).reshape(-1, 4)
        pairs = match(sc.boxes, pred)
        n_gt, n_found, n_pred = n_gt + len(sc.boxes), n_found + len(pairs), n_pred + len(pred)
        for g, p in pairs:
            sante_ok += res.leaves[p].sante == sc.sante[g]
            if sc.sante[g] == "anormal":
                anormal_gt += 1
                anormal_hit += res.leaves[p].sante == "anormal"
        if "anormal" in sc.sante:
            img_anormal += 1
            img_anormal_hit += res.plante_anormale
        else:
            img_sain += 1
            img_sain_fp += res.plante_anormale
    metrics = {
        "n_images": len(scenes),
        "detection/recall_feuille": ratio(n_found, n_gt),
        "detection/precision_feuille": ratio(n_found, n_pred),
        "feuilles/sante_accuracy": ratio(sante_ok, n_found),
        "feuilles/recall_anormal": ratio(anormal_hit, anormal_gt),
        "image/recall_plante_anormale": ratio(img_anormal_hit, img_anormal),
        "image/faux_positifs_sain": ratio(img_sain_fp, img_sain),
        "n_images_anormales": img_anormal,
        "n_images_saines": img_sain,
    }
    return metrics, results


def plot_examples(scenes, results, path: Path, n: int = 12, seed: int = 0) -> None:
    from matplotlib.figure import Figure

    from vision.labeling.build_yolo_dataset import draw_boxes

    idx = np.random.default_rng(seed).permutation(len(scenes))[:n]
    cols = 4
    rows = max(1, -(-len(idx) // cols))
    fig = Figure(figsize=(cols * 3.2, rows * 3.2))
    axes = np.atleast_1d(fig.subplots(rows, cols)).ravel()
    for ax in axes:
        ax.axis("off")
    for ax, i in zip(axes, idx, strict=False):
        img = draw_boxes(read_rgb(scenes[i].path), scenes[i].boxes, color=(255, 255, 255))
        for leaf in results[i].leaves:
            color = (255, 0, 0) if leaf.sante == "anormal" else (0, 200, 0)
            img = draw_boxes(img, [leaf.box], color, [f"{leaf.p_anormal:.2f}"])
        ax.imshow(img)
        title = "anormale" if results[i].plante_anormale else "saine"
        ax.set_title(f"{scenes[i].path.name[:24]}\n→ {title}", fontsize=6)
    fig.suptitle("blanc : vérité ; rouge / vert : feuille prédite anormale / saine")
    fig.tight_layout()
    fig.savefig(path, dpi=130)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--detector", type=Path, required=True, help="best.pt YOLO")
    parser.add_argument("--classifier", required=True, help="run MLflow ou chemin de best.pt")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--split", default="test", help="PlantDoc : train ou test")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--seuil-anormal", type=float, default=0.5)
    parser.add_argument("--device", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    ckpt = Path(args.classifier)
    if not ckpt.exists():
        ckpt = RUNS_DIR / args.classifier / "best.pt"
    device = pick_device(args.device)
    pipeline = TwoStagePipeline(
        YoloDetector(args.detector, args.conf, device=str(device)),
        CropClassifier(ckpt, device),
        seuil_anormal=args.seuil_anormal,
    )
    scenes = plantdoc_scenes(args.data_dir, args.split)
    if args.limit:
        scenes = scenes[: args.limit]
    metrics, results = evaluate(pipeline, scenes)
    out_dir = REPORTS_DIR / ckpt.parent.name
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "detector": str(args.detector),
        "classifier": str(ckpt),
        "metrics": metrics,
        "scenes": [
            {"path": str(s.path), **asdict(r)} for s, r in zip(scenes, results, strict=True)
        ],
    }
    out = out_dir / f"two_stage_{args.split}.json"
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    plot_examples(scenes, results, out_dir / f"two_stage_{args.split}.png")
    for k, v in metrics.items():
        print(f"{k:32s} {v:.4f}" if isinstance(v, float) else f"{k:32s} {v}")
    log.info("-> %s", out)


if __name__ == "__main__":
    main()
