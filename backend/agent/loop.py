"""Tool-use loop of the agent (docs/11 §2): one user message → events for the UI.

`Agent.chat()` yields events (dicts with a `type`):
- `conversation` {id}: first event, the id to send back to continue the conversation;
- `texte` {texte}: a delta of the answer, as it streams;
- `outil` {nom, arguments, resume, erreur}: a tool call and the summary of its result;
- `proposition` {decision}: a proposal created (card Valider / Rejeter of the UI);
- `fin` {tokens}: tokens of this message; `erreur` {message}: agent unavailable, budget
  reached, refusal of the model…

Everything is logged in `agent_journal` (docs/11 §4.6): user message, answers with the
model and the tokens, tool calls with their arguments and results, errors. Budgets
(docs/11 §4.8) are checked on the logged tokens before each API call. The history is
saved only at consistent points (no `tool_use` without its result).
"""

import json
import logging
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..db import models as m
from ..db.session import utc
from ..traceability import reconcile
from .config import AgentConfig
from .consignes import restore_expired
from .llm import AgentIndisponible, Turn
from .prompts import system_blocks
from .tools import Tools, definitions

log = logging.getLogger(__name__)

TOKEN_COLS = (
    m.AgentJournal.tokens_entree,
    m.AgentJournal.tokens_sortie,
    m.AgentJournal.tokens_cache_lus,
    m.AgentJournal.tokens_cache_ecrits,
)


