import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import { Link } from "react-router";
import { api, query, type Alarm, type AttendanceReport, type CustomerState, type MapData, type Me, type Overview, type Page } from "../api";
import { Logo } from "../components/Logo";
import { NetworkMap } from "../components/NetworkMap";
import { SeverityIcon } from "../components/ui";
import { humanMinutes, kindLabel, location, severityLabel, stopwatch } from "../format";
import { LiveIndicator, LiveProvider } from "../live";
import { useNow } from "../useNow";

const ALL: Set<CustomerState> = new Set(["online", "trend", "low", "offline", "unknown"]);
const SLA_MS = 15 * 60_000;
const BAR: Record<Alarm["severity"], string> = { critical: "bg-red-600", major: "bg-orange-500", minor: "bg-yellow-400", warning: "bg-slate-400" };

function Kpi({ label, value, detail, tone = "neutral" }: { label: string; value: string | number; detail?: string; tone?: "neutral" | "bad" | "warn" | "good" }) {
  const color = { neutral: "text-slate-900", bad: "text-red-500", warn: "text-amber-500", good: "text-emerald-500" }[tone];
  return (
    <section className="rounded-2xl border border-slate-200 bg-surface px-5 py-4" aria-label={label}>
      <p className="text-sm font-medium tracking-wide text-slate-500 uppercase">{label}</p>
      <p className={`mt-1 text-5xl font-semibold tabular-nums ${color}`}>{value}</p>
      {detail && <p className="mt-1 text-sm text-slate-500">{detail}</p>}
    </section>
  );
}

function TicketRow({ a, now }: { a: Alarm; now: number }) {
  const waiting = !a.assigned_to;
  const late = waiting && now - new Date(a.created_at).getTime() > SLA_MS;
  return (
    <li className="flex items-stretch gap-3 rounded-xl border border-slate-200 bg-surface">
      <span className={`w-2 shrink-0 rounded-l-xl ${BAR[a.severity]}`} aria-hidden />
      <div className="min-w-0 flex-1 py-3">
        <p className="flex items-center gap-2 text-lg font-semibold">
          <SeverityIcon severity={a.severity} className="size-3.5" />
          <span className="sr-only">{severityLabel[a.severity]}</span>
          <span className="truncate">{kindLabel[a.kind]}</span>
        </p>
        <p className="truncate text-sm text-slate-500">
          {location(a)}
          {a.affected_customers > 0 && ` · ${a.affected_customers} clientes`}
          {a.customer_name && ` · ${a.customer_name}`}
        </p>
      </div>
      <div className="py-3 pr-4 text-right">
        <p className={`font-mono text-2xl font-semibold tabular-nums ${late ? "text-red-500" : waiting ? "text-amber-500" : "text-slate-800"}`}>
          {stopwatch(waiting ? a.created_at : (a.first_assigned_at ?? a.created_at), null, now)}
        </p>
        <p className={`text-sm ${late ? "font-semibold text-red-500" : "text-slate-500"}`}>
          {waiting ? (late ? "sem dono há mais de 15 min" : "aguardando") : `com ${a.assigned_to}`}
        </p>
      </div>
    </li>
  );
}

