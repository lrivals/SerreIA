"""Active learning (docs/05 §5): uncertain greenhouse captures -> Label Studio queue.

    python -m vision.labeling.active_learning --archive edge/archive [--days 7] [--k 50]
        [--url-prefix "/data/local-files/?d=archive/"]

Reads the capture archive (edge/archive.py, synced from the Pi). A capture is a candidate
when one of its detections has a head confidence < 0.6, a high normalized sante entropy,
or when its anomaly score is high. At most k (50) per run, diversified: round-robin over
(camera, time-of-day slot) groups, the most uncertain first in each group. Captures already
queued are listed in `<out dir>/deja_selectionnees.txt` and never proposed twice.
Output: Label Studio tasks with the detections as pre-annotations (label_studio.write_tasks).
"""

import argparse
import json
import logging
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2

from vision.labeling.label_studio import Prediction, to_tasks

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "runs" / "active_learning"
LEDGER = "deja_selectionnees.txt"
HEADS = ("espece", "sante", "classe")


@dataclass(frozen=True)
class Criteria:
    conf_max: float = 0.6  # a head below: uncertain
    entropie_min: float = 0.8  # normalized sante entropy (1 = 50/50)
    anomalie_min: float = 0.5  # PatchCore score mapped to [0, 1] (0.5 = calibrated threshold)


DEFAULT = Criteria()


@dataclass
class Candidate:
    json_path: Path
    image_id: str
    camera: str
    ts: datetime
    priorite: float
    raisons: list[str]
    record: dict = field(repr=False)


def uncertainty(record: dict, c: Criteria = DEFAULT) -> tuple[float, list[str]]:
    """(priority in [0, 1], reasons); no reason: not a candidate."""
    res, rows = record["resultat"], record.get("extras", {}).get("classifieur", [])
    min_conf = min((r[f"{h}_conf"] for r in rows for h in HEADS), default=1.0)
    entropie = max((r.get("entropie", 0.0) for r in rows), default=0.0)
    anomalie = res.get("score_anomalie", 0.0)
    raisons = []
    if min_conf < c.conf_max:
        raisons.append(f"confiance {min_conf:.2f}")
    if entropie >= c.entropie_min:
        raisons.append(f"entropie {entropie:.2f}")
    if anomalie >= c.anomalie_min:
        raisons.append(f"anomalie {anomalie:.2f}")
    return max(1 - min_conf, entropie, anomalie), raisons


def load_candidates(
    archive: Path, since: datetime | None = None, c: Criteria = DEFAULT, skip: Iterable[str] = ()
) -> list[Candidate]:
    skip = set(skip)
    out = []
    for path in sorted(archive.rglob("*.json")):
        try:
            record = json.loads(path.read_text())
            res = record["resultat"]
            ts = datetime.fromisoformat(res["ts"])
        except (ValueError, KeyError):
            continue
        if res["image_id"] in skip or (since is not None and ts < since):
            continue
        prio, raisons = uncertainty(record, c)
        if raisons:
            out.append(Candidate(path, res["image_id"], res["camera"], ts, prio, raisons, record))
    return out


def select(cands: Sequence[Candidate], k: int = 50, slot_h: int = 3) -> list[Candidate]:
    """At most k, round-robin over (camera, time slot) groups, most uncertain first."""
    groups: dict[tuple, list[Candidate]] = defaultdict(list)
    for cand in cands:
        groups[(cand.camera, cand.ts.hour // slot_h)].append(cand)
    queues = sorted(
        (sorted(g, key=lambda x: -x.priorite) for g in groups.values()),
        key=lambda g: -g[0].priorite,
    )
    out: list[Candidate] = []
    depth = 0
    while len(out) < k and any(depth < len(q) for q in queues):
        out += [q[depth] for q in queues if depth < len(q)][: k - len(out)]
        depth += 1
    return out


def to_prediction(cand: Candidate, archive: Path, url_prefix: str | None) -> Prediction:
    jpg = cand.json_path.with_suffix(".jpg")
    img = cv2.imread(str(jpg))
    h, w = img.shape[:2] if img is not None else cand.record["extras"]["taille_image"]
    url = f"{url_prefix}{jpg.relative_to(archive).as_posix()}" if url_prefix else str(jpg)
    pred = Prediction(url, w, h)
    for d in cand.record["resultat"]["detections"]:
        if d["bbox"] is None:
            continue
        x, y, bw, bh = d["bbox"]
        pred.boxes.append((x * w, y * h, (x + bw) * w, (y + bh) * h))
        pred.labels.append("feuille")
        pred.scores.append(min(d["espece_conf"], d["sante_conf"], d["classe_conf"]))
    return pred


def build_tasks(selected: Sequence[Candidate], archive: Path, url_prefix: str | None) -> list[dict]:
    tasks = to_tasks([to_prediction(c, archive, url_prefix) for c in selected],
                     model_version="apprentissage-actif")  # fmt: skip
    for task, cand in zip(tasks, selected, strict=True):
        res = cand.record["resultat"]
        task["data"].update({
            "image_id": cand.image_id,
            "camera": cand.camera,
            "ts": res["ts"],
            "modele": res["modele"],
            "raisons": ", ".join(cand.raisons),
            "classes_predites": ", ".join(sorted({d["classe"] for d in res["detections"]})),
        })  # fmt: skip
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, default=ROOT / "edge" / "archive")
    parser.add_argument("--days", type=float, default=7, help="fenêtre (0 : toute l'archive)")
    parser.add_argument("--k", type=int, default=50)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument(
        "--url-prefix",
        default=None,
        help="Label Studio local files : /data/local-files/?d=archive/",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    ledger = args.out_dir / LEDGER
    skip = ledger.read_text().split() if ledger.exists() else []
    since = datetime.now(UTC) - timedelta(days=args.days) if args.days else None
    cands = load_candidates(args.archive, since, skip=skip)
    selected = select(cands, args.k)
    log.info("%d candidates, %d sélectionnées", len(cands), len(selected))
    if not selected:
        return
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"taches_{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    out.write_text(json.dumps(build_tasks(selected, args.archive, args.url_prefix), indent=1,
                              ensure_ascii=False))  # fmt: skip
    with ledger.open("a") as f:
        f.writelines(f"{c.image_id}\n" for c in selected)
    print(f"{len(selected)} tâches -> {out}")


if __name__ == "__main__":
    main()
