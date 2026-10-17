// `WS /ws/live` (docs/12 §3): the bus relayed by the server. Each message invalidates the
// queries it makes stale (throttled), so every screen follows the greenhouse live.
import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

export interface LiveEvent {
  kind: "capteur" | "vision" | "alerte" | "cmd" | "etat" | "status" | "decision" | "info";
  zone: string | null;
  subject: string | null;
  payload: unknown;
}

const STALE: Record<string, string[][]> = {
  capteur: [["tableau"], ["mesures"]],
  vision: [["tableau"], ["vision"], ["plan"]],
  alerte: [["tableau"], ["alertes"]],
  etat: [["tableau"], ["actionneurs"]],
  cmd: [["decisions"], ["arbre"]],
  decision: [["tableau"], ["decisions"], ["arbre"], ["plan"], ["conversations"]],
  status: [["noeuds"]],
};
const THROTTLE_MS = 3000;

interface Live {
  connected: boolean;
  last: LiveEvent | null;
  received: number;
  /** Every event, not only the last one (game view, docs/13 §5); returns the unsubscribe. */
  subscribe: (fn: (e: LiveEvent) => void) => () => void;
}

const listeners = new Set<(e: LiveEvent) => void>();
const subscribe = (fn: (e: LiveEvent) => void) => {
  listeners.add(fn);
  return () => void listeners.delete(fn);
};

const LiveContext = createContext<Live>({ connected: false, last: null, received: 0, subscribe });
export const useLive = () => useContext(LiveContext);

export function LiveProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [state, setState] = useState<Live>({ connected: false, last: null, received: 0, subscribe });
  const pending = useRef(new Set<string>());
  const timer = useRef<number | null>(null);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: number | null = null;
    let closed = false;

    const flush = () => {
      timer.current = null;
      for (const key of pending.current) qc.invalidateQueries({ queryKey: JSON.parse(key) });
      pending.current.clear();
    };

    const connect = () => {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${window.location.host}/ws/live`);
      ws.onopen = () => setState((s) => ({ ...s, connected: true }));
      ws.onclose = () => {
        setState((s) => ({ ...s, connected: false }));
        if (!closed) retry = window.setTimeout(connect, 3000);
      };
      ws.onmessage = (msg) => {
        const e = JSON.parse(msg.data) as LiveEvent;
        setState((s) => ({ ...s, last: e, received: s.received + 1 }));
        listeners.forEach((fn) => fn(e));
        for (const key of STALE[e.kind] ?? []) pending.current.add(JSON.stringify(key));
        if (timer.current === null) timer.current = window.setTimeout(flush, THROTTLE_MS);
      };
    };
    connect();
    return () => {
      closed = true;
      if (retry !== null) window.clearTimeout(retry);
      if (timer.current !== null) window.clearTimeout(timer.current);
      ws?.close();
    };
  }, [qc]);

  return <LiveContext.Provider value={state}>{children}</LiveContext.Provider>;
}
