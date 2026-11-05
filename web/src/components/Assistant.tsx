import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useLocation } from "react-router";
import { api, ApiError, type AssistantReply, type AssistantStatus } from "../api";
import { Icon } from "./icons";

type Message = { role: "user" | "model"; text: string; tools?: string[] };

const TOOL_LABEL: Record<string, string> = {
  resumo_rede: "resumo da rede",
  listar_alarmes: "alarmes",
  detalhar_chamado: "chamado",
  buscar_clientes: "clientes",
  sinal_onu: "sinal da ONU",
  status_olts: "OLTs",
  relatorio_atendimento: "atendimento",
  manutencoes: "manutenções",
};

/** Negrito, `código` e quebra de linha, sem HTML vindo de fora (só texto do React). */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i}>{part.slice(2, -2)}</strong>
    ) : part.startsWith("`") && part.endsWith("`") ? (
      <code key={i} className="rounded bg-slate-100 px-1 font-mono text-[0.85em]">
        {part.slice(1, -1)}
      </code>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  );
}

/** Markdown simples da resposta: parágrafos, listas e títulos. */
export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      blocks.push(
        <ul key={blocks.length} className="ml-4 list-disc space-y-1">
          {list.map((li, i) => (
            <li key={i}>{inline(li)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const item = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
    if (item) {
      list.push(item[1]);
      continue;
    }
    flush();
    if (!line.trim()) continue;
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      blocks.push(<hr key={blocks.length} className="border-slate-300" />);
      continue;
    }
    const quote = line.match(/^>\s?(.*)$/);
    if (quote) {
      blocks.push(
        <blockquote key={blocks.length} className="border-l-2 border-brand-500 pl-3 text-slate-700 italic">
          {inline(quote[1])}
        </blockquote>,
      );
      continue;
    }
    const heading = line.match(/^#{1,4}\s+(.*)$/);
    blocks.push(
      <p key={blocks.length} className={heading ? "font-semibold" : undefined}>
        {inline(heading ? heading[1] : line)}
      </p>,
    );
  }
  flush();
  return <div className="space-y-2">{blocks}</div>;
}

function alarmFromLocation(pathname: string, search: string): string | null {
  const m = pathname.match(/^\/alarms\/([0-9a-f-]{36})/);
  if (m) return m[1];
  return new URLSearchParams(search).get("chamado");
}

/** Botão do topo + painel lateral de conversa com o assistente de IA. */
export function Assistant() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const location = useLocation();
  const alarmId = alarmFromLocation(location.pathname, location.search);
  const qc = useQueryClient();
  const end = useRef<HTMLDivElement>(null);
  const { data: status } = useQuery({
    queryKey: ["assistant", "status"],
    queryFn: () => api<AssistantStatus>("/assistant/status"),
    enabled: open,
  });

  useEffect(() => {
    if (open) end.current?.scrollIntoView?.({ block: "end" });
  }, [messages, busy, open]);
  useEffect(() => {
    if (!busy) return;
    setElapsed(0);
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [busy]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  async function send(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    const history = [...messages, { role: "user" as const, text: q }];
    setMessages(history);
    setInput("");
    setError(null);
    setBusy(true);
    try {
      const out = await api<AssistantReply>("/assistant/chat", {
        method: "POST",
        body: { messages: history.map(({ role, text }) => ({ role, text })), mapping, alarm_id: alarmId },
      });
      setMapping(out.mapping);
      setMessages([...history, { role: "model", text: out.reply, tools: out.tools }]);
      qc.setQueryData<AssistantStatus>(["assistant", "status"], (s) => (s ? { ...s, remaining_today: out.remaining_today } : s));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "não foi possível falar com o assistente");
      setMessages(history.slice(0, -1));
      setInput(q);
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    send(input);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  }

  const suggestions = [
    ...(alarmId ? ["Resuma este chamado e diga o próximo passo."] : []),
    "O que está crítico agora e por onde eu começo?",
    "Quais clientes estão sem serviço?",
    "Como foi o atendimento hoje?",
    "Escreva uma mensagem para avisar os clientes afetados.",
  ];

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-lg border border-brand-500/40 bg-brand-50 px-2.5 py-1.5 text-sm font-semibold text-brand-700 hover:bg-brand-100"
        aria-label="Abrir assistente de IA"
      >
        <Icon name="sparkles" className="size-4" />
        <span className="hidden sm:inline">Assistente</span>
      </button>

      {/* portal: fora da barra do topo (o backdrop-blur dela prenderia o "fixed" do painel) */}
      {createPortal(
        <>
          {open && <div className="fixed inset-0 z-40 bg-black/30" onClick={() => setOpen(false)} aria-hidden />}
          <aside
            role="dialog"
            aria-label="Assistente de IA"
            aria-hidden={!open}
            className={`fixed inset-y-0 right-0 z-50 flex w-full max-w-[440px] flex-col border-l border-slate-200 bg-surface shadow-2xl transition-transform ${
              open ? "translate-x-0" : "invisible translate-x-full"
            }`}
          >
            <header className="flex items-center gap-3 border-b border-slate-200 px-4 py-3">
              <span className="flex size-8 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
                <Icon name="sparkles" className="size-4" />
              </span>
              <div className="flex-1 leading-tight">
                <p className="font-semibold">Assistente Lumio</p>
                <p className="text-xs text-slate-500">
                  IA · {status?.provider ?? "…"}
                  {status && ` · ${status.remaining_today} de ${status.daily_limit} perguntas hoje`}
                </p>
              </div>
              {messages.length > 0 && (
                <button
                  className="rounded-md px-2 py-1 text-xs text-slate-500 hover:bg-slate-100"
                  onClick={() => {
                    setMessages([]);
                    setMapping({});
                    setError(null);
                  }}
                >
                  Nova conversa
                </button>
              )}
              <button
                className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100"
                onClick={() => setOpen(false)}
                aria-label="Fechar assistente"
              >
                <Icon name="close" className="size-4" />
              </button>
            </header>

            <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4 text-sm" aria-live="polite">
              {status && !status.configured ? (
                <p className="rounded-lg bg-amber-50 px-3 py-2 text-amber-800">
                  O assistente ainda não foi ligado neste ambiente (falta a chave GEMINI_API_KEY no servidor).
                </p>
              ) : messages.length === 0 ? (
                <div className="space-y-3">
                  <p className="text-slate-600">
                    Pergunte sobre alarmes, clientes, sinal das ONUs, OLTs ou o atendimento. Eu consulto os dados da sua rede na hora.
                    {alarmId && " Estou vendo o chamado aberto na tela."}
                  </p>
                  <div className="flex flex-col gap-2">
                    {suggestions.map((s) => (
                      <button
                        key={s}
                        className="rounded-lg border border-slate-200 px-3 py-2 text-left text-slate-700 hover:border-brand-500 hover:bg-brand-50"
                        onClick={() => send(s)}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                messages.map((m, i) =>
                  m.role === "user" ? (
                    <div key={i} className="ml-8 rounded-2xl rounded-br-md bg-brand-600 px-3.5 py-2.5 whitespace-pre-wrap text-white">
                      {m.text}
                    </div>
                  ) : (
                    <div key={i} className="mr-4 space-y-1.5">
                      <div className="rounded-2xl rounded-bl-md bg-slate-100 px-3.5 py-2.5 text-slate-800">
                        <Markdown text={m.text} />
                      </div>
                      {!!m.tools?.length && (
                        <p className="px-1 text-[11px] text-slate-500">
                          Consultei: {[...new Set(m.tools)].map((t) => TOOL_LABEL[t] ?? t).join(", ")}
                        </p>
                      )}
                    </div>
                  ),
                )
              )}
              {busy && (
                <div
                  className="mr-4 flex items-center gap-2 rounded-2xl rounded-bl-md bg-slate-100 px-3.5 py-2.5 text-slate-600"
                  role="status"
                >
                  <span className="flex gap-1" aria-hidden>
                    <span className="size-1.5 animate-bounce rounded-full bg-slate-400" />
                    <span className="size-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:150ms]" />
                    <span className="size-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:300ms]" />
                  </span>
                  Consultando a rede… {elapsed > 3 && <span className="text-xs text-slate-500">{elapsed} s</span>}
                </div>
              )}
              {error && (
                <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-red-700">
                  {error}
                </p>
              )}
              <div ref={end} />
            </div>

            <form onSubmit={submit} className="border-t border-slate-200 p-3">
              <div className="flex items-end gap-2 rounded-xl border border-slate-300 bg-surface px-3 py-2 focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-500/20">
                <textarea
                  rows={1}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder="Pergunte algo sobre a rede…"
                  aria-label="Pergunta para o assistente"
                  maxLength={2000}
                  disabled={busy || status?.configured === false}
                  className="max-h-32 min-h-6 flex-1 resize-none bg-transparent text-sm outline-none placeholder:text-slate-400"
                />
                <button
                  type="submit"
                  disabled={busy || !input.trim()}
                  className="rounded-lg bg-brand-600 p-2 text-white hover:bg-brand-800 disabled:opacity-40"
                  aria-label="Enviar pergunta"
                >
                  <Icon name="send" className="size-4" />
                </button>
              </div>
              <p className="mt-2 text-[11px] leading-snug text-slate-500">
                Só consulta, não altera nada. Nomes, telefones e endereços de clientes são anonimizados antes de ir para o provedor de IA. A
                IA pode errar: confira antes de agir.
              </p>
            </form>
          </aside>
        </>,
        document.body,
      )}
    </>
  );
}
