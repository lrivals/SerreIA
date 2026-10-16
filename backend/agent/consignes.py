"""Recipe changes proposed by the agent (`proposer_consigne`, docs/11 §3), applied by the
server once the user validated them.

The MQTT contract has no setpoint order: on validation, `apply_validated` writes the new
value in `recette.stades`, keeps the previous one and exports a new `config_version`
(`backend.config.export.export`); the decision gets the label "consigne:…" (confirmed). A
temporary change (`duree_h`) is undone by `restore_expired`, run by the ingestion after
each batch and by the agent before each message. Installing the exported serre.yaml on
the Pi stays `make config-export PI_CONFIG=…` (docs/09 §8).
"""

import copy
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config.export import export
from ..db import models as m
from ..db.session import utc
from ..traceability import sync_actions

log = logging.getLogger(__name__)

PREFIX = "proposee:consigne "


def get_value(stades: dict, stade: str, grandeur: str):
    node = stades[stade]
    for key in grandeur.split("."):
        node = node.get(key) if isinstance(node, dict) else None
    return node


def with_value(stades: dict, stade: str, grandeur: str, valeur) -> dict:
    """A copy of `stades` with `grandeur` ("humidite", "temperature.nuit"…) of `stade` set."""
    out = copy.deepcopy(stades)
    *path, last = grandeur.split(".")
    node = out[stade]
    for key in path:
        node = node.setdefault(key, {})
    if valeur is None:
        node.pop(last, None)
    else:
        node[last] = valeur
    return out


def label(consigne: dict) -> str:
    """ "consigne tomate-standard/floraison humidite [55, 60] 72 h"."""
    v = consigne["valeur"]
    s = f"consigne {consigne['recette_id']}/{consigne['stade']} {consigne['grandeur']} "
    s += f"[{v[0]:g}, {v[1]:g}]" if isinstance(v, list) else f"{v:g}"
    return s + (f" {consigne['duree_h']:g} h" if consigne.get("duree_h") else "")


def apply_validated(s: Session, d: m.Decision, now: datetime) -> int | None:
    """Apply the recipe change of a validated agent decision; returns the exported
    `config_version` (None: not a setpoint proposal, or the export failed)."""
    p = s.get(m.AgentProposition, d.id)
    if p is None or p.consigne is None or p.appliquee is not None:
        return None
    c = p.consigne
    r = s.get(m.Recette, c["recette_id"])
    if r is None:
        log.warning("%s : recette %s supprimée, consigne non appliquée", d.id, c["recette_id"])
        return None
    now = utc(now)
    previous = _active(s, c, exclude=d.id)
    if previous is not None:  # a temporary change already holds: restore to its own origin
        p.ancienne, previous.restauree = previous.ancienne, now
    else:
        p.ancienne = {"valeur": get_value(r.stades, c["stade"], c["grandeur"])}
    r.stades = with_value(r.stades, c["stade"], c["grandeur"], c["valeur"])
    p.appliquee = now
    p.fin = now + timedelta(hours=c["duree_h"]) if c.get("duree_h") else None
    d.actions = [a.removeprefix("proposee:") if a.startswith(PREFIX) else a for a in d.actions]
    s.flush()
    sync_actions(s, [d.id])
    return _export(s, now, f"consigne {d.id}")


def restore_expired(s: Session, now: datetime) -> list[str]:
    """Undo the temporary changes whose end is past; returns their decision ids."""
    now = utc(now)
    done = []
    for p in s.scalars(
        select(m.AgentProposition).where(
            m.AgentProposition.fin.isnot(None), m.AgentProposition.restauree.is_(None)
        )
    ):
        if utc(p.fin) > now:
            continue
        c = p.consigne
        r = s.get(m.Recette, c["recette_id"])
        if r is not None:
            old = (p.ancienne or {}).get("valeur")
            r.stades = with_value(r.stades, c["stade"], c["grandeur"], old)
        p.restauree = now
        done.append(p.decision_id)
    if done:
        s.flush()
        _export(s, now, f"fin des consignes temporaires {', '.join(done)}")
    return done


def _active(s: Session, c: dict, exclude: str) -> m.AgentProposition | None:
    """The temporary change still applied on the same recipe value, if any."""
    for p in s.scalars(
        select(m.AgentProposition).where(
            m.AgentProposition.appliquee.isnot(None),
            m.AgentProposition.fin.isnot(None),
            m.AgentProposition.restauree.is_(None),
            m.AgentProposition.decision_id != exclude,
        )
    ):
        o = p.consigne
        if (o["recette_id"], o["stade"], o["grandeur"]) == (
            c["recette_id"],
            c["stade"],
            c["grandeur"],
        ):
            return p
    return None


def _export(s: Session, now: datetime, why: str) -> int | None:
    try:
        e = export(s, now)
    except (ValueError, KeyError) as err:  # the recipe in base no longer validates
        log.error("export de la configuration impossible après %s : %s", why, err)
        return None
    log.info("%s → configuration v%d (à installer sur le Pi)", why, e.version)
    return e.version
