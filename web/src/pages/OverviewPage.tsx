import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useMemo, type ReactNode } from "react";
import { Link } from "react-router";
import { api, query, type AtRiskOnu, type AttendanceReport, type HourPoint, type OltList, type Overview, type Severity } from "../api";
import { AlarmTable } from "../components/AlarmTable";
import { AlarmsPerHour, Sparkline } from "../components/charts";
import { Card, SeverityIcon, StatusBadge } from "../components/ui";
import { dbm, humanMinutes, RX_LIMIT_DBM, severityLabel } from "../format";

// o mini-mapa traz o Leaflet: carrega à parte, depois dos números
const MiniMap = lazy(() => import("../components/MiniMap").then((m) => ({ default: m.MiniMap })));

const SEVERITIES: Severity[] = ["critical", "major", "minor", "warning"];
const POLL_MS = 30_000; // reserva caso o tempo real caia
const TEAL = "#14b8a6";
const RED = "#dc2626";

type Tone = "neutral" | "bad" | "warn" | "good";
const TAG: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-600",
  good: "bg-emerald-50 text-emerald-700",
  warn: "bg-amber-50 text-amber-800",
  bad: "bg-red-50 text-red-700",
};

/** Cartão de indicador: número grande, selo de situação, tendência de 24 h e detalhe. */
function Kpi({ label, value, unit, tag, tone = "neutral", spark, children }: {
  label: string;
  value: ReactNode;
  unit?: string;
  tag?: string;
  tone?: Tone;
  spark?: { values: number[]; color: string; label: string };
  children?: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2 rounded-xl border border-slate-200 bg-surface p-4" aria-label={label}>
      <h2 className="truncate text-sm font-medium text-slate-600">{label}</h2>
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <p className="flex items-baseline gap-1.5">
          <span className="text-3xl font-bold tracking-tight text-slate-900 tabular-nums">{value}</span>
          {unit && <span className="text-sm text-slate-500">{unit}</span>}
        </p>
        {tag && <span className={`rounded-md px-1.5 py-0.5 text-xs font-semibold whitespace-nowrap ${TAG[tone]}`}>{tag}</span>}
      </div>
      {spark ? <Sparkline {...spark} /> : <div className="h-8" aria-hidden />}
      <div className="text-xs text-slate-500">{children}</div>
    </section>
  );
}

