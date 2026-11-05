import type { HourPoint } from "../api";

/** Linha fina de tendência (sem eixos) para os cartões de indicador. */
export function Sparkline({ values, color, label }: { values: number[]; color: string; label: string }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 100},${28 - ((v - min) / span) * 24}`).join(" ");
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="h-8 w-full" role="img" aria-label={label}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

const hour = (iso: string) => new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });

// cores de severidade (as mesmas dos ícones), empilhadas da base para cima
const SEGMENTS = [
  { key: "critical", label: "Crítico", color: "#dc2626" },
  { key: "major", label: "Grave", color: "#ea580c" },
  { key: "other", label: "Menor/aviso", color: "#94a3b8" },
] as const;

/** Barras empilhadas: alarmes abertos em cada hora das últimas 24 h. */
export function AlarmsPerHour({ hours }: { hours: HourPoint[] }) {
  const total = (h: HourPoint) => h.critical + h.major + h.other;
  const max = Math.max(1, ...hours.map(total));
  const sum = hours.reduce((acc, h) => acc + total(h), 0);
  return (
    <figure className="space-y-2">
      <div className="flex h-32 items-end gap-[3px] border-b border-slate-200" aria-hidden>
        {hours.map((h) => {
          const n = total(h);
          return (
            <div
              key={h.t}
              className="group relative flex h-full flex-1 items-end"
              title={`${hour(h.t)}: ${n} ${n === 1 ? "alarme" : "alarmes"}${n ? ` (${h.critical} crít., ${h.major} graves, ${h.other} outros)` : ""}`}
            >
              {n === 0 ? (
                <span className="block h-0.5 w-full rounded-sm bg-slate-200" />
              ) : (
                <span className="flex w-full flex-col-reverse overflow-hidden rounded-t-[3px]" style={{ height: `${(n / max) * 100}%` }}>
                  {SEGMENTS.filter((s) => h[s.key] > 0).map((s) => (
                    <span key={s.key} className="block min-h-0.5 [&:not(:last-child)]:border-t-2 [&:not(:last-child)]:border-surface" style={{ flexGrow: h[s.key], background: s.color }} />
                  ))}
                </span>
              )}
              <span className="absolute inset-0 rounded-sm group-hover:bg-slate-500/10" />
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-[11px] text-slate-500 tabular-nums" aria-hidden>
        <span>{hours[0] && hour(hours[0].t)}</span>
        <span>{hours[8] && hour(hours[8].t)}</span>
        <span>{hours[16] && hour(hours[16].t)}</span>
        <span>agora</span>
      </div>
      <figcaption className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600">
        {SEGMENTS.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-sm" style={{ background: s.color }} aria-hidden />
            {s.label}
          </span>
        ))}
        <span className="ml-auto">
          {sum} {sum === 1 ? "alarme" : "alarmes"} em 24 h
        </span>
      </figcaption>
      {/* a mesma informação em tabela, para leitor de tela */}
      <table className="sr-only">
        <caption>Alarmes abertos por hora</caption>
        <thead>
          <tr>
            <th>Hora</th>
            <th>Críticos</th>
            <th>Graves</th>
            <th>Outros</th>
          </tr>
        </thead>
        <tbody>
          {hours.map((h) => (
            <tr key={h.t}>
              <td>{hour(h.t)}</td>
              <td>{h.critical}</td>
              <td>{h.major}</td>
              <td>{h.other}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
