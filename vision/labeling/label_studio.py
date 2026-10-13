"""Label Studio pre-annotations and export -> YOLO (docs/04 §2, steps 4 and 5).

Plain JSON, no SDK. Labeling interface expected in the Label Studio project:

    <View>
      <Image name="image" value="$image"/>
      <RectangleLabels name="label" toName="image">
        <Label value="feuille"/><Label value="plante"/><Label value="fruit"/>
      </RectangleLabels>
    </View>

Import the tasks file (`to_tasks`) with images served by Label Studio (local storage or
`label-studio-files`), correct, then export as JSON and convert it with `export_to_yolo`.
"""

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from vision.labeling.yolo_format import (
    CLASSES,
    PixelBox,
    YoloBox,
    label_path,
    write_data_yaml,
    write_labels,
)

FROM_NAME, TO_NAME = "label", "image"


@dataclass
class Prediction:
    """Boxes proposed for one image (pixels), with a confidence per box."""

    image: str  # URL or path as Label Studio will see it
    width: int
    height: int
    boxes: list[PixelBox] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)


def _result(i: int, box: PixelBox, label: str, w: int, h: int, score: float | None) -> dict:
    x0, y0, x1, y1 = box
    out = {
        "id": f"r{i}",
        "type": "rectanglelabels",
        "from_name": FROM_NAME,
        "to_name": TO_NAME,
        "original_width": w,
        "original_height": h,
        "image_rotation": 0,
        "value": {
            "x": 100 * x0 / w,
            "y": 100 * y0 / h,
            "width": 100 * (x1 - x0) / w,
            "height": 100 * (y1 - y0) / h,
            "rotation": 0,
            "rectanglelabels": [label],
        },
    }
    if score is not None:
        out["score"] = float(score)
    return out


def to_tasks(preds: Sequence[Prediction], model_version: str = "pseudo-labels") -> list[dict]:
    """Label Studio tasks with their pre-annotations (`predictions`)."""
    tasks = []
    for p in preds:
        scores = p.scores or [None] * len(p.boxes)
        results = [
            _result(i, b, lbl, p.width, p.height, s)
            for i, (b, lbl, s) in enumerate(zip(p.boxes, p.labels, scores, strict=True))
        ]
        pred = {"model_version": model_version, "result": results}
        if p.scores:
            pred["score"] = float(min(p.scores))  # least confident box: review priority
        tasks.append({"data": {TO_NAME: p.image}, "predictions": [pred]})
    return tasks


def write_tasks(preds: Sequence[Prediction], path: Path, **kw) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_tasks(preds, **kw), indent=1, ensure_ascii=False))
    return path


def local_path(url: str, root: Path) -> Path:
    """Image file of a task URL: `/data/local-files/?d=rel/path`, `/data/upload/…` or a path."""
    parsed = urlparse(url)
    if parsed.query.startswith("d="):
        return root / unquote(parsed.query[2:])
    if parsed.path.startswith("/data/upload/"):
        name = Path(parsed.path).name
        return root / name.split("-", 1)[1] if "-" in name else root / name
    return Path(unquote(parsed.path)) if parsed.scheme in ("", "file") else root / Path(url).name


def task_boxes(task: dict, classes: Sequence[str] = CLASSES) -> list[YoloBox]:
    """YOLO boxes of the last annotation of an exported task (corrections win)."""
    anns = [a for a in task.get("annotations", []) if not a.get("was_cancelled")]
    if not anns:
        return []
    out = []
    for r in anns[-1]["result"]:
        if r.get("type") != "rectanglelabels":
            continue
        v = r["value"]
        cls = classes.index(v["rectanglelabels"][0])
        w, h = v["width"] / 100, v["height"] / 100
        out.append((cls, v["x"] / 100 + w / 2, v["y"] / 100 + h / 2, w, h))
    return out


def export_to_yolo(
    export_json: Path, out: Path, images_root: Path, split: str = "train", classes=CLASSES
) -> int:
    """Label Studio JSON export -> out/images/<split>/ (symlinks) + labels + data.yaml.

    Only annotated tasks are kept; an annotated task without boxes is a background image.
    Returns the number of images written.
    """
    tasks = json.loads(Path(export_json).read_text(encoding="utf-8"))
    n = 0
    for task in tasks:
        if not any(not a.get("was_cancelled") for a in task.get("annotations", [])):
            continue
        src = local_path(task["data"][TO_NAME], images_root).resolve()
        dst = out / "images" / split / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            dst.symlink_to(os.path.relpath(src, dst.parent))
        write_labels(label_path(dst), task_boxes(task, classes))
        n += 1
    splits = sorted(d.name for d in (out / "images").iterdir() if d.is_dir())
    write_data_yaml(out, classes, splits)
    return n
