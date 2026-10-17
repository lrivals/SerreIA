"""Agent (docs/11, docs/12 §2.7): chat in Server-Sent Events, conversations and their log.

The agent only proposes: its proposals are `proposee` decisions that the user answers with
`POST /decisions/{id}/valider` or `/rejeter`. Without an agent (no `anthropic`, no key),
these routes answer 503 and the rest of the API works the same (docs/11 §1).
"""

import json
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..db import models as m
from ..db.session import utc
from .deps import Db, User

router = APIRouter(prefix="/agent", tags=["agent"])


class Message(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    utilisateur: str = "ui"


def _agent(request: Request):
    agent = request.app.state.agent
    if agent is None:
        raise HTTPException(503, "agent indisponible : pas de client LLM configuré")
    return agent


def sse(events: Iterator[dict]) -> Iterator[str]:
    for e in events:
        yield f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False, default=str)}\n\n"


@router.get("/statut")
def status(request: Request) -> dict:
    """Whether the chat is available (the UI shows a banner otherwise)."""
    agent = request.app.state.agent
    llm = getattr(agent, "llm", None)
    return dict(disponible=agent is not None, modele=getattr(llm, "modele", None))


@router.post("/chat")
def chat(msg: Message, request: Request, u: User) -> StreamingResponse:
    agent = _agent(request)
    events = agent.chat(msg.message, msg.conversation_id, u or msg.utilisateur)
    return StreamingResponse(sse(events), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})  # fmt: skip


@router.get("/conversations")
def conversations(s: Db, limit: int = 50) -> list[dict]:
    tokens = func.sum(
        m.AgentJournal.tokens_entree
        + m.AgentJournal.tokens_sortie
        + m.AgentJournal.tokens_cache_lus
        + m.AgentJournal.tokens_cache_ecrits
    )
    totals = dict(s.execute(select(m.AgentJournal.conversation_id, tokens).group_by(
        m.AgentJournal.conversation_id)).all())  # fmt: skip
    rows = s.scalars(
        select(m.AgentConversation).order_by(m.AgentConversation.ts_maj.desc()).limit(limit)
    )
    return [
        dict(id=c.id, titre=c.titre, utilisateur=c.utilisateur, modele=c.modele,
             ts_debut=utc(c.ts_debut), ts_maj=utc(c.ts_maj), tokens=totals.get(c.id, 0) or 0)
        for c in rows
    ]  # fmt: skip


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: str, s: Db) -> dict:
    """The conversation, its full log and its proposals with their current status."""
    c = s.get(m.AgentConversation, conversation_id)
    if c is None:
        raise HTTPException(404, f"conversation inconnue {conversation_id}")
    journal = s.scalars(
        select(m.AgentJournal)
        .where(m.AgentJournal.conversation_id == c.id)
        .order_by(m.AgentJournal.id)
    )
    props = []
    for p in s.scalars(
        select(m.AgentProposition).where(m.AgentProposition.conversation_id == c.id)
    ):
        d = s.get(m.Decision, p.decision_id)
        props.append(
            dict(decision_id=p.decision_id, outil=p.outil, statut=d.statut if d else None,
                 justification=p.justification, preuves_refs=p.preuves_refs,
                 consigne=p.consigne, appliquee=p.appliquee, fin=p.fin, restauree=p.restauree)
        )  # fmt: skip
    return dict(
        id=c.id,
        titre=c.titre,
        utilisateur=c.utilisateur,
        modele=c.modele,
        ts_debut=utc(c.ts_debut),
        ts_maj=utc(c.ts_maj),
        messages=c.messages,
        journal=[
            dict(
                ts=utc(j.ts),
                type=j.type,
                contenu=j.contenu,
                modele=j.modele,
                tokens=dict(
                    entree=j.tokens_entree,
                    sortie=j.tokens_sortie,
                    cache_lus=j.tokens_cache_lus,
                    cache_ecrits=j.tokens_cache_ecrits,
                ),
            )
            for j in journal
        ],  # fmt: skip
        propositions=props,
    )
