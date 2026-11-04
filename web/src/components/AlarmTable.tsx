import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Link } from "react-router";
import { api, ApiError, query, type Alarm, type Page } from "../api";
import { ago, dateTime, dbm, duration, kindLabel, location, stopwatch } from "../format";
import { useNow } from "../useNow";
import { useLive } from "../live";
import { AlarmStatusBadge, Button, SeverityBadge, td, th } from "./ui";

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
    <ul className="grid gap-x-6 gap-y-1 px-4 py-3 text-sm sm:grid-cols-2 lg:grid-cols-4" aria-label={`ONUs afetadas por ${kindLabel[parent.kind]}`}>
      {[...(data?.items ?? [])].sort((x, y) => (x.onu_index ?? 0) - (y.onu_index ?? 0)).map((c) => (
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
  );
}

export function AlarmTable({ alarms, history = false, compact = false, emptyText }: { alarms: Alarm[]; history?: boolean; compact?: boolean; emptyText?: string }) {
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
              <tr className={fresh.has(a.id) && a.status === "active" ? "bg-red-50/60" : undefined} data-alarm-id={a.id}>
                <td className={td}>
                  <SeverityBadge severity={a.severity} />
                </td>
                <td className={td}>
                  <p className="font-medium">
                    <Link to={`/alarms/${a.id}`} className="hover:underline">
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
                  <td className={`${td} tabular-nums`}>
                    {history ? duration(a.created_at, a.cleared_at) : `${a.occurrences}×`}
                  </td>
                )}
                <td className={td}>
                  <AlarmStatusBadge status={a.status} />
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
                        <Link to={`/alarms/${a.id}`} className="text-sm font-medium text-brand-600 hover:underline">
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
