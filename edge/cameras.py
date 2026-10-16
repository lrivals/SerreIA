"""Camera sources (docs/05 §1, §3): every source returns an RGB uint8 image.

folder:<dir>   images of a folder, in turn (tests on the PC, replay of an archive)
usb:<index>    USB webcam through OpenCV
csi:<index>    Camera Module 3 through picamera2 (Pi, apt python3-picamera2)
"""

from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from .config import ROOT

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


class Camera(Protocol):
    def capture(self) -> np.ndarray: ...

    def close(self) -> None: ...


class FolderCamera:
    """Cycles through the images of a folder (recursive, sorted)."""

    def __init__(self, folder: Path):
        self.paths = sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_EXTS)
        if not self.paths:
            raise FileNotFoundError(f"aucune image dans {folder}")
        self.i = 0
        self.last: Path | None = None

    def capture(self) -> np.ndarray:
        self.last = self.paths[self.i % len(self.paths)]
        self.i += 1
        img = cv2.imread(str(self.last), cv2.IMREAD_COLOR)
        if img is None:
            raise OSError(f"image illisible : {self.last}")
        return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    def close(self) -> None:
        pass


class OpenCvCamera:
    """USB webcam; a few frames are dropped so that auto exposure settles."""

    def __init__(self, index: int, resolution: tuple[int, int] | None = None, warmup: int = 5):
        self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise OSError(f"webcam {index} introuvable")
        if resolution:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])
        self.warmup = warmup

    def capture(self) -> np.ndarray:
        for _ in range(self.warmup):
            self.cap.grab()
        ok, frame = self.cap.read()
        if not ok:
            raise OSError("lecture webcam impossible")
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def close(self) -> None:
        self.cap.release()


class PiCamera:
    """Camera Module 3 (CSI). Not testable without the board."""

    def __init__(self, index: int, resolution: tuple[int, int] | None = None):
        from picamera2 import Picamera2

        self.cam = Picamera2(index)
        main = {"format": "RGB888", **({"size": tuple(resolution)} if resolution else {})}
        self.cam.configure(self.cam.create_still_configuration(main=main))
        self.cam.start()

    def capture(self) -> np.ndarray:
        # picamera2 "RGB888" is BGR in memory (libcamera naming).
        return cv2.cvtColor(self.cam.capture_array("main"), cv2.COLOR_BGR2RGB)

    def close(self) -> None:
        self.cam.stop()
        self.cam.close()


def open_camera(source: str, resolution: tuple[int, int] | None = None) -> Camera:
    kind, _, arg = source.partition(":")
    if kind == "folder":
        folder = Path(arg)
        return FolderCamera(folder if folder.is_absolute() else ROOT / folder)
    if kind == "usb":
        return OpenCvCamera(int(arg or 0), resolution)
    if kind == "csi":
        return PiCamera(int(arg or 0), resolution)
    raise ValueError(f"source caméra inconnue {source!r} (folder:…, usb:N, csi:N)")
