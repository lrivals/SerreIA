"""Dataset statistics reports (docs/19 §1): `summary.json` + `summary.md` in one folder.

Shared by the vision (`vision.datasets.stats`) and sensor (`sim.stats`) notebooks, without
depending on either.
"""

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports" / "datasets"


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def to_jsonable(obj):
    """numpy / pandas scalars and containers to plain JSON types (NaN -> None)."""
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return to_jsonable(obj.reset_index().to_dict(orient="records"))
    if isinstance(obj, pd.Series):
        return to_jsonable(obj.to_dict())
    if isinstance(obj, np.ndarray):
        return to_jsonable(obj.tolist())
    if isinstance(obj, np.integer | np.bool_):
        return obj.item()
    if isinstance(obj, float | np.floating):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(obj, datetime | pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    return obj


def write_report(
    out_dir: Path, summary: dict, sections: dict[str, "pd.DataFrame | str"] | None = None
) -> Path:
    """Writes `summary.json` (summary + date) and `summary.md` (key figures then sections).

    Returns the folder. Figures are saved by the plot functions next to these files.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"date": datetime.now(UTC).isoformat(timespec="seconds"), **summary}
    (out_dir / "summary.json").write_text(
        json.dumps(to_jsonable(payload), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    lines = [f"# {out_dir.name}", "", "| Indicateur | Valeur |", "|---|---|"]
    for k, v in to_jsonable(payload).items():
        if not isinstance(v, dict | list):
            lines.append(f"| {k} | {v} |")
    for title, content in (sections or {}).items():
        lines += ["", f"## {title}", ""]
        if isinstance(content, pd.DataFrame | pd.Series):
            if _has_tabulate():
                lines.append(content.to_markdown())
            else:
                lines += ["```", content.to_string(), "```"]
        else:
            lines.append(str(content))
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_dir


def _has_tabulate() -> bool:
    try:
        import tabulate  # noqa: F401
    except ImportError:
        return False
    return True
