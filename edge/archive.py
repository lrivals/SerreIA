"""Local archive of the captures and asynchronous upload (docs/05 §3 step 6).

    <dir>/<YYYY-MM-DD>/<image_id>.jpg       capture (after white balance)
    <dir>/<YYYY-MM-DD>/<image_id>.json      {"resultat": VisionResult, "extras": {...}}
    <dir>/<YYYY-MM-DD>/<image_id>.uploaded  marker once accepted by the server

Circular buffer: days older than `retention_jours` are deleted, uploaded or not. The JSON
keeps the classifier probabilities and entropies used by active learning (docs/05 §5).
"""

import base64
import json
import logging
import shutil
import threading
import urllib.request
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from common.mqtt import VisionResult

from .vision.preprocess import resize_max

log = logging.getLogger(__name__)

DAY_FMT = "%Y-%m-%d"


class Archive:
    def __init__(
        self, root: Path, retention_days: int = 7, max_side: int = 1920, quality: int = 90
    ):
        self.root, self.retention = root, retention_days
        self.max_side, self.quality = max_side, quality

    def save(self, img: np.ndarray, result: VisionResult, extras: dict) -> Path:
        day = self.root / f"{result.ts:{DAY_FMT}}"
        day.mkdir(parents=True, exist_ok=True)
        small, _ = resize_max(img, self.max_side)
        jpg = day / f"{result.image_id}.jpg"
        cv2.imwrite(str(jpg), cv2.cvtColor(small, cv2.COLOR_RGB2BGR),
                    [cv2.IMWRITE_JPEG_QUALITY, self.quality])  # fmt: skip
        record = {"resultat": result.model_dump(mode="json"), "extras": extras}
        path = day / f"{result.image_id}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, allow_nan=False))
        tmp.replace(path)  # never a half-written JSON for the uploader
        return path

    def days(self) -> list[tuple[date, Path]]:
        out = []
        for d in self.root.glob("*") if self.root.exists() else []:
            try:
                out.append((datetime.strptime(d.name, DAY_FMT).date(), d))
            except ValueError:
                continue
        return sorted(out)

    def purge(self, now: datetime) -> int:
        """Delete the days older than the retention; returns the number of days deleted."""
        limit = now.date() - timedelta(days=self.retention)
        old = [d for day, d in self.days() if day < limit]
        for d in old:
            shutil.rmtree(d, ignore_errors=True)
        return len(old)

    def records(self) -> Iterator[Path]:
        """JSON records, oldest first."""
        for _, d in self.days():
            yield from sorted(d.glob("*.json"))

    def pending(self) -> Iterator[Path]:
        return (p for p in self.records() if not p.with_suffix(".uploaded").exists())


def http_send(url: str, timeout: float) -> Callable[[dict], None]:
    """POST of the record as JSON, JPEG in base64 (`jpeg_b64`); any non-2xx raises."""

    def send(payload: dict) -> None:
        req = urllib.request.Request(
            url, json.dumps(payload).encode(), {"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if not 200 <= resp.status < 300:
                raise OSError(f"HTTP {resp.status}")

    return send


class Uploader:
    """Uploads the pending records; stops a round at the first failure and retries later."""

    def __init__(self, archive: Archive, send: Callable[[dict], None], period_s: float = 60.0):
        self.archive, self.send, self.period = archive, send, period_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def upload_pending(self, limit: int = 100) -> int:
        n = 0
        for path in self.archive.pending():
            if n >= limit:
                break
            payload = json.loads(path.read_text())
            jpg = path.with_suffix(".jpg")
            if jpg.exists():
                payload["jpeg_b64"] = base64.b64encode(jpg.read_bytes()).decode()
            try:
                self.send(payload)
            except Exception as e:
                log.warning("upload de %s échoué (%s) : nouvel essai plus tard", path.name, e)
                break
            path.with_suffix(".uploaded").touch()
            n += 1
        return n

    def _run(self) -> None:
        while not self._stop.wait(self.period):
            self.upload_pending()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="uploader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
