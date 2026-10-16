"""Configuration of the Pi services, `edge/config.yaml` (docs/05 §3)."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]

Roi = tuple[int, int, int, int]  # x0, y0, x1, y1 in pixels of the capture


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlantCfg(_Cfg):
    id: str
    roi: Roi | None = None
    px_per_cm: float | None = None  # calibration chart
    base_row: int | None = None  # side camera: image row of the pot rim


class CameraCfg(_Cfg):
    id: str
    zone: str
    source: str  # folder:<dir> | usb:<index> | csi:<index>
    resolution: tuple[int, int] | None = None  # (width, height)
    wb_roi: Roi | None = None  # fixed grey card in the field of view
    plantes: list[PlantCfg] = Field(default_factory=list)


class MqttCfg(_Cfg):
    host: str = "localhost"
    port: int = 1883
    keepalive_s: int = 60


class LedCfg(_Cfg):
    # The contract has no LED colour: "couper" switches the LEDs off during the capture
    # then restores their retained state (etat/led); "aucun" leaves them alone.
    mode: Literal["aucun", "couper"] = "aucun"
    attente_s: float = 2.0


class ArchiveCfg(_Cfg):
    dir: Path = Path("edge/archive")
    retention_jours: int = 7
    cote_max_px: int = 1920  # archived JPEG
    qualite_jpeg: int = 90


class UploadCfg(_Cfg):
    url: str | None = None  # server endpoint; None: no upload
    periode_s: float = 60.0
    timeout_s: float = 30.0


class ModelsCfg(_Cfg):
    dir: Path = Path("edge/models/current")
    backend: Literal["onnx", "hailo"] = "onnx"
    patchcore: bool = True
    device: str = "cpu"  # PatchCore (torch)


class SeuilsCfg(_Cfg):
    conf_detection: float = 0.25
    marge_crop: float = 0.1


class ServiceCfg(_Cfg):
    noeud: str = "pi-serre"
    periode_s: float = 600.0
    erreurs_avant_alerte: int = 3
    mqtt: MqttCfg = Field(default_factory=MqttCfg)
    led: LedCfg = Field(default_factory=LedCfg)
    archive: ArchiveCfg = Field(default_factory=ArchiveCfg)
    upload: UploadCfg = Field(default_factory=UploadCfg)
    modeles: ModelsCfg = Field(default_factory=ModelsCfg)
    seuils: SeuilsCfg = Field(default_factory=SeuilsCfg)
    cameras: list[CameraCfg] = Field(min_length=1)

    def resolve(self, path: Path) -> Path:
        """Relative paths are relative to the repository root."""
        return path if path.is_absolute() else ROOT / path


def load_config(path: Path) -> ServiceCfg:
    return ServiceCfg.model_validate(yaml.safe_load(Path(path).read_text()))
