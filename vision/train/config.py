"""YAML run configs with `_base_` inheritance and `--set a.b=c` overrides (docs/08 §4)."""

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        out[k] = (
            deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
        )
    return out


def load_config(path: Path) -> dict:
    """Config at path, merged over its `_base_` (path relative to the file), recursively."""
    path = Path(path)
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    base = cfg.pop("_base_", None)
    if base is not None:
        cfg = deep_merge(load_config(path.parent / base), cfg)
    return cfg


def apply_overrides(cfg: dict, overrides: list[str]) -> dict:
    """`a.b=value` pairs, value parsed as YAML (numbers, booleans, lists)."""
    cfg = copy.deepcopy(cfg)
    for item in overrides:
        key, sep, raw = item.partition("=")
        if not sep:
            raise ValueError(f"override attendu sous la forme clé=valeur : {item!r}")
        *parents, leaf = key.split(".")
        node = cfg
        for p in parents:
            node = node.setdefault(p, {})
        node[leaf] = yaml.safe_load(raw)
    return cfg


def flatten(cfg: dict, prefix: str = "") -> dict[str, object]:
    out = {}
    for k, v in cfg.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, f"{key}."))
        else:
            out[key] = v
    return out


def resolve(path: str | Path) -> Path:
    """Paths in configs are relative to the repository root."""
    p = Path(path)
    return p if p.is_absolute() else ROOT / p
