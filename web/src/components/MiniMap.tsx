import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { api, type CustomerState, type MapData } from "../api";
import { NetworkMap } from "./NetworkMap";
import { STATE_COLOR } from "../mapStates";

const ALL: Set<CustomerState> = new Set(["online", "trend", "low", "offline", "unknown"]);

/** Mapa compacto da visão geral (carregado à parte: traz o Leaflet). */
export function MiniMap() {
  const navigate = useNavigate();
  const { data, error } = useQuery({ queryKey: ["map"], queryFn: () => api<MapData>("/map"), refetchInterval: 30_000 });
  if (error) return <p className="p-4 text-sm text-slate-500">Mapa indisponível agora.</p>;
  if (!data) return <div className="h-full min-h-72 animate-pulse bg-slate-100" aria-hidden />;
  if (!data.customers.length) {
    return (
      <div className="flex h-full min-h-72 flex-col items-center justify-center gap-2 p-6 text-center text-sm text-slate-500">
        <p>Importe a base de clientes para ver a rede no mapa.</p>
        <a href="/clientes" className="font-medium text-brand-600 hover:underline" onClick={(e) => (e.preventDefault(), navigate("/clientes"))}>
          Importar clientes
        </a>
      </div>
    );
  }
  return (
    <div className="relative h-full">
      <NetworkMap data={data} visible={ALL} onNavigate={navigate} className="h-full min-h-72" bare />
      <div className="pointer-events-none absolute top-3 right-3 z-[400] flex gap-3 rounded-md border border-slate-200 bg-surface/95 px-2.5 py-1.5 text-xs text-slate-600 shadow-sm">
        {(
          [
            ["online", "Online"],
            ["offline", "Sem serviço"],
            ["low", "Sinal baixo"],
          ] as const
        ).map(([s, label]) => (
          <span key={s} className="inline-flex items-center gap-1.5">
            <span className="size-2 rounded-full" style={{ background: STATE_COLOR[s] }} aria-hidden />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}
