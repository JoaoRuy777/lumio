import { useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Readings } from "../api";
import { dateTime, dbm, RX_LIMIT_DBM } from "../format";

// Uma série só: o título nomeia, sem caixa de legenda. Linha de 2 px na cor
// da série 1; o limite de alarme é uma linha de referência rotulada.
const SERIES = "#2a78d6";
const LIMIT = "#d03b3b";
// cores pelas variáveis do tema: o gráfico acompanha o modo noturno
const AXIS_TEXT = { fill: "var(--color-slate-500)", fontSize: 12 };

function tick(ts: number, spanHours: number) {
  const d = new Date(ts);
  return spanHours <= 24
    ? d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

export function RxChart({ readings, hours }: { readings: Readings; hours: number }) {
  const [asTable, setAsTable] = useState(false);
  const points = readings.items.map((r) => ({ t: new Date(r.ts).getTime(), rx: r.rx_dbm }));
  const values = points.map((p) => p.rx).filter((v): v is number => v !== null);

  if (points.length === 0) {
    return (
      <p className="px-4 py-10 text-center text-sm text-slate-500">
        Sem leituras de potência no período. A potência é coletada a cada 5 minutos (padrão).
      </p>
    );
  }

  // eixo sempre mostra o limite, com uma folga em volta dos dados
  // marcas do eixo a cada 2, 3 ou 5 dB, alinhadas ao passo (nada de -18, -20, -23)
  const min = Math.min(RX_LIMIT_DBM, ...values) - 1;
  const max = Math.max(RX_LIMIT_DBM, ...values) + 1;
  const step = max - min > 15 ? 5 : max - min > 8 ? 3 : 2;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = Array.from({ length: (hi - lo) / step + 1 }, (_, i) => lo + i * step);

  return (
    <div className="px-2 pt-3 pb-2">
      <div className="mb-1 flex justify-end px-2">
        <button className="text-xs text-brand-600 hover:underline" onClick={() => setAsTable(!asTable)} aria-pressed={asTable}>
          {asTable ? "Ver gráfico" : "Ver como tabela"}
        </button>
      </div>
      {asTable ? (
        <div className="max-h-72 overflow-y-auto px-2">
          <table className="w-full text-sm">
            <caption className="sr-only">Potência recebida (RX) por horário</caption>
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="py-1 font-medium">Horário</th>
                <th className="py-1 text-right font-medium">RX{readings.bucket_s > 0 && " (média)"}</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {[...readings.items].reverse().map((r) => (
                <tr key={r.ts} className="border-t border-slate-100">
                  <td className="py-1">{dateTime(r.ts)}</td>
                  <td className={`py-1 text-right ${r.rx_dbm !== null && r.rx_dbm < RX_LIMIT_DBM ? "font-medium text-red-700" : ""}`}>
                    {dbm(r.rx_dbm)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="h-64" role="img" aria-label={`Gráfico da potência recebida nas últimas ${hours} horas; mínimo ${dbm(Math.min(...values))}`}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--color-slate-200)" />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(t: number) => tick(t, hours)}
                tick={AXIS_TEXT}
                axisLine={false}
                tickLine={false}
                minTickGap={40}
              />
              <YAxis domain={[lo, hi]} ticks={ticks} tick={AXIS_TEXT} axisLine={false} tickLine={false} width={44} />
              <ReferenceLine
                y={RX_LIMIT_DBM}
                stroke={LIMIT}
                strokeDasharray="4 4"
                label={{ value: `limite de alarme ${RX_LIMIT_DBM} dBm`, position: "insideTopLeft", fill: "var(--color-slate-600)", fontSize: 12 }}
              />
              <Tooltip
                cursor={{ stroke: "var(--color-slate-400)", strokeWidth: 1 }}
                labelFormatter={(t) => dateTime(new Date(Number(t)).toISOString())}
                formatter={(v) => [dbm(Number(v)), readings.bucket_s > 0 ? "RX (média)" : "RX"]}
                contentStyle={{ borderRadius: 8, borderColor: "var(--color-slate-200)", backgroundColor: "var(--color-surface)", color: "var(--color-slate-800)", fontSize: 13 }}
              />
              <Line
                type="monotone"
                dataKey="rx"
                stroke={SERIES}
                strokeWidth={2}
                dot={points.length < 3 ? { r: 4, fill: SERIES, stroke: "var(--color-surface)", strokeWidth: 2 } : false}
                activeDot={{ r: 5, fill: SERIES, stroke: "var(--color-surface)", strokeWidth: 2 }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
