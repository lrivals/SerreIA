// Agent (docs/12 §2.7, docs/11): streamed chat, tool calls shown collapsed, proposals as
// cards with Validate / Reject, clickable references. When the agent is unavailable a
// banner says so and the rest of the UI keeps working.
import { useQueryClient } from "@tanstack/react-query";
import * as Collapsible from "@radix-ui/react-collapsible";
import { Bot, ChevronRight, MessageSquarePlus, Send, Square, User, Wrench } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { useAgentStatut, useConversation, useConversations, useDecision } from "@/api/hooks";
import { chat } from "@/api/sse";
import type { ContentBlock, ConversationDetail, DecisionRecord } from "@/api/types";
import { CarteProposition } from "@/components/CarteProposition";
import { ErrorBox, Loading, RefText } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { fmtDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export type Part =
  | { kind: "text"; text: string }
  | { kind: "tool"; nom: string; resume: string; erreur?: string | null; arguments?: unknown }
  | { kind: "proposition"; decision?: DecisionRecord; id: string };

export type Turn = { role: "user"; text: string } | { role: "assistant"; parts: Part[]; error?: string };

/** Turns of a stored conversation (Claude API format) for the chat view. */
export function turnsOf(c: ConversationDetail): Turn[] {
  const turns: Turn[] = [];
  const proposals = new Set(c.propositions.map((p) => p.decision_id));
  for (const m of c.messages) {
    const blocks: ContentBlock[] = typeof m.content === "string" ? [{ type: "text", text: m.content }] : m.content;
    if (m.role === "user") {
      const text = blocks.filter((b) => b.type === "text").map((b) => (b as { text: string }).text).join("\n");
      if (text) turns.push({ role: "user", text });
      for (const b of blocks)
        if (b.type === "tool_result") {
          const ids = String((b as { content: unknown }).content).match(/dec-\d{8}-\d{4}-z\d+-\w+/g) ?? [];
          const last = turns[turns.length - 1];
          for (const id of new Set(ids))
            if (proposals.has(id) && last?.role === "assistant" && !last.parts.some((p) => p.kind === "proposition" && p.id === id)) {
              last.parts.push({ kind: "proposition", id });
            }
        }
      continue;
    }
    const parts: Part[] = [];
    for (const b of blocks) {
      if (b.type === "text") parts.push({ kind: "text", text: (b as { text: string }).text });
      else if (b.type === "tool_use") {
        const u = b as { name: string; input: unknown };
        parts.push({ kind: "tool", nom: u.name, resume: u.name, arguments: u.input });
      }
    }
    const last = turns[turns.length - 1];
    if (last?.role === "assistant") last.parts.push(...parts);
    else turns.push({ role: "assistant", parts });
  }
  return turns;
}

function AppelOutil({ p }: { p: Extract<Part, { kind: "tool" }> }) {
  return (
    <Collapsible.Root className="text-xs">
      <Collapsible.Trigger className="group flex cursor-pointer items-center gap-1 text-muted-foreground hover:text-foreground">
        <ChevronRight className="h-3 w-3 transition-transform group-data-[state=open]:rotate-90" />
        <Wrench className="h-3 w-3" />
        {p.erreur ? <span className="text-bad">refusé : {p.erreur}</span> : <>a consulté : {p.resume}</>}
      </Collapsible.Trigger>
      <Collapsible.Content>
        <pre className="mt-1 ml-5 overflow-x-auto rounded bg-muted p-2">
          {p.nom}({JSON.stringify(p.arguments ?? {}, null, 1)})
        </pre>
      </Collapsible.Content>
    </Collapsible.Root>
  );
}

function PropositionStockee({ id }: { id: string }) {
  const { data } = useDecision(id);
  return data ? <CarteProposition decision={data} /> : null;
}

function Bulle({ turn }: { turn: Turn }) {
  if (turn.role === "user")
    return (
      <div className="flex justify-end gap-2">
        <div className="max-w-[80%] rounded-lg bg-primary px-3 py-2 text-sm whitespace-pre-wrap text-primary-foreground">{turn.text}</div>
        <User className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" />
      </div>
    );
  return (
    <div className="flex gap-2">
      <Bot className="mt-1 h-4 w-4 shrink-0 text-primary" />
      <div className="flex max-w-[85%] min-w-0 flex-col gap-2 text-sm">
        {turn.parts.map((p, i) =>
          p.kind === "text" ? (
            <p key={i} className="leading-relaxed whitespace-pre-wrap">
              <RefText text={p.text} />
            </p>
          ) : p.kind === "tool" ? (
            <AppelOutil key={i} p={p} />
          ) : p.decision ? (
            <CarteProposition key={i} decision={p.decision} />
          ) : (
            <PropositionStockee key={i} id={p.id} />
          ),
        )}
        {turn.error && <ErrorBox error={turn.error} />}
      </div>
    </div>
  );
}

export function Agent() {
  const [params, setParams] = useSearchParams();
  const conversationId = params.get("conversation");
  const list = useConversations();
  const statut = useAgentStatut();
  const stored = useConversation(conversationId);
  const qc = useQueryClient();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState(params.get("message") ?? "");
  const [busy, setBusy] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (stored.data && !busy) setTurns(turnsOf(stored.data));
    if (!conversationId) setTurns([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stored.data, conversationId]);
  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [turns]);
  useEffect(() => {
    if (statut.data) setUnavailable(!statut.data.disponible);
    else if (statut.error) setUnavailable(true);
  }, [statut.data, statut.error]);

  const update = (fn: (last: Extract<Turn, { role: "assistant" }>) => void) =>
    setTurns((ts) => {
      const copy = [...ts];
      const last = { ...(copy[copy.length - 1] as Extract<Turn, { role: "assistant" }>) };
      last.parts = [...last.parts];
      fn(last);
      copy[copy.length - 1] = last;
      return copy;
    });

  const send = async () => {
    const message = input.trim();
    if (!message || busy) return;
    setInput("");
    setBusy(true);
    setTurns((ts) => [...ts, { role: "user", text: message }, { role: "assistant", parts: [] }]);
    abort.current = new AbortController();
    let cid = conversationId;
    try {
      for await (const e of chat(message, cid, abort.current.signal)) {
        if (e.type === "conversation") cid = e.id;
        else if (e.type === "texte")
          update((last) => {
            const prev = last.parts[last.parts.length - 1];
            if (prev?.kind === "text") last.parts[last.parts.length - 1] = { kind: "text", text: prev.text + e.texte };
            else last.parts.push({ kind: "text", text: e.texte });
          });
        else if (e.type === "outil") update((last) => void last.parts.push({ kind: "tool", nom: e.nom, resume: e.resume, erreur: e.erreur, arguments: e.arguments }));
        else if (e.type === "proposition") update((last) => void last.parts.push({ kind: "proposition", id: e.decision.id, decision: e.decision }));
        else if (e.type === "erreur") update((last) => void (last.error = e.message));
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) setUnavailable(true);
      if (!(err instanceof DOMException && err.name === "AbortError"))
        update((last) => void (last.error = err instanceof ApiError ? err.detail : String(err)));
    } finally {
      setBusy(false);
      abort.current = null;
      qc.invalidateQueries({ queryKey: ["conversations"] });
      qc.invalidateQueries({ queryKey: ["tableau"] });
      if (cid && cid !== conversationId) setParams({ conversation: cid }, { replace: true });
    }
  };

  return (
    <div className="grid h-[calc(100vh-7rem)] gap-4 lg:grid-cols-[260px_1fr]">
      <Card className="hidden flex-col overflow-hidden lg:flex">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <span className="text-sm font-semibold">Conversations</span>
          <Button size="icon" variant="ghost" title="Nouvelle conversation" onClick={() => setParams({})}>
            <MessageSquarePlus className="h-4 w-4" />
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {list.data?.map((c) => (
            <button
              key={c.id}
              onClick={() => setParams({ conversation: c.id })}
              className={cn("block w-full cursor-pointer border-b px-3 py-2 text-left text-sm hover:bg-muted", c.id === conversationId && "bg-muted")}
            >
              <div className="line-clamp-2">{c.titre || c.id}</div>
              <div className="text-xs text-muted-foreground">
                {fmtDateTime(c.ts_maj)} · {c.tokens?.toLocaleString("fr-FR")} tokens
              </div>
            </button>
          ))}
        </div>
      </Card>
      <Card className="flex min-h-0 flex-col">
        {unavailable && (
          <div role="alert" className="border-b border-warn/50 bg-warn/10 px-4 py-2 text-sm">
            Agent indisponible (pas de client LLM configuré ou API injoignable). Le reste de l'interface reste utilisable.
          </div>
        )}
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {stored.isLoading && <Loading />}
          {turns.length === 0 && !stored.isLoading && (
            <div className="mx-auto mt-10 max-w-md text-center text-sm text-muted-foreground">
              <Bot className="mx-auto mb-2 h-8 w-8 text-primary" />
              Posez une question sur la serre : « Pourquoi la ventilation a tourné cette nuit ? », « Que faire pour le
              mildiou sur z1-A1 ? ». L'agent consulte les mesures, images et décisions, et ne fait que <em>proposer</em> :
              chaque action attend votre validation.
            </div>
          )}
          {turns.map((t, i) => (
            <Bulle key={i} turn={t} />
          ))}
          <div ref={bottom} />
        </div>
        <form
          className="flex items-end gap-2 border-t p-3"
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <Textarea
            rows={2}
            className="flex-1 resize-none"
            placeholder="Votre question…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            aria-label="Message à l'agent"
          />
          {busy ? (
            <Button variant="outline" onClick={() => abort.current?.abort()} aria-label="Arrêter">
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button type="submit" disabled={!input.trim()} aria-label="Envoyer">
              <Send className="h-4 w-4" />
            </Button>
          )}
        </form>
      </Card>
    </div>
  );
}
