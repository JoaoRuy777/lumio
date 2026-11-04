import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api, type OltList, type Overview, type Severity } from "../api";
import { AlarmTable } from "../components/AlarmTable";
import { Card, SeverityIcon, StatTile, StatusBadge } from "../components/ui";
import { RX_LIMIT_DBM, severityLabel } from "../format";

const SEVERITIES: Severity[] = ["critical", "major", "minor", "warning"];
const POLL_MS = 30_000; // reserva caso o tempo real caia

export function OverviewPage() {
  const ov = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/overview"), refetchInterval: POLL_MS });
  const olts = useQuery({ queryKey: ["olts"], queryFn: () => api<OltList>("/olts"), refetchInterval: POLL_MS });

  if (ov.isPending) return <p className="text-sm text-slate-500">Carregando…</p>;
  if (ov.error) return <p role="alert" className="text-sm text-red-700">Erro ao carregar: {ov.error.message}</p>;
  const d = ov.data;

  if (d.olts.total === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center">
        <h1 className="text-lg font-medium">Nenhuma OLT cadastrada ainda</h1>
        <p className="mt-1 text-sm text-slate-500">Cadastre a primeira OLT para a Lumio começar a monitorar a rede.</p>
        <Link to="/olts" className="mt-4 inline-block rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700">
          Cadastrar OLT
        </Link>
      </div>
    );
  }

  const offline = d.onus.offline;
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Visão geral</h1>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Alarmes abertos"
          value={d.alarms.total}
          tone={d.alarms.critical > 0 ? "bad" : "neutral"}
        >
          <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-600">
            {SEVERITIES.map((s) => (
              <li key={s} className="inline-flex items-center gap-1">
                <SeverityIcon severity={s} className="size-2.5" />
                {d.alarms[s]} {severityLabel[s].toLowerCase()}
              </li>
            ))}
          </ul>
        </StatTile>
        <StatTile
          label="ONUs online"
          value={`${d.onus.online} / ${d.onus.total}`}
          tone={offline > 0 ? "bad" : "neutral"}
          detail={offline > 0 ? <Link className="text-red-700 hover:underline" to="/onus?status=offline">{offline} offline</Link> : "todas online"}
        />
        <StatTile
          label={`Sinal abaixo de ${RX_LIMIT_DBM} dBm`}
          value={d.rx_low}
          detail={d.rx_low > 0 ? <Link className="hover:underline" to={`/onus?rx_below=${RX_LIMIT_DBM}`}>ver ONUs</Link> : "nenhuma ONU"}
        />
        <StatTile
          label="OLTs coletando"
          value={`${d.olts.ok} / ${d.olts.total}`}
          tone={d.olts.error > 0 ? "bad" : "neutral"}
          detail={d.olts.error > 0 ? `${d.olts.error} sem resposta` : d.olts.late > 0 ? `${d.olts.late} com coleta atrasada` : "coleta em dia"}
        />
      </div>

      <Card
        title="Alarmes abertos"
        actions={
          <Link to="/alarms" className="text-sm text-brand-600 hover:underline">
            ver todos
          </Link>
        }
      >
        <AlarmTable alarms={d.recent_alarms} compact />
      </Card>

      <Card title="OLTs">
        <ul className="divide-y divide-slate-100">
          {olts.data?.items.map((o) => {
            const pct = o.onus_total ? (o.onus_online / o.onus_total) * 100 : 0;
            return (
              <li key={o.id} className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
                <Link to={`/olts/${o.id}`} className="min-w-40 font-medium hover:underline">
                  {o.name}
                </Link>
                <StatusBadge status={o.collection_status} />
                {/* uma magnitude só: barra de um tom, com o número escrito ao lado */}
                <div className="flex min-w-56 flex-1 items-center gap-3">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-200" aria-hidden>
                    <div className="h-full rounded-full bg-[#2a78d6]" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="text-sm tabular-nums text-slate-600">
                    {o.onus_online}/{o.onus_total} ONUs online
                  </span>
                </div>
                <span className={`text-sm tabular-nums ${o.active_alarms ? "font-medium text-red-700" : "text-slate-400"}`}>
                  {o.active_alarms} alarmes
                </span>
              </li>
            );
          })}
        </ul>
      </Card>
    </div>
  );
}
