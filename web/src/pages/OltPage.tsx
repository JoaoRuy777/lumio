import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { api, query, type Alarm, type Olt, type Page, type Pon } from "../api";
import { AlarmTable } from "../components/AlarmTable";
import { Card, Loading, StatusBadge, td, th } from "../components/ui";
import { ago, dbm, RX_LIMIT_DBM } from "../format";

export function OltPage() {
  const { id } = useParams();
  const olt = useQuery({ queryKey: ["olts", id], queryFn: () => api<Olt>(`/olts/${id}`), refetchInterval: 30_000 });
  const pons = useQuery({ queryKey: ["pons", id], queryFn: () => api<Pon[]>(`/olts/${id}/pons`), refetchInterval: 30_000 });
  const alarms = useQuery({
    queryKey: ["alarms", "olt", id],
    queryFn: () => api<Page<Alarm>>(`/alarms${query({ olt_id: id })}`),
    refetchInterval: 30_000,
  });

  if (olt.isPending) return <Loading rows={5} />;
  if (olt.error)
    return (
      <p role="alert" className="text-sm text-red-700">
        OLT não encontrada.
      </p>
    );
  const o = olt.data;
  const vendor = o.vendor ? `${o.vendor[0].toUpperCase()}${o.vendor.slice(1)} ${o.model ?? ""}` : "fabricante não identificado";

  return (
    <div className="space-y-6">
      <div>
        <Link to="/olts" className="text-sm text-slate-500 hover:underline">
          ← OLTs
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-bold tracking-tight">{o.name}</h1>
          <StatusBadge status={o.collection_status} />
        </div>
        <p className="text-sm text-slate-600">
          {vendor} ·{" "}
          <span className="font-mono text-xs">
            {o.host}:{o.snmp_port}
          </span>{" "}
          · última coleta {ago(o.last_poll_at)}
        </p>
        {o.last_error && o.collection_status !== "ok" && <p className="mt-1 text-sm text-red-700">{o.last_error}</p>}
      </div>

      <Card title="Alarmes abertos">{alarms.data && <AlarmTable alarms={alarms.data.items} />}</Card>

      <Card title={`Portas PON (${pons.data?.length ?? "…"})`}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                <th className={th}>PON</th>
                <th className={`${th} text-right`}>ONUs online</th>
                <th className={`${th} text-right`}>RX médio</th>
                <th className={`${th} text-right`}>Pior RX</th>
                <th className={`${th} text-right`}>Alarmes</th>
                <th className={th} aria-label="Ações" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {pons.data?.map((p) => {
                const down = p.onus_total > 0 && p.onus_online === 0;
                return (
                  <tr key={p.id}>
                    <td className={`${td} font-medium`}>{p.name}</td>
                    <td className={`${td} text-right tabular-nums ${down ? "font-medium text-red-700" : ""}`}>
                      {p.onus_online} / {p.onus_total}
                    </td>
                    <td className={`${td} text-right tabular-nums`}>{dbm(p.rx_avg)}</td>
                    <td
                      className={`${td} text-right tabular-nums ${p.rx_min !== null && p.rx_min < RX_LIMIT_DBM ? "font-medium text-red-700" : ""}`}
                    >
                      {dbm(p.rx_min)}
                    </td>
                    <td className={`${td} text-right tabular-nums ${p.active_alarms ? "font-medium text-red-700" : "text-slate-400"}`}>
                      {p.active_alarms}
                    </td>
                    <td className={`${td} text-right`}>
                      <Link to={`/onus${query({ olt_id: o.id, pon_id: p.id })}`} className="text-sm text-brand-600 hover:underline">
                        ver ONUs
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
