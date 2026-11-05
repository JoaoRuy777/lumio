import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api, type MaintenanceWindow } from "../api";
import { Icon } from "./icons";

const time = (iso: string) =>
  new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

export function scope(w: Pick<MaintenanceWindow, "olt_name" | "pon">) {
  return w.pon ? `${w.olt_name} · PON ${w.pon}` : `${w.olt_name} (OLT inteira)`;
}

/** Faixa de aviso quando há manutenção em andamento: os alarmes dali não geram e-mail. */
export function MaintenanceBanner() {
  const { data } = useQuery({
    queryKey: ["maintenance", "current"],
    queryFn: () => api<MaintenanceWindow[]>("/maintenance?current=true"),
    refetchInterval: 60_000,
  });
  if (!data?.length) return null;
  return (
    <div
      role="status"
      className="flex flex-wrap items-start gap-3 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800"
    >
      <Icon name="maintenance" className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">
          {data.length === 1 ? "Manutenção em andamento" : `${data.length} manutenções em andamento`}: alarmes dali aparecem aqui, sem aviso
          por e-mail.
        </p>
        <ul className="mt-0.5">
          {data.map((w) => (
            <li key={w.id}>
              <b>{scope(w)}</b> até {time(w.ends_at)} · {w.reason}
            </li>
          ))}
        </ul>
      </div>
      <Link to="/manutencao" className="font-medium underline">
        Gerenciar
      </Link>
    </div>
  );
}
