"""Optional authentication of the UI (docs/12 §1): a password, then a session token.

Without `password` (no `SERREIA_UI_PASSWORD`), the API is open on the LAN. With it, every
request that is not a read (GET, HEAD) needs `Authorization: Bearer <token>`: the actions
on the greenhouse, the configuration changes and the agent (it spends tokens). Tokens live
in memory: a restart of the API logs everyone out.
"""

import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .deps import Now, User, user

TOKEN_TTL = timedelta(days=7)
READS = ("GET", "HEAD", "OPTIONS")
# Writes open without a token: the login, and the camera_service uploader (it has none).
OPEN = ("/api/auth/login", "/api/images")

router = APIRouter(prefix="/auth", tags=["auth"])


@dataclass
class Auth:
    password: str | None = None
    tokens: dict[str, tuple[str, datetime]] = field(default_factory=dict)  # → (user, expiry)

    @property
    def required(self) -> bool:
        return bool(self.password)

    def login(self, password: str, user: str, now: datetime) -> str:
        if not self.required or not hmac.compare_digest(password.encode(), self.password.encode()):
            raise HTTPException(401, "mot de passe incorrect")
        token = secrets.token_urlsafe(32)
        self.tokens[token] = (user, now + TOKEN_TTL)
        return token

    def user(self, token: str | None, now: datetime) -> str | None:
        entry = self.tokens.get(token or "")
        if entry is None or entry[1] <= now:
            self.tokens.pop(token or "", None)
            return None
        return entry[0]


def check(request: Request) -> None:
    """Dependency of the /api router: writes need a valid token when a password is set."""
    auth: Auth = request.app.state.auth
    if not auth.required or request.method in READS or request.url.path in OPEN:
        return
    if user(request) is None:
        raise HTTPException(401, "authentification requise", headers={"WWW-Authenticate": "Bearer"})


class Login(BaseModel):
    mot_de_passe: str = Field(min_length=1)
    utilisateur: str = Field(default="ui", min_length=1, max_length=64)


@router.get("")
def status(request: Request, u: User) -> dict:
    return dict(requise=request.app.state.auth.required, utilisateur=u)


@router.post("/login")
def login(body: Login, request: Request, now: Now) -> dict:
    token = request.app.state.auth.login(body.mot_de_passe, body.utilisateur, now)
    return dict(jeton=token, utilisateur=body.utilisateur, expire=now + TOKEN_TTL)


@router.post("/logout")
def logout(request: Request) -> dict:
    token = request.headers.get("authorization", "").partition(" ")[2]
    request.app.state.auth.tokens.pop(token, None)
    return dict(ok=True)
