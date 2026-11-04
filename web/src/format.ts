import type { AlarmKind, Cause, Severity } from "./api";

export const RX_LIMIT_DBM = -27; // mesmo limite do worker

export const kindLabel: Record<AlarmKind, string> = {
  pon_fiber_cut: "Rompimento de fibra",
  onu_offline: "ONU offline",
  onu_rx_low: "Sinal baixo",
  olt_unreachable: "OLT inacessível",
  olt_cpu_high: "CPU alta",
};

export const severityLabel: Record<Severity, string> = {
  critical: "Crítico",
  major: "Grave",
  minor: "Menor",
  warning: "Aviso",
};

const nf = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export function dbm(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${nf.format(value)} dBm`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "medium" });
}

/** "agora", "há 5 min", "há 2 h", "há 3 dias" */
export function ago(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "—";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return "agora";
  if (s < 3600) return `há ${Math.floor(s / 60)} min`;
  if (s < 86400) return `há ${Math.floor(s / 3600)} h`;
  return `há ${Math.floor(s / 86400)} dias`;
}

/** Duração legível: "45 s", "12 min", "3 h 05 min", "2 d 4 h" */
export function duration(fromIso: string, toIso: string | null = null, now: number = Date.now()): string {
  const s = Math.max(0, Math.round(((toIso ? new Date(toIso).getTime() : now) - new Date(fromIso).getTime()) / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} h ${String(m % 60).padStart(2, "0")} min`;
  return `${Math.floor(h / 24)} d ${h % 24} h`;
}

/** Onde está a falha: "OLT · PON 0/1/2 · ONU 5" */
export function location(a: { olt_name: string; pon: string | null; onu_index: number | null }): string {
  return [a.olt_name, a.pon && `PON ${a.pon}`, a.onu_index !== null && `ONU ${a.onu_index}`].filter(Boolean).join(" · ");
}

export const causeLabel: Record<Cause, string> = {
  fiber_third_party: "Rompimento por terceiros (obra, veículo)",
  fiber_natural: "Rompimento por causa natural (árvore, chuva, animal)",
  power: "Falta de energia",
  equipment: "Falha de equipamento (OLT, splitter, ONU)",
  customer: "Problema no cliente",
  maintenance: "Manutenção programada",
  configuration: "Erro de configuração",
  no_fault: "Sem falha real (falso alarme)",
  other: "Outro",
};

/** Cronômetro: "04:07", "1:02:09", "2 d 03:15:00" (de from até to, ou até agora). */
export function stopwatch(fromIso: string, toIso: string | null = null, now: number = Date.now()): string {
  let s = Math.max(0, Math.floor(((toIso ? new Date(toIso).getTime() : now) - new Date(fromIso).getTime()) / 1000));
  const d = Math.floor(s / 86400);
  s %= 86400;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mmss = `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  const clock = h > 0 || d > 0 ? `${d > 0 ? String(h).padStart(2, "0") : h}:${mmss}` : mmss;
  return d > 0 ? `${d} d ${clock}` : clock;
}

/** Minutos do relatório em texto: "45 s", "12 min", "1 h 05 min". */
export function humanMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "—";
  const s = Math.round(minutes * 60);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}
