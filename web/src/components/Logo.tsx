import { useId } from "react";

/**
 * Marca da Lumio: uma fibra que dobra e forma o "L", com pulsos de luz
 * passando e um ponto aceso na ponta (a luz chegando ao cliente).
 *
 * `onDark`: versão para fundo escuro (menu lateral, modo TV, ícone da aba).
 * Sem ela, as cores seguem o tema (variáveis --color-logo-*).
 */
export function LogoMark({ size = 32, onDark = false, className = "" }: { size?: number; onDark?: boolean; className?: string }) {
  const glow = useId();
  const fiber = onDark ? "#2dd4bf" : "var(--color-logo-fiber)";
  const spark = onDark ? "#f0fdfa" : "var(--color-logo-spark)";
  const halo = onDark ? "#5eead4" : "var(--color-logo-fiber)";
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" className={className} aria-hidden>
      <defs>
        <radialGradient id={glow}>
          <stop offset="0" stopColor={halo} stopOpacity="0.9" />
          <stop offset="1" stopColor={halo} stopOpacity="0" />
        </radialGradient>
      </defs>
      <path d="M13 6V29a9 9 0 0 0 9 9h14" stroke={fiber} strokeWidth="5" fill="none" strokeLinecap="round" />
      {size >= 28 && (
        <path d="M13 6V29a9 9 0 0 0 9 9h14" stroke={spark} strokeWidth="1.4" fill="none" strokeLinecap="round" strokeDasharray="3 7" opacity="0.8" />
      )}
      <circle cx="38" cy="38" r="9" fill={`url(#${glow})`} />
      <circle cx="38.5" cy="38" r="2.8" fill={spark} />
    </svg>
  );
}

/** Marca + nome, para login, menu e modo TV. */
export function Logo({ size = 32, onDark = false, subtitle }: { size?: number; onDark?: boolean; subtitle?: string }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <LogoMark size={size} onDark={onDark} />
      <span className="flex flex-col leading-tight">
        <span
          className={`font-bold tracking-tight ${onDark ? "text-white" : "text-slate-900"}`}
          style={{ fontSize: Math.round(size * 0.58) }}
        >
          Lumio
        </span>
        {subtitle && <span className={`text-xs ${onDark ? "text-[#8a96a8]" : "text-slate-500"}`}>{subtitle}</span>}
      </span>
    </span>
  );
}
