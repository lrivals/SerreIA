"""Helpers of the configuration routes (docs/12 §3): rows as dicts, 404, partial updates."""

from datetime import datetime

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from ..db.session import utc


def row(obj) -> dict:
    """Columns of an ORM row (timestamps in UTC)."""
    out = {}
    for col in inspect(obj).mapper.column_attrs:
        v = getattr(obj, col.key)
        out[col.key] = utc(v) if isinstance(v, datetime) else v
    return out


def get(s: Session, model, key, what: str):
    obj = s.get(model, key)
    if obj is None:
        raise HTTPException(404, f"{what} inconnu(e) {key}")
    return obj


def absent(s: Session, model, key, what: str) -> None:
    if s.get(model, key) is not None:
        raise HTTPException(409, f"{what} {key} existe déjà")


def patch(obj, body: BaseModel, skip: tuple[str, ...] = ()) -> None:
    """Apply the fields actually sent (PATCH)."""
    for k, v in body.model_dump(exclude_unset=True).items():
        if k not in skip:
            setattr(obj, k, v)


def in_use(what: str, by: str) -> HTTPException:
    return HTTPException(409, f"{what} est utilisé(e) par {by}")
