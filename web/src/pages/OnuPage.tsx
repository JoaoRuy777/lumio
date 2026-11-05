import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { api, query, type AtRiskOnu, type Alarm, type Customer, type Onu, type Page, type Readings } from "../api";
import { AlarmTable } from "../components/AlarmTable";
import { RxChart, type Outage } from "../components/RxChart";
import { Card, Loading } from "../components/ui";
import { ago, dateTime, dbm, RX_LIMIT_DBM } from "../format";
import { OnuState } from "./OnusPage";

const RANGES = [
  { hours: 6, label: "6 h" },
  { hours: 24, label: "24 h" },
  { hours: 24 * 7, label: "7 dias" },
  { hours: 24 * 30, label: "30 dias" },
];

export function OnuPage() {
  const { id } = useParams();
  const [hours, setHours] = useState(24);
  const onu = useQuery({ queryKey: ["onu", id], queryFn: () => api<Onu>(`/onus/${id}`), refetchInterval: 30_000 });
  const readings = useQuery({
    queryKey: ["onu", id, "readings", hours],
    queryFn: () => api<Readings>(`/onus/${id}/readings${query({ hours })}`),
    refetchInterval: 60_000,
  });
  const alarms = useQuery({
    queryKey: ["alarms", "onu", id],
    queryFn: () => api<Page<Alarm>>(`/alarms${query({ onu_id: id, status: "all", limit: 100 })}`),
    refetchInterval: 60_000,
  });

  const customer = useQuery({ queryKey: ["customers", "onu", id], queryFn: () => api<Customer | null>(`/onus/${id}/customer`) });
  const risk = useQuery({ queryKey: ["at-risk"], queryFn: () => api<AtRiskOnu[]>("/onus-at-risk"), refetchInterval: 60_000 });
  const trend = risk.data?.find((r) => r.onu_id === id);

  if (onu.isPending) return <Loading rows={5} />;
  if (onu.error)
    return (
      <p role="alert" className="text-sm text-red-700">
        ONU não encontrada.
      </p>
    );
  const o = onu.data;
  const now = Date.now();
  const offline = (alarms.data?.items ?? []).filter((a) => a.kind === "onu_offline");
  const outages: Outage[] = offline.map((a) => ({
    from: new Date(a.created_at).getTime(),
    to: a.cleared_at ? new Date(a.cleared_at).getTime() : now,
  }));
  const drops30d = offline.filter((a) => now - new Date(a.created_at).getTime() < 30 * 86_400_000).length;
  const margin = o.online && o.rx_dbm !== null ? o.rx_dbm - RX_LIMIT_DBM : null;
  const c = customer.data;

  return (
    <div className="space-y-6">
      <div>
        <Link to="/onus" className="text-sm text-slate-500 hover:underline">
          ← ONUs
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="font-mono text-2xl font-bold tracking-tight">{o.serial ?? "ONU sem serial"}</h1>
          <OnuState online={o.online} />
        </div>
        <p className="text-sm text-slate-600">
          <Link className="hover:underline" to={`/olts/${o.olt_id}`}>
            {o.olt_name}
          </Link>{" "}
          · PON {o.pon} · ONU {o.onu_index}
        </p>
      </div>

      {c ? (
        <section className="rounded-xl border border-slate-200 bg-surface p-4" aria-label="Cliente">
          <div className="flex flex-wrap items-start gap-4">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-50 text-sm font-semibold text-brand-700" aria-hidden>
              {c.name
                .split(/\s+/)
                .filter(Boolean)
                .map((p, i, a) => (i === 0 || i === a.length - 1 ? p[0] : ""))
                .join("")
                .toUpperCase()}
            </span>
            <dl className="grid flex-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <dt className="text-xs text-slate-500">Cliente</dt>
                <dd className="font-semibold">{c.name}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">Telefone</dt>
                <dd>{c.phone ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">Endereço</dt>
                <dd>{[c.address, c.district].filter(Boolean).join(" · ") || "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">Plano</dt>
                <dd>
                  {c.plan ?? "—"}
                  {c.code && <span className="text-slate-500"> · {c.code}</span>}
                </dd>
              </div>
            </dl>
            <Link to="/mapa" className="text-xs font-medium text-brand-600 hover:underline">
              ver no mapa
            </Link>
          </div>
        </section>
      ) : (
        customer.data === null && (
          <p className="rounded-xl border border-dashed border-slate-300 px-4 py-3 text-sm text-slate-500">
            Nenhum cliente ligado a esta ONU. Importe a base em{" "}
            <Link to="/clientes" className="font-medium text-brand-600 hover:underline">
              Clientes
            </Link>{" "}
            (o vínculo é pelo serial).
          </p>
        )
      )}
      {trend && (
        <p role="status" className="rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <b>Sinal piorando:</b> {trend.slope_db_day.toLocaleString("pt-BR")} dB por dia nas últimas leituras. Nesse ritmo passa do limite
          de alarme (-27 dBm) em{" "}
          {trend.days_to_limit < 1
            ? `cerca de ${Math.max(1, Math.round(trend.days_to_limit * 24))} h`
            : `cerca de ${Math.round(trend.days_to_limit)} dias`}
          . Vale verificar conectores e o cabo do cliente antes de ele cair.
        </p>
      )}

      <dl className="grid gap-4 rounded-xl border border-slate-200 bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-sm text-slate-500">RX agora</dt>
          <dd className={`mt-1 text-lg font-semibold tabular-nums ${margin !== null && margin < 0 ? "text-red-700" : ""}`}>
            {o.online ? dbm(o.rx_dbm) : "—"}
          </dd>
          {margin !== null && (
            <dd className={`text-xs ${margin < 0 ? "text-red-700" : margin < 3 ? "text-amber-700" : "text-slate-500"}`}>
              {margin < 0
                ? `${Math.abs(margin).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} dB abaixo do limite`
                : `${margin.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} dB de folga até o limite`}
            </dd>
          )}
        </div>
        <div>
          <dt className="text-sm text-slate-500">TX agora</dt>
          <dd className="mt-1 text-lg font-semibold tabular-nums">{o.online ? dbm(o.tx_dbm) : "—"}</dd>
        </div>
        <div>
          <dt className="text-sm text-slate-500">Quedas em 30 dias</dt>
          <dd className={`mt-1 text-lg font-semibold tabular-nums ${drops30d > 2 ? "text-red-700" : ""}`}>{alarms.data ? drops30d : "…"}</dd>
        </div>
        <div>
          <dt className="text-sm text-slate-500">Última mudança</dt>
          <dd className="mt-1 text-sm" title={dateTime(o.last_change_at)}>
            {ago(o.last_change_at)}
          </dd>
        </div>
      </dl>

      <Card
        title="Potência recebida (RX)"
        actions={
          <div className="inline-flex rounded-lg border border-slate-200 p-0.5" role="group" aria-label="Período">
            {RANGES.map((r) => (
              <button
                key={r.hours}
                aria-pressed={hours === r.hours}
                className={`rounded-md px-2.5 py-1 text-xs font-medium ${hours === r.hours ? "bg-brand-600 text-white" : "text-slate-600"}`}
                onClick={() => setHours(r.hours)}
              >
                {r.label}
              </button>
            ))}
          </div>
        }
      >
        {readings.data ? <RxChart readings={readings.data} hours={hours} outages={outages} /> : <Loading rows={6} />}
      </Card>

      <Card title="Alarmes desta ONU">{alarms.data && <AlarmTable alarms={alarms.data.items} history />}</Card>
    </div>
  );
}
