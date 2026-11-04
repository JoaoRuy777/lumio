// Tempo real: lê /api/events (SSE) e recarrega o que mudou.
//
// Usa fetch em vez de EventSource para mandar o token no cabeçalho
// Authorization (EventSource só aceita token na URL, que vaza em logs).
// O aviso só diz "algo mudou"; os dados vêm das rotas normais da API.

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { LOGOUT_EVENT, session } from "./api";

export type LiveStatus = "connecting" | "live" | "offline";

export interface LiveEvent {
  type: "alarm.opened" | "alarm.cleared" | "alarm.acknowledged";
  alarm_id: string;
  kind?: string;
  severity?: string;
  olt_id?: string;
}

interface LiveState {
  status: LiveStatus;
  /** ids de alarmes abertos desde que a tela abriu (para destacar na lista) */
  fresh: Set<string>;
}

const LiveContext = createContext<LiveState>({ status: "offline", fresh: new Set() });

export const useLive = () => useContext(LiveContext);

/** Quebra o texto do SSE em eventos; devolve os completos e o resto (incompleto). */
export function parseSse(buffer: string): { events: { event: string; data: string }[]; rest: string } {
  const blocks = buffer.split(/\r?\n\r?\n/);
  const rest = blocks.pop() ?? "";
  const events = [];
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (data.length) events.push({ event, data: data.join("\n") });
  }
  return { events, rest };
}

// Consultas que cada tipo de aviso pode ter mudado
const AFFECTED = [["overview"], ["alarms"], ["olts"], ["onus"], ["pons"], ["onu"], ["map"], ["customers"], ["at-risk"]];

export function LiveProvider({ children, retryMs = 1000 }: { children: ReactNode; retryMs?: number }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const [fresh, setFresh] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    const abort = new AbortController();
    let attempt = 0;

    function handle(ev: LiveEvent) {
      if (ev.type === "alarm.opened") setFresh((s) => new Set(s).add(ev.alarm_id));
      for (const key of AFFECTED) qc.invalidateQueries({ queryKey: key });
    }

    async function connectOnce(): Promise<"retry" | "stop"> {
      const token = session.get();
      if (!token) return "stop";
      const res = await fetch("/api/events", {
        headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
        signal: abort.signal,
      });
      if (res.status === 401) {
        session.clear();
        window.dispatchEvent(new Event(LOGOUT_EVENT));
        return "stop";
      }
      if (!res.ok || !res.body) return "retry";
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) return "retry";
        const parsed = parseSse(buffer + value);
        buffer = parsed.rest;
        for (const { event, data } of parsed.events) {
          if (event === "ready") {
            attempt = 0;
            setStatus("live");
            // pode ter perdido avisos enquanto estava desconectado
            for (const key of AFFECTED) qc.invalidateQueries({ queryKey: key });
          } else {
            try {
              handle(JSON.parse(data) as LiveEvent);
            } catch {
              /* aviso malformado: ignora */
            }
          }
        }
      }
    }

    (async () => {
      while (!abort.signal.aborted) {
        let outcome: "retry" | "stop" = "retry";
        try {
          outcome = await connectOnce();
        } catch {
          outcome = "retry";
        }
        if (abort.signal.aborted || outcome === "stop") break;
        setStatus("offline");
        // espera crescente até 30 s; enquanto isso, as telas seguem no polling
        const wait = Math.min(30_000, retryMs * 2 ** attempt++);
        await new Promise((r) => setTimeout(r, wait));
        setStatus("connecting");
      }
    })();
    return () => abort.abort();
  }, [qc, retryMs]);

  return <LiveContext.Provider value={{ status, fresh }}>{children}</LiveContext.Provider>;
}

export function LiveIndicator() {
  const { status } = useLive();
  const label = { live: "Ao vivo", connecting: "Conectando…", offline: "Sem tempo real (atualiza a cada 30 s)" }[status];
  const dot = { live: "bg-emerald-500", connecting: "bg-amber-400", offline: "bg-slate-400" }[status];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-slate-600" role="status" aria-live="polite">
      <span className={`size-2 rounded-full ${dot} ${status === "live" ? "animate-pulse" : ""}`} aria-hidden />
      {label}
    </span>
  );
}
