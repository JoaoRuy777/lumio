import type { ReactNode } from "react";
import { ThemeToggle } from "../theme";
import { Logo } from "./Logo";

const BENEFITS = [
  {
    title: "Alarmes em segundos",
    text: "Rompimento de fibra vira um alarme só, com os clientes afetados e o aviso por e-mail.",
    icon: "M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0",
  },
  {
    title: "Atendimento medido",
    text: "Chamados com responsável, linha do tempo, TME, TMA e SLA por operador.",
    icon: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2",
  },
  {
    title: "A rede no mapa",
    text: "Cada cliente no mapa, sinal piorando antes de cair e assistente de IA para o NOC.",
    icon: "m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3zM9 3v15M15 6v15",
  },
];

/** Ilustração: fibras chegando aos clientes, com pulsos de luz. */
function FiberArt() {
  const paths = ["M-20 300 C 120 300, 160 140, 420 120", "M-20 330 C 140 330, 200 220, 420 230", "M-20 360 C 160 360, 240 320, 420 340"];
  return (
    <svg viewBox="0 0 400 420" className="pointer-events-none absolute inset-x-0 bottom-0 h-[55%] w-full opacity-70" aria-hidden>
      <defs>
        <linearGradient id="fiber" x1="0" x2="1">
          <stop offset="0" stopColor="#2dd4bf" stopOpacity="0" />
          <stop offset="0.6" stopColor="#2dd4bf" stopOpacity="0.55" />
          <stop offset="1" stopColor="#5eead4" stopOpacity="0.9" />
        </linearGradient>
      </defs>
      {paths.map((d, i) => (
        <g key={d}>
          <path d={d} stroke="url(#fiber)" strokeWidth="2.2" fill="none" />
          <path
            d={d}
            stroke="#f0fdfa"
            strokeWidth="2.2"
            fill="none"
            strokeDasharray="6 120"
            className="lumio-pulse-path"
            style={{ animationDelay: `${i * 0.9}s` }}
          />
        </g>
      ))}
      {[
        [420, 120],
        [420, 230],
        [420, 340],
      ].map(([x, y]) => (
        <circle key={y} cx={x - 24} cy={y} r="4" fill="#f0fdfa" />
      ))}
    </svg>
  );
}

/** Tela de entrada: marca e benefícios à esquerda (telas largas), formulário à direita. */
export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="grid min-h-screen lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
      <section
        className="relative hidden overflow-hidden border-r border-white/10 bg-[#0b1220] px-12 py-12 text-white lg:flex lg:flex-col"
        aria-label="Sobre a Lumio"
      >
        <Logo size={40} onDark />
        <div className="relative z-10 mt-16 max-w-md">
          <h2 className="text-3xl leading-tight font-bold tracking-tight">
            Monitoramento GPON que avisa <span className="text-[#5eead4]">antes do cliente ligar</span>.
          </h2>
          <ul className="mt-10 space-y-6">
            {BENEFITS.map((b) => (
              <li key={b.title} className="flex gap-4">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-white/10 text-[#5eead4]">
                  <svg
                    viewBox="0 0 24 24"
                    className="size-5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden
                  >
                    <path d={b.icon} />
                  </svg>
                </span>
                <div>
                  <p className="font-semibold">{b.title}</p>
                  <p className="text-sm text-[#a6b0c2]">{b.text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <FiberArt />
      </section>

      <section className="relative flex items-center justify-center px-4 py-10">
        <ThemeToggle className="absolute top-4 right-4" />
        <div className="w-full max-w-sm">{children}</div>
      </section>
    </main>
  );
}