class Agent:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        llm,
        publisher=None,
        cfg: AgentConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.sessions = sessions
        self.llm = llm
        self.cfg = cfg or AgentConfig()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.tools = Tools(sessions, publisher, self.cfg, self.clock)

    def chat(
        self, message: str, conversation_id: str | None = None, utilisateur: str = "ui"
    ) -> Iterator[dict]:
        now = utc(self.clock())
        with self.sessions.begin() as s:
            reconcile(s, now)  # expired proposals, plant states…
            restore_expired(s, now)
            conv = s.get(m.AgentConversation, conversation_id) if conversation_id else None
            if conversation_id and conv is None:
                yield dict(type="erreur", message=f"conversation inconnue {conversation_id}")
                return
            if conv is None:
                conv = m.AgentConversation(
                    id=f"conv-{uuid.uuid4().hex[:12]}", ts_debut=now, ts_maj=now,
                    utilisateur=utilisateur, modele=self.llm.modele, titre=message[:80],
                    messages=[],
                )  # fmt: skip
                s.add(conv)
            cid, history = conv.id, list(conv.messages)
            tz = s.scalars(select(m.Serre.fuseau)).first() or "UTC"
            self._log(s, cid, "utilisateur", {"texte": message, "utilisateur": utilisateur})
        yield dict(type="conversation", id=cid)

        from zoneinfo import ZoneInfo

        local = now.astimezone(ZoneInfo(tz)).isoformat(timespec="minutes")
        history.append({"role": "user", "content": f"[{local}] {message}"})
        self._save(cid, history)
        total = dict(entree=0, sortie=0, cache_lus=0, cache_ecrits=0)
        tools = definitions()
        for _ in range(self.cfg.max_tours):
            refus = self._budget(cid)
            if refus:
                yield self._error(cid, refus)
                return
            with self.sessions.begin() as s:
                system = system_blocks(s)
            try:
                turn: Turn = yield from self._stream(system, tools, history)
            except AgentIndisponible as e:
                yield self._error(cid, f"agent indisponible : {e}")
                return
            u = turn.usage
            for k, key in (("entree", "input_tokens"), ("sortie", "output_tokens"),
                           ("cache_lus", "cache_read_input_tokens"),
                           ("cache_ecrits", "cache_creation_input_tokens")):  # fmt: skip
                total[k] += u.get(key, 0)
            with self.sessions.begin() as s:
                self._log(s, cid, "assistant", {"content": turn.content,
                                                 "stop_reason": turn.stop_reason},
                          turn.modele or self.llm.modele, u)  # fmt: skip
            history.append({"role": "assistant", "content": turn.content})
            if turn.stop_reason == "pause_turn":
                self._save(cid, history)
                continue
            if turn.stop_reason == "refusal":
                self._save(cid, history)
                yield self._error(cid, "le modèle a refusé de répondre à cette demande")
                return
            uses = turn.tool_uses
            if not uses:
                self._save(cid, history)
                yield dict(type="fin", conversation=cid, tokens=total)
                return
            if turn.stop_reason == "max_tokens":  # a truncated tool input is never run
                history.pop()
                self._save(cid, history)
                yield self._error(cid, "réponse tronquée (max_tokens), outil non exécuté")
                return
            results = []
            for use in uses:
                r = self.tools.run(use["name"], use.get("input"), cid)
                with self.sessions.begin() as s:
                    call = {"id": use["id"], "nom": use["name"]}
                    self._log(s, cid, "appel_outil", dict(call, arguments=use.get("input")))
                    self._log(s, cid, "resultat_outil",
                              dict(call, erreur=r.error, resultat=r.content))  # fmt: skip
                yield dict(type="outil", nom=use["name"], arguments=use.get("input"),
                           resume=r.resume, erreur=r.error)  # fmt: skip
                if r.proposition is not None:
                    yield dict(type="proposition", decision=_jsonable(r.proposition))
                block = {"type": "tool_result", "tool_use_id": use["id"], "content": r.text()}
                if r.error:
                    block["is_error"] = True
                results.append(block)
            history.append({"role": "user", "content": results})  # all results at once
            self._save(cid, history)
        yield self._error(cid, f"trop d'appels d'outils ({self.cfg.max_tours}) pour un message")

    # --- helpers ---------------------------------------------------------------------------

    def _stream(self, system, tools, history):
        gen = self.llm.turn(system, tools, history)
        while True:
            try:
                delta = next(gen)
            except StopIteration as stop:
                return stop.value
            yield dict(type="texte", texte=delta)

    def _budget(self, cid: str) -> str | None:
        now = utc(self.clock())
        tokens = sum(TOKEN_COLS)
        with self.sessions.begin() as s:
            conv = s.scalar(
                select(func.coalesce(func.sum(tokens), 0)).where(
                    m.AgentJournal.conversation_id == cid
                )
            )
            day = s.scalar(
                select(func.coalesce(func.sum(tokens), 0)).where(
                    m.AgentJournal.ts >= now - timedelta(hours=24)
                )
            )
        if conv >= self.cfg.tokens_conversation:
            return f"budget de la conversation atteint ({conv} tokens) : en ouvrir une nouvelle"
        if day >= self.cfg.tokens_jour:
            return f"budget journalier de l'agent atteint ({day} tokens sur 24 h)"
        return None

    def _log(self, s: Session, cid: str, type_: str, contenu: dict, modele=None, usage=None):
        u = usage or {}
        s.add(
            m.AgentJournal(
                conversation_id=cid,
                ts=utc(self.clock()),
                type=type_,
                contenu=_jsonable(contenu),
                modele=modele,
                tokens_entree=u.get("input_tokens", 0),
                tokens_sortie=u.get("output_tokens", 0),
                tokens_cache_lus=u.get("cache_read_input_tokens", 0),
                tokens_cache_ecrits=u.get("cache_creation_input_tokens", 0),
            )
        )

    def _save(self, cid: str, history: list[dict]) -> None:
        with self.sessions.begin() as s:
            conv = s.get(m.AgentConversation, cid)
            conv.messages, conv.ts_maj = _jsonable(history), utc(self.clock())

    def _error(self, cid: str, message: str) -> dict:
        log.warning("agent %s : %s", cid, message)
        with self.sessions.begin() as s:
            self._log(s, cid, "erreur", {"message": message})
        return dict(type="erreur", message=message)


def _jsonable(x):
    return json.loads(json.dumps(x, ensure_ascii=False, default=str))
