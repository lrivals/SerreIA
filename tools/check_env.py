"""Check that the development machine is ready (docs/08-environnement.md).

    python -m tools.check_env      # or: make check-env

One line per check: OK, WARN (works, but not as documented) or FAIL (blocking). The exit
code is 1 if any check fails. No dependency outside the standard library: torch and the
extras are only probed, never required.
"""

import importlib.util
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MLFLOW_DB = ROOT / "mlruns" / "mlflow.db"
DRIVE_REMOTE = "gdrive:"
DRIVER_HINT = "sudo ubuntu-drivers install, enroll the MOK key, reboot (docs/08 §1)"
# Extra -> modules imported to tell whether it is installed (pyproject.toml).
EXTRAS = {
    "vision": ("torch", "torchvision", "timm", "albumentations", "cv2", "mlflow"),
    "detection": ("ultralytics", "scipy"),
    "controle": ("numpy", "pandas", "yaml", "onnxruntime"),
    "backend": ("sqlalchemy", "psycopg", "fastapi"),
    "notebook": ("ipykernel", "nbclient", "nbformat"),
}
BASE = ("pydantic", "paho")
STATUS = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # ok | warn | fail
    detail: str = ""


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def run(*cmd: str) -> str | None:
    """Stdout of a command, None if it is missing or fails."""
    if which(cmd[0]) is None:
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def torch_info() -> dict | None:
    """Version and CUDA state of torch, None if not installed."""
    if not has_module("torch"):
        return None
    import torch

    info = {"version": torch.__version__, "cuda": torch.cuda.is_available()}
    if info["cuda"]:
        props = torch.cuda.get_device_properties(0)
        info["gpu"] = f"{props.name}, {props.total_memory / 2**30:.1f} GiB"
    return info


def check_python() -> Check:
    v = sys.version_info
    ok = v >= (3, 12)
    return Check("python", "ok" if ok else "fail", f"{v.major}.{v.minor}.{v.micro}")


def check_base() -> Check:
    missing = [m for m in BASE if not has_module(m)]
    if missing:
        return Check("base dependencies", "fail", f"missing {', '.join(missing)}: uv sync")
    return Check("base dependencies", "ok")


def check_uv() -> Check:
    if which("uv") is None:
        return Check("uv", "warn", "not installed (pip fallback, docs/08 §2)")
    return Check("uv", "ok", run("uv", "--version") or "")


def check_driver() -> Check:
    gpus = run("nvidia-smi", "-L")
    if not gpus:
        sb = run("mokutil", "--sb-state") or ""
        hint = DRIVER_HINT if "enabled" in sb else DRIVER_HINT.replace(", enroll the MOK key", "")
        return Check("nvidia driver", "fail", f"nvidia-smi does not answer: {hint}")
    return Check("nvidia driver", "ok", gpus.splitlines()[0])


def check_torch() -> Check:
    info = torch_info()
    if info is None:
        return Check("torch", "warn", "not installed: uv sync --extra vision")
    if info["cuda"]:
        return Check("torch", "ok", f"{info['version']}, {info['gpu']}")
    if info["version"].endswith("+cpu"):
        return Check("torch", "warn", f"{info['version']} (CPU build): make cuda-torch")
    return Check("torch", "warn", f"{info['version']}, CUDA unavailable (driver?)")


def check_extras() -> list[Check]:
    checks = []
    for extra, modules in EXTRAS.items():
        missing = [m for m in modules if not has_module(m)]
        if missing:
            detail = f"missing {', '.join(missing)}: uv sync --extra {extra}"
            checks.append(Check(f"extra {extra}", "warn", detail))
        else:
            checks.append(Check(f"extra {extra}", "ok"))
    return checks


def check_tools() -> list[Check]:
    checks = []
    remotes = run("rclone", "listremotes")
    if remotes is None:
        checks.append(Check("rclone", "warn", "not installed: sudo apt install rclone"))
    elif DRIVE_REMOTE not in remotes.split():
        checks.append(Check("rclone", "warn", f"no {DRIVE_REMOTE} remote (docs/data-drive.md)"))
    else:
        checks.append(Check("rclone", "ok", f"remote {DRIVE_REMOTE}"))
    for cmd, use in (("docker", "make stack-up"), ("mosquitto", "local MQTT broker")):
        status = "ok" if which(cmd) else "warn"
        checks.append(Check(cmd, status, "" if status == "ok" else f"not installed ({use})"))
    return checks


def check_mlflow() -> Check:
    if MLFLOW_DB.exists():
        return Check("mlflow store", "ok", str(MLFLOW_DB.relative_to(ROOT)))
    return Check("mlflow store", "ok", "mlruns/mlflow.db created by the first run")


def collect() -> list[Check]:
    return [
        check_python(),
        check_base(),
        check_uv(),
        check_driver(),
        check_torch(),
        *check_extras(),
        *check_tools(),
        check_mlflow(),
    ]


def report(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    lines = [f"[{STATUS[c.status]}] {c.name:<{width}}  {c.detail}".rstrip() for c in checks]
    return "\n".join(lines)


def main() -> int:
    checks = collect()
    print(report(checks))
    return 1 if any(c.status == "fail" for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