export function OverviewPage() {
  const today = useMemo(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d.toISOString();
  }, []);
  const ov = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/overview"), refetchInterval: POLL_MS });
  const olts = useQuery({ queryKey: ["olts"], queryFn: () => api<OltList>("/olts"), refetchInterval: POLL_MS });
  const risk = useQuery({ queryKey: ["at-risk"], queryFn: () => api<AtRiskOnu[]>("/onus-at-risk"), refetchInterval: 60_000 });
  const history = useQuery({
    queryKey: ["overview", "history"],
    queryFn: () => api<{ hours: HourPoint[] }>("/overview/history"),
    refetchInterval: 60_000,
  });
  const attendance = useQuery({
    queryKey: ["alarms", "overview-attendance", today],
    queryFn: () => api<AttendanceReport>(`/reports/attendance${query({ from: today, to: new Date().toISOString() })}`),
    refetchInterval: 60_000,
  });

  if (ov.isPending) return <OverviewSkeleton />;
  if (ov.error) return <p role="alert" className="text-sm text-red-700">Erro ao carregar: {ov.error.message}</p>;
  const d = ov.data;

  if (d.olts.total === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-surface p-10 text-center">
        <h1 className="text-lg font-medium">Nenhuma OLT cadastrada ainda</h1>
        <p className="mt-1 text-sm text-slate-500">Cadastre a primeira OLT para a Lumio começar a monitorar a rede.</p>
        <Link to="/olts" className="mt-4 inline-block rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-800">
          Cadastrar OLT
        </Link>
      </div>
    );
  }

  const hours = history.data?.hours ?? [];
  const offline = d.onus.offline;
  const pctOnline = d.onus.total ? (100 * d.onus.online) / d.onus.total : 0;
  const custOff = d.customers_offline ?? 0;
  const s = attendance.data?.summary;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-sm text-slate-500">Monitoramento</p>
          <h1 className="text-2xl font-bold tracking-tight">Visão geral</h1>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <Kpi
          label="Alarmes abertos"
          value={d.alarms.total}
          tag={d.alarms.critical ? `${d.alarms.critical} ${d.alarms.critical === 1 ? "crítico" : "críticos"}` : d.alarms.total ? undefined : "tudo certo"}
          tone={d.alarms.critical ? "bad" : "good"}
          spark={hours.length ? { values: hours.map((h) => h.open), color: d.alarms.critical ? RED : TEAL, label: "Alarmes em aberto nas últimas 24 h" } : undefined}
        >
          <ul className="flex flex-wrap gap-x-3 gap-y-1">
            {SEVERITIES.map((sev) => (
              <li key={sev} className="inline-flex items-center gap-1">
                <SeverityIcon severity={sev} className="size-2.5" />
                {d.alarms[sev]} {severityLabel[sev].toLowerCase()}
              </li>
            ))}
          </ul>
        </Kpi>
        <Kpi
          label="ONUs online"
          value={`${d.onus.online} / ${d.onus.total}`}
          tag={`${pctOnline.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} %`}
          tone={offline > 0 ? (pctOnline < 90 ? "bad" : "warn") : "good"}
          spark={hours.length ? { values: hours.map((h) => d.onus.total - h.onus_offline), color: TEAL, label: "ONUs online nas últimas 24 h" } : undefined}
        >
          {offline > 0 ? (
            <Link className="font-medium text-red-700 hover:underline" to="/onus?status=offline">
              {offline} offline
            </Link>
          ) : (
            "todas online"
          )}
        </Kpi>
        <Kpi
          label="Clientes afetados"
          value={custOff}
          unit={d.customers ? `de ${d.customers}` : undefined}
          tag={custOff ? "sem serviço" : undefined}
          tone={custOff ? "bad" : "good"}
          spark={hours.length && d.customers ? { values: hours.map((h) => h.onus_offline), color: custOff ? RED : TEAL, label: "ONUs offline nas últimas 24 h" } : undefined}
        >
          {d.customers ? (
            <Link className="hover:underline" to={custOff ? "/clientes?state=offline" : "/mapa"}>
              {custOff ? "ver clientes sem serviço" : "ver no mapa"}
            </Link>
          ) : (
            <Link className="hover:underline" to="/clientes">
              importar clientes
            </Link>
          )}
        </Kpi>
        <Kpi
          label={`Sinal < ${RX_LIMIT_DBM} dBm`}
          value={d.rx_low}
          unit="ONUs"
          tag={d.rx_trend ? `${d.rx_trend} piorando` : undefined}
          tone={d.rx_trend ? "warn" : "neutral"}
        >
          {d.rx_low > 0 ? (
            <Link className="hover:underline" to={`/onus?rx_below=${RX_LIMIT_DBM}`}>
              ver ONUs
            </Link>
          ) : (
            "nenhuma ONU"
          )}
          {d.rx_trend > 0 && <span className="block text-amber-700">{d.rx_trend} com sinal piorando</span>}
        </Kpi>
        <Kpi
          label="OLTs coletando"
          value={`${d.olts.ok} / ${d.olts.total}`}
          tag={d.olts.error ? `${d.olts.error} sem resposta` : undefined}
          tone={d.olts.error ? "bad" : d.olts.late ? "warn" : "good"}
        >
          {d.olts.error > 0 || d.olts.late > 0 ? (
            <Link className="hover:underline" to="/olts">
              {d.olts.late > 0 ? `${d.olts.late} com coleta atrasada · ` : ""}ver OLTs
            </Link>
          ) : (
            "coleta em dia"
          )}
        </Kpi>
      </div>

      <div className="grid gap-5 xl:grid-cols-5">
        <Card
          title="Alarmes abertos"
          className="xl:col-span-3"
          actions={
            <Link to="/alarms" className="text-sm font-medium text-brand-600 hover:underline">
              Central de alarmes →
            </Link>
          }
        >
          <AlarmTable alarms={d.recent_alarms} compact />
        </Card>
        <Card
          title="Mapa da rede"
          className="flex flex-col overflow-hidden xl:col-span-2"
          actions={
            <Link to="/mapa" className="text-sm font-medium text-brand-600 hover:underline">
              Expandir
            </Link>
          }
        >
          <div className="h-80 flex-1">
            <Suspense fallback={<div className="h-full animate-pulse bg-slate-100" aria-hidden />}>
              <MiniMap />
            </Suspense>
          </div>
        </Card>
      </div>

      <div className="grid gap-5 xl:grid-cols-5">
        <Card
          title="Alarmes nas últimas 24 h"
          className="xl:col-span-2"
          actions={
            s && (
              <span className="text-xs text-slate-500">
                Hoje: TMA <b className="text-slate-800">{s.tma_min !== null ? humanMinutes(s.tma_min) : "—"}</b> · SLA {s.sla_assume_min} min{" "}
                <b className="text-slate-800">{s.assumed_within_sla_pct !== null ? `${s.assumed_within_sla_pct.toLocaleString("pt-BR")} %` : "—"}</b>
              </span>
            )
          }
        >
          <div className="p-4">{hours.length ? <AlarmsPerHour hours={hours} /> : <div className="h-40 animate-pulse rounded bg-slate-100" aria-hidden />}</div>
        </Card>

        <Card title="Saúde das OLTs" className="xl:col-span-3">
          <ul className="divide-y divide-slate-100">
            {olts.data?.items.map((o) => {
              const pct = o.onus_total ? (o.onus_online / o.onus_total) * 100 : 0;
              const bad = o.collection_status === "error";
              return (
                <li key={o.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 px-4 py-3 sm:grid-cols-[minmax(8rem,1fr)_auto_minmax(10rem,2fr)_auto]">
                  <Link to={`/olts/${o.id}`} className="truncate font-medium hover:underline">
                    {o.name}
                  </Link>
                  <StatusBadge status={o.collection_status} />
                  {/* uma magnitude só: barra de um tom, com o número escrito ao lado */}
                  <div className="col-span-2 flex items-center gap-3 sm:col-span-1">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-200" aria-hidden>
                      <div className={`h-full rounded-full ${bad ? "bg-red-500" : pct < 90 ? "bg-amber-500" : "bg-brand-500"}`} style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-sm whitespace-nowrap text-slate-600 tabular-nums">
                      {o.onus_online}/{o.onus_total} ONUs online
                    </span>
                  </div>
                  <span className={`hidden text-right text-sm tabular-nums sm:block ${o.active_alarms ? "font-medium text-red-700" : "text-slate-400"}`}>
                    {o.active_alarms} {o.active_alarms === 1 ? "alarme" : "alarmes"}
                  </span>
                </li>
              );
            })}
          </ul>
        </Card>
      </div>

      {!!risk.data?.length && (
        <Card title="Sinal piorando: agir antes de o cliente cair">
          <ul className="divide-y divide-slate-100 text-sm">
            {risk.data.slice(0, 6).map((r) => (
              <li key={r.onu_id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2">
                <Link to={`/onus/${r.onu_id}`} className="hover:underline">
                  <span className="font-mono text-xs">{r.serial}</span> · {r.olt_name} · PON {r.pon} · ONU {r.onu_index}
                </Link>
                <span className="text-slate-600 tabular-nums">
                  {dbm(r.rx_dbm)} · {r.slope_db_day.toLocaleString("pt-BR")} dB/dia ·{" "}
                  <b className="text-amber-700">
                    limite em ~{r.days_to_limit < 1 ? `${Math.max(1, Math.round(r.days_to_limit * 24))} h` : `${Math.round(r.days_to_limit)} dias`}
                  </b>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

/** Esqueleto enquanto carrega: a página não "pula" quando os números chegam. */
function OverviewSkeleton() {
  return (
    <div className="space-y-5" aria-busy="true" aria-label="Carregando visão geral">
      <div className="h-12 w-48 animate-pulse rounded bg-slate-200" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="h-40 animate-pulse rounded-xl bg-slate-100" />
        ))}
      </div>
      <div className="h-80 animate-pulse rounded-xl bg-slate-100" />
    </div>
  );
}
