// Server-Sent Events of `POST /api/agent/chat` (docs/11 §7): the request is a POST, so the
// stream is read with fetch rather than EventSource.
import { ApiError, authHeaders } from "./client";

export type AgentEvent =
  | { type: "conversation"; id: string }
  | { type: "texte"; texte: string }
  | { type: "outil"; nom: string; arguments: unknown; resume: string; erreur?: string | null }
  | { type: "proposition"; decision: import("./types").DecisionRecord }
  | { type: "fin"; conversation: string; tokens: unknown }
  | { type: "erreur"; message: string; conversation?: string };

/** Splits an SSE byte stream into events (`data:` lines joined, JSON-decoded). */
export async function* parseSSE(body: ReadableStream<Uint8Array>): AsyncGenerator<AgentEvent> {
  const reader = body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (value) buffer += value;
    let sep: number;
    while ((sep = buffer.search(/\r?\n\r?\n/)) >= 0) {
      const chunk = buffer.slice(0, sep);
      buffer = buffer.slice(sep).replace(/^\r?\n\r?\n/, "");
      const data = chunk
        .split(/\r?\n/)
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).replace(/^ /, ""))
        .join("\n");
      if (data) yield JSON.parse(data) as AgentEvent;
    }
    if (done) return;
  }
}

export async function* chat(
  message: string,
  conversationId: string | null,
  signal?: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const res = await fetch("/api/agent/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ message, conversation_id: conversationId }),
    signal,
  });
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.detail ?? `erreur HTTP ${res.status}`);
  }
  yield* parseSSE(res.body);
}
