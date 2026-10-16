"""Configuration published to the controller (docs/09 §8, docs/12 §2.1).

The builder edits the database; `POST /api/config/publier` turns it into a new versioned
serre.yaml (`backend.config.export`: validated like the controller does, a new version
only when the content changed) and installs it (local copy and/or rsync to the Pi, set
by `python -m backend.api --install / --rsync`). The consistency banner shows the
warnings of `edge/controller/coherence.py` and the incompatible recipes of a zone.
"""

import difflib
import logging
import subprocess

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select

from edge.controller.config import Greenhouse, SerreCfg

from ..config.export import build_config, deliver, export, render
from ..db import models as m
from ..db.session import utc
from .deps import Db, Now

log = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"])


def _draft(s) -> tuple[SerreCfg, Greenhouse]:
    """The configuration of the database as it would be published; 422 if invalid. The
    warnings are returned to the UI, not logged at every request."""
    quiet = logging.getLogger("edge.controller.config")
    level = quiet.level
    quiet.setLevel(logging.ERROR)
    try:
        raw = build_config(s)
        cfg = SerreCfg.model_validate({**raw, "config_version": 0})
        return cfg, Greenhouse(cfg, cfg.load_recipes())
    except (ValidationError, ValueError, KeyError, RuntimeError) as e:
        raise HTTPException(422, f"configuration invalide : {e}") from e
    finally:
        quiet.setLevel(level)


def _last(s) -> m.ConfigExport | None:
    return s.scalars(
        select(m.ConfigExport).order_by(m.ConfigExport.version.desc()).limit(1)
    ).first()


@router.get("/coherence")
def coherence(s: Db) -> dict:
    """Warnings (the controller runs with them) and errors (publication refused)."""
    try:
        _, gh = _draft(s)
    except HTTPException as e:
        return dict(valide=False, erreurs=[e.detail], avertissements=[])
    warnings = list(gh.warnings)
    for zone, sp in gh.setpoints.items():
        if sp is not None and sp.incompatibles:
            warnings.append(f"{zone} : recettes incompatibles ({', '.join(sp.incompatibles)})")
    return dict(valide=True, erreurs=[], avertissements=warnings)


@router.get("/versions")
def versions(s: Db) -> list[dict]:
    rows = s.scalars(select(m.ConfigExport).order_by(m.ConfigExport.version.desc()))
    return [dict(version=r.version, ts=utc(r.ts), sha256=r.sha256) for r in rows]


def _yaml(s, version: int | None) -> tuple[str, str]:
    """(label, YAML) of a published version, or of the draft for None."""
    if version is None:
        cfg, _ = _draft(s)
        last = _last(s)
        cfg = cfg.model_copy(update={"config_version": (last.version if last else 0) + 1})
        return "brouillon", render(cfg)
    r = s.get(m.ConfigExport, version)
    if r is None:
        raise HTTPException(404, f"version de configuration inconnue {version}")
    return f"v{version}", render(SerreCfg.model_validate(r.contenu))


@router.get("/diff")
def diff(s: Db, de: int | None = None, a: int | None = None) -> dict:
    """Unified diff of serre.yaml between two versions; default: last published → draft
    (what `publier` would change)."""
    if de is None:
        last = _last(s)
        de = last.version if last else None
    label_a, text_a = _yaml(s, a)
    if de is None:
        label_de, text_de = "vide", ""
    else:
        label_de, text_de = _yaml(s, de)

    def body(text: str) -> list[str]:  # without the header comment (version, generator)
        return [line for line in text.splitlines(keepends=True)
                if not line.startswith(("#", "config_version:"))]  # fmt: skip

    lines = list(difflib.unified_diff(body(text_de), body(text_a), label_de, label_a))
    return dict(de=label_de, a=label_a, identique=not lines, diff="".join(lines))


@router.post("/publier")
def publish(s: Db, now: Now, request: Request) -> dict:
    """New `config_version` (or the current one when nothing changed), installed for the
    controller, which hot-reloads it and records it in every decision."""
    _draft(s)  # readable 422 before export() raises
    exp = export(s, now)
    st = request.app.state.settings
    try:
        path = deliver(exp, st.config_out, st.config_install, st.config_rsync)
    except (OSError, subprocess.CalledProcessError) as e:
        raise HTTPException(502, f"configuration non installée (rien publié) : {e}") from e
    return dict(
        config_version=exp.version,
        nouvelle=exp.changed,
        avertissements=exp.warnings,
        fichier=str(path),
        installee=str(st.config_install) if st.config_install else None,
        rsync=st.config_rsync,
    )
