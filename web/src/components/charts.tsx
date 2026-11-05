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
const day = (iso: string) => new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });

type Bucket = Pick<HourPoint, "t" | "critical" | "major" | "other">;

// cores de severidade (as mesmas dos ícones), empilhadas da base para cima
const SEGMENTS = [
  { key: "critical", label: "Crítico", color: "#dc2626" },
  { key: "major", label: "Grave", color: "#ea580c" },
  { key: "other", label: "Menor/aviso", color: "#94a3b8" },
] as const;

/**
 * Barras empilhadas por severidade: alarmes abertos em cada hora (ou dia).
 * `live`: a última barra é "agora" (visão geral); nos relatórios mostra a data.
 */
export function AlarmsPerHour({
  hours,
  bucket = "hour",
  live = true,
  suffix = "em 24 h",
}: {
  hours: Bucket[];
  bucket?: "hour" | "day";
  live?: boolean;
  suffix?: string;
}) {
  const label = bucket === "hour" ? hour : day;
  const total = (h: Bucket) => h.critical + h.major + h.other;
  const count = hours.length;
  const marks = count ? [0, Math.floor(count / 3), Math.floor((2 * count) / 3), count - 1] : [];
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
              title={`${label(h.t)}: ${n} ${n === 1 ? "alarme" : "alarmes"}${n ? ` (${h.critical} crít., ${h.major} graves, ${h.other} outros)` : ""}`}
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
        {marks.map((i, k) => (
          <span key={k}>{k === marks.length - 1 && live ? "agora" : label(hours[i].t)}</span>
        ))}
      </div>
      <figcaption className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600">
        {SEGMENTS.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-sm" style={{ background: s.color }} aria-hidden />
            {s.label}
          </span>
        ))}
        <span className="ml-auto">
          {sum} {sum === 1 ? "alarme" : "alarmes"} {suffix}
        </span>
      </figcaption>
      {/* a mesma informação em tabela, para leitor de tela */}
      <table className="sr-only">
        <caption>Alarmes abertos por {bucket === "hour" ? "hora" : "dia"}</caption>
        <thead>
          <tr>
            <th>{bucket === "hour" ? "Hora" : "Dia"}</th>
            <th>Críticos</th>
            <th>Graves</th>
            <th>Outros</th>
          </tr>
        </thead>
        <tbody>
          {hours.map((h) => (
            <tr key={h.t}>
              <td>{label(h.t)}</td>
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

/** Barras horizontais com rótulo e valor (uma magnitude só, cor por faixa). */
export function HBars({
  items,
  max,
  min = 0,
  format,
  label,
}: {
  items: { key: string; label: string; value: number; color: string; hint?: string }[];
  max?: number;
  /** início da escala (ex.: 90 para disponibilidade, senão 99 % e 100 % ficam iguais) */
  min?: number;
  format: (v: number) => string;
  label: string;
}) {
  const top = max ?? Math.max(1, ...items.map((i) => i.value));
  return (
    <ul className="space-y-2.5 p-4" aria-label={label}>
      {items.map((i) => (
        <li key={i.key} className="grid grid-cols-[minmax(7rem,12rem)_1fr_auto] items-center gap-3 text-sm" title={i.hint}>
          <span className="truncate">{i.label}</span>
          <span className="h-2.5 overflow-hidden rounded-full bg-slate-100" aria-hidden>
            <span className="block h-full rounded-full" style={{ width: `${Math.max(1, (100 * (i.value - min)) / (top - min))}%`, background: i.color }} />
          </span>
          <span className="w-24 text-right font-medium tabular-nums">{format(i.value)}</span>
        </li>
      ))}
    </ul>
  );
}
