import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState, type MouseEvent } from "react";
import { Link } from "react-router";
import { api, ApiError, query, type Alarm, type Page, type Severity } from "../api";
import { ago, dateTime, dbm, duration, kindLabel, location, stopwatch } from "../format";
import { useNow } from "../useNow";
import { useLive } from "../live";
import { AlarmStatusBadge, Button, SeverityBadge, td, th } from "./ui";

// faixa colorida no começo da linha: a severidade se lê de longe (com o texto ao lado)
const STRIPE: Record<Severity, string> = {
  critical: "shadow-[inset_4px_0_0_#dc2626]",
  major: "shadow-[inset_4px_0_0_#ea580c]",
  minor: "shadow-[inset_4px_0_0_#eab308]",
  warning: "shadow-[inset_4px_0_0_#94a3b8]",
};

/** Tela larga o bastante para a lista e o chamado lado a lado. */
const wide = () => typeof window.matchMedia === "function" && window.matchMedia("(min-width: 1280px)").matches;

function Detail({ alarm }: { alarm: Alarm }) {
  const rx = alarm.details.rx_dbm;
  const cpu = alarm.details.cpu;
  if (typeof rx === "number") return <span className="text-slate-500"> · {dbm(rx)}</span>;
  if (typeof cpu === "number") return <span className="text-slate-500"> · CPU {cpu}%</span>;
  return null;
}

/** Quem está com o chamado e há quanto tempo (cronômetro ao vivo). */
export function Attendance({ alarm: a, now }: { alarm: Alarm; now: number }) {
  if (a.work_closed_at) {
    return (
      <p className="mt-1 text-xs text-slate-500">
        Atendido por {a.work_closed_by ?? "—"}
        {a.first_assigned_at && <> em {stopwatch(a.first_assigned_at, a.work_closed_at)}</>}
      </p>
    );
  }
  if (a.assigned_to && a.first_assigned_at) {
    return (
      <p className="mt-1 text-xs text-slate-600">
        Com <span className="font-medium">{a.assigned_to}</span> ·{" "}
        <span className="font-mono tabular-nums" title="tempo em atendimento">
          {stopwatch(a.first_assigned_at, null, now)}
        </span>
      </p>
    );
  }
  if (!a.parent_id && a.status !== "cleared") {
    return (
      <p className="mt-1 text-xs text-amber-700">
        Aguardando há <span className="font-mono tabular-nums">{stopwatch(a.created_at, null, now)}</span>
      </p>
    );
  }
  return null;
}

export function Children({ parent }: { parent: Alarm }) {
  const { data, isPending } = useQuery({
    queryKey: ["alarms", "children", parent.id],
    queryFn: () => api<Page<Alarm>>(`/alarms${query({ parent_id: parent.id, status: "all", limit: 200 })}`),
  });
  if (isPending) return <p className="px-4 py-2 text-sm text-slate-500">Carregando ONUs…</p>;
  return (
    <div className="@container">
      <ul
        className="grid gap-x-6 gap-y-1 px-4 py-3 text-sm @md:grid-cols-2 @4xl:grid-cols-4"
        aria-label={`ONUs afetadas por ${kindLabel[parent.kind]}`}
      >
        {[...(data?.items ?? [])]
          .sort((x, y) => (x.onu_index ?? 0) - (y.onu_index ?? 0))
          .map((c) => (
            <li key={c.id} className="flex items-center gap-2">
              <span className={`size-1.5 rounded-full ${c.status === "cleared" ? "bg-emerald-500" : "bg-red-500"}`} aria-hidden />
              {c.onu_id ? (
                <Link className="hover:underline" to={`/onus/${c.onu_id}`}>
                  ONU {c.onu_index}
                </Link>
              ) : (
                <span>ONU {c.onu_index}</span>
              )}
              <span className="font-mono text-xs text-slate-500">{c.onu_serial}</span>
              {c.customer_name && <span className="truncate text-xs text-slate-600">{c.customer_name}</span>}
              {c.status === "cleared" && <span className="text-xs text-emerald-700">voltou</span>}
            </li>
          ))}
      </ul>
    </div>
  );
}

