import { cloneElement, useId, type ButtonHTMLAttributes, type ReactElement } from "react";
import type { CollectionStatus } from "../api";

export const inputClass =
  "w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-xs outline-none " +
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
  primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-500/50",
  secondary: "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 disabled:text-slate-400",
  danger: "border border-red-200 bg-white text-red-700 hover:bg-red-50",
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
