import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { LogoMark } from "../components/Logo";
import { ThemeToggle } from "../theme";
import { ago, duration } from "../format";

interface Incident {
  kind: "pon_fiber_cut" | "olt_unreachable";
  since: string;
  until?: string | null;
  districts: string[];
}
interface Maintenance {
  starts_at: string;
  ends_at: string;
  in_progress: boolean;
  districts: string[];
}
export interface PublicStatus {
  name: string;
  updated_at: string;
  incidents: Incident[];
  maintenance: Maintenance[];
  history: Incident[];
}

class NotFound extends Error {}

const KIND: Record<Incident["kind"], string> = {
  pon_fiber_cut: "Rompimento de fibra",
  olt_unreachable: "Falha em equipamento da rede",
};

const when = (iso: string) =>
  new Date(iso).toLocaleString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const hour = (iso: string) => new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
const places = (d: string[]) => (d.length ? d.join(", ") : "Algumas regiões");

async function load(slug: string): Promise<PublicStatus> {
  // fetch direto, sem o token de quem estiver logado: a página é pública
  const res = await fetch(`/api/public/status/${encodeURIComponent(slug)}`);
  if (res.status === 404) throw new NotFound();
  if (!res.ok) throw new Error(`erro ${res.status}`);
  return res.json();
}

/** /status/<endereço>: o cliente final vê se há interrupção no bairro dele. */
export function StatusPage({ slug }: { slug: string }) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["public-status", slug],
    queryFn: () => load(slug),
    refetchInterval: 60_000,
    retry: (n, e) => !(e instanceof NotFound) && n < 2,
  });

  useEffect(() => {
    document.title = data ? `${data.name} · Status da rede` : "Status da rede";
  }, [data]);

  return (
    <div className="min-h-screen bg-slate-50">
      <main className="mx-auto max-w-2xl px-4 py-8 sm:py-12">
        <div className="mb-8 flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-slate-500">Status da rede</p>
            <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
              {data?.name ?? (isLoading ? "Carregando…" : "Status da rede")}
            </h1>
          </div>
          <ThemeToggle />
        </div>

        {error instanceof NotFound && (
          <Panel>
            <p className="font-semibold">Página não encontrada</p>
            <p className="mt-1 text-sm text-slate-600">Confira o endereço com o seu provedor de internet.</p>
          </Panel>
        )}
        {error && !(error instanceof NotFound) && (
          <Panel>
            <p className="font-semibold">Não foi possível carregar agora</p>
            <p className="mt-1 text-sm text-slate-600">Tentaremos de novo em instantes.</p>
          </Panel>
        )}

        {data && (
          <div className="space-y-8">
            <Summary data={data} />

            {data.incidents.length > 0 && (
              <Section title="Agora">
                {data.incidents.map((i) => (
                  <Panel key={i.since + i.kind} tone="bad">
                    <p className="font-semibold">{KIND[i.kind]}</p>
                    <p className="mt-1 text-sm">
                      <span className="text-slate-600">Bairros afetados: </span>
                      <strong className="font-semibold">{places(i.districts)}</strong>
                    </p>
                    <p className="mt-1 text-sm text-slate-600">
                      Desde {hour(i.since)} ({ago(i.since)}). Nossa equipe já foi avisada e está trabalhando.
                    </p>
                  </Panel>
                ))}
              </Section>
            )}

            {data.maintenance.length > 0 && (
              <Section title="Manutenções programadas">
                {data.maintenance.map((m) => (
                  <Panel key={m.starts_at + m.districts.join()} tone="info">
                    <p className="flex flex-wrap items-center gap-2 font-semibold">
                      {when(m.starts_at)} até {when(m.ends_at)}
                      {m.in_progress && (
                        <span className="rounded-full bg-sky-200 px-2 py-0.5 text-xs font-medium text-sky-800">Em andamento</span>
                      )}
                    </p>
                    <p className="mt-1 text-sm">
                      <span className="text-slate-600">Bairros: </span>
                      <strong className="font-semibold">{places(m.districts)}</strong>
                    </p>
                    <p className="mt-1 text-sm text-slate-600">A conexão pode oscilar ou cair durante esse período.</p>
                  </Panel>
                ))}
              </Section>
            )}

            <Section title="Últimos 7 dias">
              {data.history.length === 0 ? (
                <p className="text-sm text-slate-600">Nenhuma interrupção nos últimos 7 dias.</p>
              ) : (
                <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 bg-surface">
                  {data.history.map((h) => (
                    <li key={h.since + h.kind} className="px-4 py-3 text-sm">
                      <p className="font-medium">
                        {KIND[h.kind]} · {places(h.districts)}
                      </p>
                      <p className="text-slate-600">
                        {when(h.since)} · resolvido em {duration(h.since, h.until ?? null)}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-6 text-xs text-slate-500">
              <span>Atualizado às {hour(data.updated_at)} · a página se atualiza sozinha a cada minuto</span>
              <span className="inline-flex items-center gap-1.5">
                <LogoMark size={16} /> Monitorado por Lumio
              </span>
            </footer>
          </div>
        )}
      </main>
    </div>
  );
}

function Summary({ data }: { data: PublicStatus }) {
  const working = data.maintenance.some((m) => m.in_progress);
  if (data.incidents.length) {
    const districts = new Set(data.incidents.flatMap((i) => i.districts));
    return (
      <Panel tone="bad" big>
        <p className="text-lg font-semibold">
          <span aria-hidden>● </span>Interrupção{" "}
          {districts.size ? `em ${districts.size === 1 ? "1 bairro" : `${districts.size} bairros`}` : "em parte da rede"}
        </p>
        <p className="mt-1 text-sm text-slate-600">Já sabemos do problema. Não é preciso ligar para o suporte.</p>
      </Panel>
    );
  }
  if (working)
    return (
      <Panel tone="info" big>
        <p className="text-lg font-semibold">
          <span aria-hidden>● </span>Manutenção programada em andamento
        </p>
        <p className="mt-1 text-sm text-slate-600">O resto da rede funciona normalmente.</p>
      </Panel>
    );
  return (
    <Panel tone="ok" big>
      <p className="text-lg font-semibold">
        <span aria-hidden>● </span>Tudo funcionando normalmente
      </p>
      <p className="mt-1 text-sm text-slate-600">Nenhuma interrupção conhecida na rede agora.</p>
    </Panel>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold tracking-wider text-slate-500 uppercase">{title}</h2>
      {children}
    </section>
  );
}

const TONE = {
  neutral: "border-slate-200 bg-surface",
  ok: "border-emerald-600/30 bg-emerald-50 [&>p:first-child]:text-emerald-800",
  bad: "border-red-200 bg-red-50 [&>p:first-child]:text-red-700",
  info: "border-sky-200 bg-sky-50 [&>p:first-child]:text-sky-800",
};

function Panel({ tone = "neutral", big = false, children }: { tone?: keyof typeof TONE; big?: boolean; children: React.ReactNode }) {
  return (
    <div role={big ? "status" : undefined} className={`rounded-xl border ${big ? "p-5" : "p-4"} ${TONE[tone]}`}>
      {children}
    </div>
  );
}
