"""Development machine diagnostic (tools/check_env.py), without GPU nor network."""

import pytest

from tools import check_env


@pytest.fixture
def machine(monkeypatch):
    """A fully installed machine; each test breaks one part of it."""
    state = {
        "commands": {
            "uv": "uv 0.9.0",
            "nvidia-smi": "GPU 0: NVIDIA RTX 1000 Ada Generation Laptop GPU (UUID: x)",
            "mokutil": "SecureBoot enabled",
            "rclone": "gdrive:",
            "docker": "",
            "mosquitto": "",
        },
        "missing_modules": set(),
        "torch": {"version": "2.14.1+cu128", "cuda": True, "gpu": "RTX 1000 Ada, 6.0 GiB"},
    }
    commands = state["commands"]
    monkeypatch.setattr(
        check_env, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd in commands else None
    )
    monkeypatch.setattr(check_env, "run", lambda *cmd: commands.get(cmd[0]))
    monkeypatch.setattr(check_env, "has_module", lambda m: m not in state["missing_modules"])
    monkeypatch.setattr(check_env, "torch_info", lambda: state["torch"])
    return state


def _by_name(checks):
    return {c.name: c for c in checks}


def test_complete_machine_passes(machine, capsys):
    assert check_env.main() == 0
    checks = check_env.collect()
    assert all(c.status == "ok" for c in checks), check_env.report(checks)
    assert "RTX 1000 Ada" in capsys.readouterr().out


def test_missing_driver_fails_with_hint(machine):
    del machine["commands"]["nvidia-smi"]
    driver = _by_name(check_env.collect())["nvidia driver"]
    assert driver.status == "fail"
    assert "ubuntu-drivers install" in driver.detail and "MOK" in driver.detail
    assert check_env.main() == 1


def test_no_mok_hint_without_secure_boot(machine):
    del machine["commands"]["nvidia-smi"]
    machine["commands"]["mokutil"] = "SecureBoot disabled"
    assert "MOK" not in check_env.check_driver().detail


def test_cpu_torch_warns(machine):
    machine["torch"] = {"version": "2.14.1+cpu", "cuda": False}
    torch = check_env.check_torch()
    assert torch.status == "warn" and "make cuda-torch" in torch.detail


def test_missing_torch_and_extras_only_warn(machine):
    machine["torch"] = None
    machine["missing_modules"] |= {"ultralytics", "sqlalchemy"}
    checks = _by_name(check_env.collect())
    assert checks["torch"].status == "warn"
    assert checks["extra detection"].status == "warn"
    assert "--extra backend" in checks["extra backend"].detail
    assert checks["extra vision"].status == "ok"
    assert check_env.main() == 0


def test_missing_base_dependency_fails(machine):
    machine["missing_modules"].add("pydantic")
    assert check_env.check_base().status == "fail"


def test_rclone_without_drive_remote_warns(machine):
    machine["commands"]["rclone"] = "other:"
    rclone = _by_name(check_env.check_tools())["rclone"]
    assert rclone.status == "warn" and "gdrive:" in rclone.detail


def test_report_one_line_per_check():
    checks = [check_env.Check("a", "ok"), check_env.Check("long name", "fail", "why")]
    lines = check_env.report(checks).splitlines()
    assert lines == ["[OK  ] a", "[FAIL] long name  why"]