function Tv({ me }: { me: Me }) {
  const now = useNow();
  const today = useMemo(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d.toISOString();
  }, []);
  const overview = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/overview"), refetchInterval: 30_000 });
  const alarms = useQuery({
    queryKey: ["alarms", "tv"],
    queryFn: () => api<Page<Alarm>>(`/alarms${query({ status: "open", limit: 10 })}`),
    refetchInterval: 30_000,
  });
  const map = useQuery({ queryKey: ["map"], queryFn: () => api<MapData>("/map"), refetchInterval: 30_000 });
  const attendance = useQuery({
    queryKey: ["alarms", "tv-attendance", today],
    queryFn: () => api<AttendanceReport>(`/reports/attendance${query({ from: today, to: new Date().toISOString() })}`),
    refetchInterval: 60_000,
  });

  const ov = overview.data;
  const s = attendance.data?.summary;
  const items = alarms.data?.items ?? [];
  const unassigned = alarms.data ? items.filter((a) => !a.assigned_to).length : null;
  const down = map.data ? map.data.customers.filter((c) => c.state === "offline").length : null;   // null: carregando
  const pct = ov && ov.onus.total ? (100 * ov.onus.online) / ov.onus.total : null;

  return (
    <div className="flex min-h-screen flex-col gap-5 p-6">
      <header className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <Logo size={48} />
          <span className="text-xl text-slate-500">NOC · {me.tenant_name}</span>
        </div>
        <div className="flex items-center gap-5">
          <LiveIndicator />
          <span className="font-mono text-3xl font-semibold tabular-nums">
            {new Date(now).toLocaleTimeString("pt-BR")}
          </span>
          <button
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100"
            onClick={() => (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen())}
          >
            Tela cheia
          </button>
          <Link to="/" className="text-sm text-slate-500 hover:underline">
            Sair do modo TV
          </Link>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
        <Kpi
          label="ONUs online"
          value={pct === null ? "—" : `${pct.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`}
          detail={ov ? `${ov.onus.online} de ${ov.onus.total}` : undefined}
          tone={pct === null ? "neutral" : pct >= 99 ? "good" : pct >= 95 ? "warn" : "bad"}
        />
        <Kpi label="Clientes sem serviço" value={down ?? "—"} tone={down === null ? "neutral" : down ? "bad" : "good"} detail={ov ? `${ov.customers} clientes na base` : undefined} />
        <Kpi label="Alarmes críticos" value={ov?.alarms.critical ?? "—"} tone={ov?.alarms.critical ? "bad" : "good"} detail={ov ? `${ov.alarms.total} abertos no total` : undefined} />
        <Kpi label="Chamados sem dono" value={unassigned ?? "—"} tone={unassigned === null ? "neutral" : unassigned ? "warn" : "good"} detail="esperando alguém assumir" />
        <Kpi label="TME hoje" value={humanMinutes(s?.tme_min)} detail={s?.assumed_within_sla_pct != null ? `${s.assumed_within_sla_pct.toLocaleString("pt-BR")}% em até 15 min` : "tempo até assumir"} />
        <Kpi label="TMA hoje" value={humanMinutes(s?.tma_min)} detail={s ? `${s.closed} chamados encerrados` : "tempo de atendimento"} />
      </div>

      <div className="grid flex-1 gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section aria-label="Fila de chamados" className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold">Chamados abertos</h2>
          {items.length === 0 ? (
            <p className="flex flex-1 items-center justify-center rounded-xl border border-dashed border-slate-300 text-2xl text-emerald-500">
              Rede normal · nenhum chamado aberto
            </p>
          ) : (
            <ul className="space-y-3">
              {items.map((a) => (
                <TicketRow key={a.id} a={a} now={now} />
              ))}
            </ul>
          )}
          {ov && ov.rx_trend > 0 && (
            <p className="rounded-xl bg-amber-50 px-4 py-3 text-amber-800">
              {ov.rx_trend} {ov.rx_trend === 1 ? "ONU com sinal piorando" : "ONUs com sinal piorando"} (devem passar do limite em até 7 dias)
            </p>
          )}
        </section>
        {map.data && map.data.customers.length > 0 ? (
          <NetworkMap data={map.data} visible={ALL} className="h-full min-h-[420px]" interactive={false} />
        ) : (
          <div className="flex items-center justify-center rounded-xl border border-dashed border-slate-300 text-slate-500">
            Importe os clientes para ver o mapa
          </div>
        )}
      </div>
    </div>
  );
}

/** Modo TV: tela de parede do NOC, sempre escura, sem menu. */
export function TvPage({ me }: { me: Me }) {
  useEffect(() => {
    const root = document.documentElement;
    const previous = root.dataset.theme;
    root.dataset.theme = "dark";             // só nesta tela; não muda a preferência salva
    return () => {
      if (previous) root.dataset.theme = previous;
    };
  }, []);
  return (
    <LiveProvider>
      <Tv me={me} />
    </LiveProvider>
  );
}
