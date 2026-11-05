import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api, query, type OltList, type Onu, type Page } from "../api";
import { Card, EmptyState, inputClass, Loading, Pager, td, th } from "../components/ui";
import { ago, dbm, kindLabel, RX_LIMIT_DBM } from "../format";

const LIMIT = 100;

export function OnuState({ online }: { online: boolean | null }) {
  if (online === null) return <span className="text-xs text-slate-500">aguardando coleta</span>;
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${online ? "text-emerald-700" : "text-red-700"}`}>
      <span className={`size-2 rounded-full ${online ? "bg-emerald-500" : "bg-red-500"}`} aria-hidden />
      {online ? "Online" : "Offline"}
    </span>
  );
}

export function OnusPage() {
  const [params, setParams] = useSearchParams();
  const filters = {
    olt_id: params.get("olt_id"),
    pon_id: params.get("pon_id"),
    status: params.get("status"),
    rx_below: params.get("rx_below"),
    q: params.get("q"),
  };
  const offset = Number(params.get("offset") ?? 0);
  const [search, setSearch] = useState(filters.q ?? "");

  const olts = useQuery({ queryKey: ["olts"], queryFn: () => api<OltList>("/olts") });
  const { data, isPending, error } = useQuery({
    queryKey: ["onus", filters, offset],
    queryFn: () => api<Page<Onu>>(`/onus${query({ ...filters, limit: LIMIT, offset })}`),
    refetchInterval: 30_000,
  });

  function update(key: string, value: string | null) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "offset") next.delete("offset");
    if (key === "olt_id") next.delete("pon_id");
    setParams(next);
  }

  // busca por serial: espera parar de digitar
  useEffect(() => {
    const t = setTimeout(() => {
      if ((filters.q ?? "") !== search) update("q", search.trim() || null);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-slate-500">Rede</p>
        <h1 className="text-2xl font-bold tracking-tight">ONUs</h1>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="mb-1 block text-slate-600">OLT</span>
          <select className={inputClass} value={filters.olt_id ?? ""} onChange={(e) => update("olt_id", e.target.value || null)}>
            <option value="">Todas</option>
            {olts.data?.items.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-slate-600">Situação</span>
          <select className={inputClass} value={filters.status ?? ""} onChange={(e) => update("status", e.target.value || null)}>
            <option value="">Todas</option>
            <option value="offline">Offline</option>
            <option value="online">Online</option>
            <option value="unknown">Aguardando coleta</option>
          </select>
        </label>
        <label className="flex items-center gap-2 pb-2 text-sm">
          <input
            type="checkbox"
            checked={filters.rx_below !== null}
            onChange={(e) => update("rx_below", e.target.checked ? String(RX_LIMIT_DBM) : null)}
          />
          Só sinal abaixo de {RX_LIMIT_DBM} dBm
        </label>
        <label className="ml-auto text-sm">
          <span className="mb-1 block text-slate-600">Serial</span>
          <input
            className={inputClass}
            type="search"
            placeholder="buscar serial"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
      </div>

      <Card>
        {isPending ? (
          <Loading rows={6} />
        ) : error ? (
          <p role="alert" className="p-6 text-sm text-red-700">
            Erro ao carregar ONUs: {error.message}
          </p>
        ) : data.items.length === 0 ? (
          <EmptyState icon="search" title="Nenhuma ONU com esses filtros." text="Tente limpar os filtros ou buscar pelo serial completo." />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-slate-200 bg-slate-50">
                  <tr>
                    <th className={th}>Serial</th>
                    <th className={th}>Local</th>
                    <th className={th}>Situação</th>
                    <th className={`${th} text-right`}>RX</th>
                    <th className={`${th} text-right`}>TX</th>
                    <th className={th}>Última mudança</th>
                    <th className={th}>Alarmes</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.items.map((o) => (
                    <tr key={o.id} className="hover:bg-slate-50">
                      <td className={td}>
                        <Link to={`/onus/${o.id}`} className="font-mono text-xs font-medium text-brand-700 hover:underline">
                          {o.serial ?? "—"}
                        </Link>
                      </td>
                      <td className={`${td} whitespace-nowrap`}>
                        {o.olt_name} · {o.pon} · {o.onu_index}
                      </td>
                      <td className={td}>
                        <OnuState online={o.online} />
                      </td>
                      <td
                        className={`${td} text-right tabular-nums ${o.rx_dbm !== null && o.rx_dbm < RX_LIMIT_DBM ? "font-medium text-red-700" : ""}`}
                      >
                        {o.online ? dbm(o.rx_dbm) : "—"}
                      </td>
                      <td className={`${td} text-right tabular-nums`}>{o.online ? dbm(o.tx_dbm) : "—"}</td>
                      <td className={`${td} whitespace-nowrap text-slate-600`}>{ago(o.last_change_at)}</td>
                      <td className={`${td} text-xs`}>
                        {o.active_alarms.map((k) => kindLabel[k]).join(", ") || <span className="text-slate-400">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={data.total} limit={LIMIT} offset={offset} onChange={(o) => update("offset", String(o))} />
          </>
        )}
      </Card>
    </div>
  );
}
