import { cloneElement, useId, type ButtonHTMLAttributes, type ReactElement, type ReactNode } from "react";
import type { AlarmStatus, CollectionStatus, Severity } from "../api";
import { severityLabel } from "../format";

export const inputClass =
  "w-full rounded-md border border-slate-300 bg-surface px-3 py-2 text-sm shadow-xs outline-none " +
  "focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 disabled:bg-slate-100";

// O rótulo aponta para o campo (htmlFor) e a dica fica ligada por aria-describedby:
// leitores de tela anunciam "Nome", e a dica como descrição, não como parte do nome.
export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactElement<{ id?: string }> }) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-slate-700">
        {label}
      </label>
      {cloneElement(children as ReactElement<Record<string, unknown>>, {
        id,
        ...(hint ? { "aria-describedby": hintId } : {}),
      })}
      {hint && (
        <span id={hintId} className="mt-1 block text-xs text-slate-500">
          {hint}
        </span>
      )}
    </div>
  );
}

type Variant = "primary" | "secondary" | "danger";

const variants: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-800 disabled:bg-brand-500/50",
  secondary: "border border-slate-300 bg-surface text-slate-700 hover:bg-slate-50 disabled:text-slate-400",
  danger: "border border-red-200 bg-surface text-red-700 hover:bg-red-50",
};

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      {...props}
      className={`rounded-md px-3 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed ${variants[variant]} ${className}`}
    />
  );
}

const statusStyle: Record<CollectionStatus, [string, string]> = {
  ok: ["Coletando", "bg-emerald-50 text-emerald-700 ring-emerald-600/20"],
  pending: ["Aguardando 1ª coleta", "bg-slate-100 text-slate-600 ring-slate-500/20"],
  late: ["Coleta atrasada", "bg-amber-50 text-amber-800 ring-amber-600/20"],
  error: ["Sem resposta", "bg-red-50 text-red-700 ring-red-600/20"],
  disabled: ["Desativada", "bg-slate-100 text-slate-500 ring-slate-500/20"],
};

export function StatusBadge({ status }: { status: CollectionStatus }) {
  const [label, style] = statusStyle[status];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}>
      <span className="size-1.5 rounded-full bg-current" aria-hidden />
      {label}
    </span>
  );
}

export function PlanUsageBar({ used, limit }: { used: number; limit: number }) {
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 100;
  const full = used >= limit;
  return (
    <div className="min-w-48">
      <div className="mb-1 flex justify-between text-sm">
        <span className="text-slate-600">Uso do plano</span>
        <span className={full ? "font-medium text-amber-700" : "font-medium"}>
          {used} de {limit} OLTs
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-200" role="progressbar" aria-valuenow={used} aria-valuemax={limit}>
        <div className={`h-full rounded-full ${full ? "bg-amber-500" : "bg-brand-500"}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ painel (sprint 4)

// Cores de status reservadas (nunca usadas para séries de gráfico). A forma do
// ícone também muda por severidade: a informação não depende só da cor.
const severityStyle: Record<Severity, { color: string; shape: ReactElement }> = {
  critical: { color: "#d03b3b", shape: <polygon points="4,0 8,0 12,4 12,8 8,12 4,12 0,8 0,4" /> },
  major: { color: "#ec835a", shape: <polygon points="6,0 12,12 0,12" /> },
  minor: { color: "#fab219", shape: <polygon points="6,0 12,6 6,12 0,6" /> },
  warning: { color: "#64748b", shape: <circle cx="6" cy="6" r="5.5" /> },
};

export function SeverityIcon({ severity, className = "size-3" }: { severity: Severity; className?: string }) {
  const { color, shape } = severityStyle[severity];
  return (
    <svg viewBox="0 0 12 12" className={`shrink-0 ${className}`} fill={color} aria-hidden>
      {shape}
    </svg>
  );
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-700">
      <SeverityIcon severity={severity} />
      {severityLabel[severity]}
    </span>
  );
}

export function AlarmStatusBadge({ status }: { status: AlarmStatus }) {
  const [label, style] = {
    active: ["Ativo", "bg-red-50 text-red-700 ring-red-600/20"],
    acknowledged: ["Reconhecido", "bg-sky-50 text-sky-800 ring-sky-600/20"],
    cleared: ["Encerrado", "bg-slate-100 text-slate-600 ring-slate-500/20"],
  }[status];
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}>{label}</span>;
}

/** Número de destaque: é o que a visão geral precisa, não um gráfico. */
export function StatTile({ label, value, detail, tone = "neutral", children }: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: "neutral" | "bad";
  children?: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-surface p-4 shadow-sm" aria-label={label}>
      <h2 className="text-sm text-slate-500">{label}</h2>
      <p className={`mt-1 text-3xl font-semibold tabular-nums tracking-tight ${tone === "bad" ? "text-red-700" : "text-slate-900"}`}>
        {value}
      </p>
      {detail && <p className="mt-1 text-sm text-slate-500">{detail}</p>}
      {children}
    </section>
  );
}

export function Pager({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (offset: number) => void }) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <nav className="flex items-center justify-between border-t border-slate-200 px-4 py-3 text-sm" aria-label="Paginação">
      <span className="text-slate-500">
        {offset + 1}–{Math.min(offset + limit, total)} de {total}
      </span>
      <span className="flex gap-2">
        <Button variant="secondary" disabled={page <= 1} onClick={() => onChange(offset - limit)}>
          Anterior
        </Button>
        <Button variant="secondary" disabled={page >= pages} onClick={() => onChange(offset + limit)}>
          Próxima
        </Button>
      </span>
    </nav>
  );
}

export function Card({ title, actions, children }: { title?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-surface shadow-sm">
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
          {title && <h2 className="font-medium">{title}</h2>}
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export const th = "px-4 py-3 text-left text-xs font-medium tracking-wide text-slate-500 uppercase";
export const td = "px-4 py-3";
