"""Dependencies of the routes: database session (one transaction per request), MQTT
publisher and clock, all set by `create_app`."""

from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session


def session(request: Request):
    with request.app.state.sessions.begin() as s:
        yield s


def publisher(request: Request):
    if request.app.state.publisher is None:
        raise HTTPException(503, "API en lecture seule : pas de connexion MQTT")
    return request.app.state.publisher


def now(request: Request) -> datetime:
    return request.app.state.clock()


Db = Annotated[Session, Depends(session)]
Pub = Annotated[object, Depends(publisher)]
Now = Annotated[datetime, Depends(now)]
