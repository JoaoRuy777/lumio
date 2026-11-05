import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { api, type Customer, type CustomerState, type MapData } from "../api";
import { Card, Loading } from "../components/ui";
import { NetworkMap, type FocusTarget } from "../components/NetworkMap";
import { STATE_COLOR, STATE_LABEL } from "../mapStates";

const STATES: CustomerState[] = ["offline", "low", "trend", "online", "unknown"];

export function MapPage() {
  const navigate = useNavigate();
  const [visible, setVisible] = useState<Set<CustomerState>>(new Set(STATES));
  const [focus, setFocus] = useState<FocusTarget | null>(null);
  const { data, isPending, error } = useQuery({ queryKey: ["map"], queryFn: () => api<MapData>("/map"), refetchInterval: 20_000 });

  const counts = useMemo(() => {
    const c = Object.fromEntries(STATES.map((s) => [s, 0])) as Record<CustomerState, number>;
    for (const x of data?.customers ?? []) c[x.state] += 1;
    return c;
  }, [data]);
  // sem serviço, agrupados pelo chamado (um rompimento = um grupo)
  const down = useMemo(() => {
    const groups = new Map<string, Customer[]>();
    for (const c of data?.customers ?? []) {
      if (c.state !== "offline") continue;
      const key = c.ticket_id ?? `${c.olt_name} ${c.pon}`;
      groups.set(key, [...(groups.get(key) ?? []), c]);
    }
    return [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [data]);
  const risky = (data?.customers ?? []).filter((c) => c.state === "trend" || c.state === "low");

  const toggle = (s: CustomerState) =>
    setVisible((v) => {
      const n = new Set(v);
      if (n.has(s)) n.delete(s);
      else n.add(s);
      return n;
    });
  const go = (c: Customer) => c.lat !== null && c.lon !== null && setFocus({ lat: c.lat, lon: c.lon, key: Date.now() });

  if (isPending) return <Loading rows={6} />;
  if (error || !data)
    return (
      <p role="alert" className="text-sm text-red-700">
        Erro ao carregar o mapa.
      </p>
    );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-slate-500">Monitoramento</p>
          <h1 className="text-2xl font-bold tracking-tight">Mapa da rede</h1>
          <p className="text-sm text-slate-500">
            {data.customers.length} clientes no mapa · {data.olts.length} OLTs · atualiza sozinho
          </p>
        </div>
        <Link to="/clientes" className="text-sm font-medium text-brand-600 hover:underline">
          Clientes e importação →
        </Link>
      </div>

      {data.customers.length === 0 ? (
        <Card>
          <p className="px-4 py-10 text-center text-sm text-slate-500">
            Nenhum cliente com localização. Importe a base de clientes (CSV com latitude e longitude) em{" "}
            <Link to="/clientes" className="font-medium text-brand-600 hover:underline">
              Clientes
            </Link>
            .
          </p>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
          <NetworkMap data={data} visible={visible} focus={focus} onNavigate={navigate} className="h-[calc(100vh-260px)] min-h-[440px]" />

          <div className="space-y-4">
            <Card title="Legenda">
              <ul className="space-y-1 p-3 text-sm">
                {STATES.map((s) => (
                  <li key={s}>
                    <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-slate-50">
                      <input type="checkbox" checked={visible.has(s)} onChange={() => toggle(s)} />
                      <span className="size-3 rounded-full ring-2 ring-white" style={{ background: STATE_COLOR[s] }} aria-hidden />
                      <span className="flex-1">{STATE_LABEL[s]}</span>
                      <span className="tabular-nums text-slate-500">{counts[s]}</span>
                    </label>
                  </li>
                ))}
                <li className="flex items-center gap-2 px-1 pt-1 text-slate-500">
                  <span className="ml-5 size-3 rounded-sm bg-brand-600" aria-hidden /> OLT
                </li>
              </ul>
            </Card>

            <Card title={`Sem serviço (${counts.offline})`}>
              {down.length === 0 ? (
                <p className="px-4 py-4 text-sm text-slate-500">Todos os clientes com serviço.</p>
              ) : (
                <div className="max-h-80 divide-y divide-slate-100 overflow-y-auto">
                  {down.map(([key, list]) => (
                    <div key={key} className="px-3 py-2">
                      <p className="flex items-center justify-between gap-2 text-xs font-medium text-slate-500">
                        <span>
                          {list[0].olt_name} · PON {list[0].pon} · {list.length} {list.length === 1 ? "cliente" : "clientes"}
                        </span>
                        {list[0].ticket_id && (
                          <Link to={`/alarms/${list[0].ticket_id}`} className="text-brand-600 hover:underline">
                            chamado
                          </Link>
                        )}
                      </p>
                      <ul className="mt-1 space-y-0.5 text-sm">
                        {list.map((c) => (
                          <li key={c.id}>
                            <button className="w-full text-left hover:underline" onClick={() => go(c)}>
                              {c.name}
                              {c.phone && <span className="text-xs text-slate-500"> · {c.phone}</span>}
                            </button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {risky.length > 0 && (
              <Card title={`Sinal em atenção (${risky.length})`}>
                <ul className="max-h-48 divide-y divide-slate-100 overflow-y-auto text-sm">
                  {risky.map((c) => (
                    <li key={c.id} className="px-3 py-1.5">
                      <button className="flex w-full items-center gap-2 text-left hover:underline" onClick={() => go(c)}>
                        <span className="size-2 shrink-0 rounded-full" style={{ background: STATE_COLOR[c.state] }} aria-hidden />
                        <span className="flex-1 truncate">{c.name}</span>
                        <span className="text-xs text-slate-500">{STATE_LABEL[c.state]}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
