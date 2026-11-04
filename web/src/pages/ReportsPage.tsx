import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError, downloadFile, query, type AlarmKind, type AlarmsReport, type AvailabilityReport } from "../api";
import { Button, Card, inputClass, StatTile, td, th } from "../components/ui";
import { kindLabel } from "../format";

type Preset = "1" | "7" | "30" | "custom";

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 3 })} %`;
const minutes = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} min`;

function isoDay(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Período escolhido -> {from, to} com fuso (a API exige). */
export function periodParams(preset: Preset, start: string, end: string, now = new Date()): { from: string; to: string } | null {
  if (preset !== "custom") {
    return { from: new Date(now.getTime() - Number(preset) * 86_400_000).toISOString(), to: now.toISOString() };
  }
  if (!start || !end) return null;
  const from = new Date(`${start}T00:00:00`);           // meia-noite no fuso do navegador
  const to = new Date(`${end}T00:00:00`);
  to.setDate(to.getDate() + 1);                          // "até" inclui o dia inteiro
  return from < to ? { from: from.toISOString(), to: to.toISOString() } : null;
}

export function ReportsPage() {
  const today = new Date();
  const [preset, setPreset] = useState<Preset>("7");
  const [start, setStart] = useState(isoDay(new Date(today.getTime() - 7 * 86_400_000)));
  const [end, setEnd] = useState(isoDay(today));
  const [error, setError] = useState<string | null>(null);
  // presets "andam" com o relógio; fixa o instante ao trocar de período
  const [anchor, setAnchor] = useState(() => new Date());
  const params = periodParams(preset, start, end, anchor);

  const availability = useQuery({
    queryKey: ["reports", "availability", params],
    queryFn: () => api<AvailabilityReport>(`/reports/availability${query(params ?? {})}`),
    enabled: params !== null,
  });
  const alarms = useQuery({
    queryKey: ["reports", "alarms", params],
    queryFn: () => api<AlarmsReport>(`/reports/alarms${query(params ?? {})}`),
    enabled: params !== null,
  });

  async function download(report: "availability" | "alarms", format: "csv" | "pdf") {
    if (!params) return;
    setError(null);
    try {
      await downloadFile(`/reports/${report}${query({ ...params, format })}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "não foi possível baixar");
    }
  }

  const presets: [Preset, string][] = [["1", "24 horas"], ["7", "7 dias"], ["30", "30 dias"], ["custom", "Escolher datas"]];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Relatórios</h1>

      <div className="flex flex-wrap items-end gap-4">
        <div role="group" aria-label="Período" className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
          {presets.map(([key, label]) => (
            <button
              key={key}
              aria-pressed={preset === key}
              className={`rounded-md px-3 py-1.5 text-sm font-medium ${preset === key ? "bg-brand-600 text-white" : "text-slate-600"}`}
              onClick={() => {
                setPreset(key);
                setAnchor(new Date());
              }}
            >
              {label}
            </button>
          ))}
        </div>
        {preset === "custom" && (
          <>
            <label className="text-sm">
              <span className="mb-1 block text-slate-600">De</span>
              <input type="date" className={inputClass} value={start} max={end} onChange={(e) => setStart(e.target.value)} />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-slate-600">Até</span>
              <input type="date" className={inputClass} value={end} min={start} onChange={(e) => setEnd(e.target.value)} />
            </label>
          </>
        )}
      </div>

      {error && (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}
      {params === null && <p className="text-sm text-amber-800">Escolha um período válido.</p>}

      <div className="grid gap-4 sm:grid-cols-3">
        <StatTile label="Disponibilidade da rede" value={pct(availability.data?.overall_availability_pct)} detail="média das ONUs, ponderada pelo tempo" />
        <StatTile label="Alarmes no período" value={alarms.data?.total ?? "—"} detail={alarms.data ? `${alarms.data.open} ainda abertos` : undefined} />
        <StatTile label="Tempo médio até normalizar" value={minutes(alarms.data?.mttr_min)} detail="MTTR dos alarmes encerrados" />
      </div>

      <Card
        title="Disponibilidade por OLT"
        actions={
          <span className="flex gap-2">
            <Button variant="secondary" onClick={() => download("availability", "csv")} disabled={!params}>
              Baixar CSV
            </Button>
            <Button variant="secondary" onClick={() => download("availability", "pdf")} disabled={!params}>
              Baixar PDF
            </Button>
          </span>
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                <th className={th}>OLT</th>
                <th className={`${th} text-right`}>ONUs</th>
                <th className={`${th} text-right`}>Disponibilidade</th>
                <th className={`${th} text-right`}>ONUs fora</th>
                <th className={`${th} text-right`}>Quedas</th>
                <th className={`${th} text-right`}>Rompimentos</th>
                <th className={`${th} text-right`}>OLT inacessível</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 tabular-nums">
              {availability.data?.olts.map((o) => (
                <tr key={o.olt}>
                  <td className={`${td} font-medium`}>{o.olt}</td>
                  <td className={`${td} text-right`}>{o.onus}</td>
                  <td className={`${td} text-right`}>{pct(o.availability_pct)}</td>
                  <td className={`${td} text-right`}>{minutes(o.onu_downtime_min)}</td>
                  <td className={`${td} text-right`}>{o.onu_outages}</td>
                  <td className={`${td} text-right`}>{o.fiber_cuts}</td>
                  <td className={`${td} text-right`}>{minutes(o.olt_unreachable_min)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {availability.data?.olts.length === 0 && <p className="px-4 py-6 text-sm text-slate-500">Nenhuma OLT cadastrada.</p>}
        </div>
        {!!availability.data?.worst_onus.length && (
          <div className="border-t border-slate-200 px-4 py-3">
            <h3 className="mb-2 text-sm font-medium">ONUs com mais tempo fora do ar</h3>
            <ol className="space-y-1 text-sm">
              {availability.data.worst_onus.map((w) => (
                <li key={`${w.olt}-${w.pon}-${w.onu}`} className="flex flex-wrap justify-between gap-2 tabular-nums">
                  <span>
                    {w.olt} · PON {w.pon} · ONU {w.onu} <span className="font-mono text-xs text-slate-500">{w.serial}</span>
                  </span>
                  <span className="text-slate-600">
                    {minutes(w.downtime_min)} fora em {w.outages} {w.outages === 1 ? "queda" : "quedas"} · {pct(w.availability_pct)}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        )}
      </Card>

      <Card
        title="Alarmes por tipo"
        actions={
          <span className="flex gap-2">
            <Button variant="secondary" onClick={() => download("alarms", "csv")} disabled={!params}>
              Baixar CSV
            </Button>
            <Button variant="secondary" onClick={() => download("alarms", "pdf")} disabled={!params}>
              Baixar PDF
            </Button>
          </span>
        }
      >
        {alarms.data && Object.keys(alarms.data.by_kind).length > 0 ? (
          <ul className="divide-y divide-slate-100 text-sm">
            {(Object.entries(alarms.data.by_kind) as [AlarmKind, number][])
              .sort((a, b) => b[1] - a[1])
              .map(([kind, n]) => (
                <li key={kind} className="flex justify-between px-4 py-2 tabular-nums">
                  <span>{kindLabel[kind]}</span>
                  <span className="font-medium">{n}</span>
                </li>
              ))}
          </ul>
        ) : (
          <p className="px-4 py-6 text-sm text-slate-500">Nenhum alarme no período.</p>
        )}
        <p className="border-t border-slate-200 px-4 py-2 text-xs text-slate-500">
          ONUs de um rompimento de fibra contam dentro dele. O CSV abre no Excel (separador ";" e vírgula decimal).
        </p>
      </Card>
    </div>
  );
}
