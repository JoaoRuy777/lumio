import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { api, query, type Alarm, type Onu, type Page, type Readings } from "../api";
import { AlarmTable } from "../components/AlarmTable";
import { RxChart } from "../components/RxChart";
import { Card } from "../components/ui";
import { ago, dateTime, dbm } from "../format";
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
    queryFn: () => api<Page<Alarm>>(`/alarms${query({ onu_id: id, status: "all", limit: 20 })}`),
  });

  if (onu.isPending) return <p className="text-sm text-slate-500">Carregando…</p>;
  if (onu.error) return <p role="alert" className="text-sm text-red-700">ONU não encontrada.</p>;
  const o = onu.data;

  return (
    <div className="space-y-6">
      <div>
        <Link to="/onus" className="text-sm text-slate-500 hover:underline">
          ← ONUs
        </Link>
        <h1 className="mt-1 font-mono text-2xl font-semibold tracking-tight">{o.serial ?? "ONU sem serial"}</h1>
        <p className="text-sm text-slate-600">
          <Link className="hover:underline" to={`/olts/${o.olt_id}`}>
            {o.olt_name}
          </Link>{" "}
          · PON {o.pon} · ONU {o.onu_index}
        </p>
      </div>

      <dl className="grid gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:grid-cols-4">
        <div>
          <dt className="text-sm text-slate-500">Situação</dt>
          <dd className="mt-1">
            <OnuState online={o.online} />
          </dd>
        </div>
        <div>
          <dt className="text-sm text-slate-500">RX agora</dt>
          <dd className="mt-1 text-lg font-semibold tabular-nums">{o.online ? dbm(o.rx_dbm) : "—"}</dd>
        </div>
        <div>
          <dt className="text-sm text-slate-500">TX agora</dt>
          <dd className="mt-1 text-lg font-semibold tabular-nums">{o.online ? dbm(o.tx_dbm) : "—"}</dd>
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
                className={`rounded-md px-2.5 py-1 text-xs font-medium ${hours === r.hours ? "bg-slate-800 text-white" : "text-slate-600"}`}
                onClick={() => setHours(r.hours)}
              >
                {r.label}
              </button>
            ))}
          </div>
        }
      >
        {readings.data ? <RxChart readings={readings.data} hours={hours} /> : <p className="p-6 text-sm text-slate-500">Carregando…</p>}
      </Card>

      <Card title="Alarmes desta ONU">{alarms.data && <AlarmTable alarms={alarms.data.items} history />}</Card>
    </div>
  );
}