export function AlarmTable({
  alarms,
  history = false,
  compact = false,
  emptyText,
  selectedId,
  onSelect,
}: {
  alarms: Alarm[];
  history?: boolean;
  compact?: boolean;
  emptyText?: string;
  /** chamado aberto no painel ao lado (destaca a linha) */
  selectedId?: string | null;
  /** em tela larga, abrir o chamado no painel em vez de trocar de página */
  onSelect?: (a: Alarm) => void;
}) {
  const qc = useQueryClient();
  const { fresh } = useLive();
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const now = useNow();
  const assume = useMutation({
    mutationFn: (a: Alarm) => api<Alarm>(`/alarms/${a.id}/assign`, { method: "POST", body: {} }),
    onSuccess: () => {
      setError(null);
      qc.invalidateQueries({ queryKey: ["alarms"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "não foi possível assumir"),
  });

  if (alarms.length === 0) {
    return (
      <p className="px-4 py-10 text-center text-sm text-slate-500">
        {emptyText ?? (history ? "Nenhum alarme no período." : "Nenhum alarme aberto. Rede normal.")}
      </p>
    );
  }

  const toggle = (id: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const cols = compact ? 4 : 6;
  const openTicket = (a: Alarm) => (e: MouseEvent) => {
    if (!onSelect || a.parent_id || e.ctrlKey || e.metaKey || e.shiftKey || !wide()) return;
    e.preventDefault();
    onSelect(a);
  };

  return (
    <div className="overflow-x-auto">
      {error && (
        <p role="alert" className="m-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}
      <table className="w-full text-sm">
        <thead className="border-b border-slate-200 bg-slate-50">
          <tr>
            <th className={th}>Severidade</th>
            <th className={th}>Alarme</th>
            <th className={th}>{history ? "Início" : "Desde"}</th>
            {!compact && <th className={th}>{history ? "Duração" : "Ocorrências"}</th>}
            <th className={th}>Situação</th>
            {!compact && <th className={th} aria-label="Ações" />}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {alarms.map((a) => (
            <Fragment key={a.id}>
              <tr
                className={`transition-colors ${a.id === selectedId ? "bg-brand-50" : fresh.has(a.id) && a.status === "active" ? "bg-red-50/60" : "hover:bg-slate-50"}`}
                data-alarm-id={a.id}
                aria-current={a.id === selectedId ? "true" : undefined}
              >
                <td className={`${td} ${a.status === "cleared" ? "" : STRIPE[a.severity]}`}>
                  <SeverityBadge severity={a.severity} />
                </td>
                <td className={td}>
                  <p className="font-medium">
                    <Link to={`/alarms/${a.id}`} className="hover:underline" onClick={openTicket(a)}>
                      {kindLabel[a.kind]}
                    </Link>
                    <Detail alarm={a} />
                    {fresh.has(a.id) && a.status === "active" && (
                      <span className="ml-2 rounded bg-red-600 px-1.5 py-0.5 text-[10px] font-semibold text-white uppercase">novo</span>
                    )}
                  </p>
                  <p className="text-xs text-slate-500">{location(a)}</p>
                  {a.children > 0 && (
                    <button
                      className="mt-1 text-xs font-medium text-brand-600 hover:underline"
                      aria-expanded={open.has(a.id)}
                      onClick={() => toggle(a.id)}
                    >
                      {open.has(a.id) ? "Ocultar" : "Ver"} {a.children} ONUs afetadas
                    </button>
                  )}
                </td>
                <td className={`${td} whitespace-nowrap`} title={dateTime(a.created_at)}>
                  {history ? dateTime(a.created_at) : ago(a.created_at)}
                </td>
                {!compact && (
                  <td className={`${td} tabular-nums`}>{history ? duration(a.created_at, a.cleared_at) : `${a.occurrences}×`}</td>
                )}
                <td className={td}>
                  <AlarmStatusBadge status={a.status} />
                  {a.escalated_at && !a.assigned_to && a.status !== "cleared" && (
                    <span
                      className="ml-1.5 inline-flex rounded-full bg-orange-50 px-2 py-0.5 text-xs font-medium text-orange-800 ring-1 ring-orange-600/20 ring-inset"
                      title="Ninguém assumiu a tempo: o aviso foi escalado"
                    >
                      Escalonado
                    </span>
                  )}
                  {a.maintenance_id && (
                    <span
                      className="ml-1.5 inline-flex rounded-full bg-sky-50 px-2 py-0.5 text-xs font-medium text-sky-800 ring-1 ring-sky-600/20 ring-inset"
                      title={`Manutenção programada: ${a.maintenance_reason ?? ""} (sem aviso por e-mail)`}
                    >
                      Manutenção
                    </span>
                  )}
                  <Attendance alarm={a} now={now} />
                </td>
                {!compact && (
                  <td className={`${td} text-right whitespace-nowrap`}>
                    {!a.parent_id && !a.assigned_to && !a.work_closed_at && a.status !== "cleared" ? (
                      <Button variant="secondary" disabled={assume.isPending} onClick={() => assume.mutate(a)}>
                        Assumir
                      </Button>
                    ) : (
                      !a.parent_id && (
                        <Link to={`/alarms/${a.id}`} className="text-sm font-medium text-brand-600 hover:underline" onClick={openTicket(a)}>
                          Abrir chamado
                        </Link>
                      )
                    )}
                  </td>
                )}
              </tr>
              {open.has(a.id) && (
                <tr className="bg-slate-50">
                  <td colSpan={cols}>
                    <Children parent={a} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
