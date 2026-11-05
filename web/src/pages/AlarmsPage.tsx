import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { api, query, type Alarm, type Me, type Page, type Severity } from "../api";
import { AlarmTable } from "../components/AlarmTable";
import { Ticket } from "../components/Ticket";
import { Card, Pager, SeverityIcon } from "../components/ui";
import { severityLabel } from "../format";

const LIMIT = 50;
const SEVERITIES: Severity[] = ["critical", "major", "minor", "warning"];
const TABS = [
  { key: "open", label: "Abertos" },
  { key: "mine", label: "Meus atendimentos" },
  { key: "cleared", label: "Histórico" },
] as const;
type Tab = (typeof TABS)[number]["key"];

export function AlarmsPage() {
  const [params, setParams] = useSearchParams();
  const raw = params.get("status");
  const tab: Tab = raw === "cleared" || raw === "mine" ? raw : "open";
  const severity = params.getAll("severity") as Severity[];
  const offset = Number(params.get("offset") ?? 0);
  const selected = params.get("chamado"); // chamado aberto no painel ao lado
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<Me>("/auth/me"),
    enabled: !!selected,
  });

  const { data, isPending, error } = useQuery({
    queryKey: ["alarms", tab, severity, offset],
    queryFn: () =>
      api<Page<Alarm>>(
        `/alarms${query(tab === "mine" ? { mine: true, severity, limit: LIMIT, offset } : { status: tab, severity, limit: LIMIT, offset })}`,
      ),
    refetchInterval: 30_000,
  });

  function update(changes: Record<string, string | string[] | null>) {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      next.delete(k);
      for (const item of v === null ? [] : Array.isArray(v) ? v : [v]) next.append(k, item);
    }
    if (!("offset" in changes) && !("chamado" in changes)) next.delete("offset");
    setParams(next);
  }

  const toggleSeverity = (s: Severity) =>
    update({
      severity: severity.includes(s) ? severity.filter((x) => x !== s) : [...severity, s],
    });

  const items = data?.items ?? [];
  const waiting = tab === "open" ? items.filter((a) => !a.assigned_to && !a.work_closed_at && a.status !== "cleared").length : 0;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-sm text-slate-500">Monitoramento</p>
          <h1 className="text-2xl font-bold tracking-tight">Central de alarmes</h1>
        </div>
        {tab === "open" && data && (
          <p className="text-sm text-slate-600">
            <b className="text-slate-900 tabular-nums">{data.total}</b> {data.total === 1 ? "aberto" : "abertos"}
            {waiting > 0 && (
              <>
                {" · "}
                <b className="text-amber-700 tabular-nums">{waiting}</b> sem responsável
              </>
            )}
          </p>
        )}
      </div>

      {/* filtros numa linha só, acima da lista */}
      <div className="flex flex-wrap items-center gap-4">
        <div role="tablist" className="inline-flex rounded-lg border border-slate-200 bg-surface p-0.5">
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              className={`rounded-md px-3 py-1.5 text-sm font-medium ${tab === t.key ? "bg-slate-100 text-slate-900 shadow-xs ring-1 ring-slate-200" : "text-slate-600 hover:text-slate-900"}`}
              onClick={() =>
                update({
                  status: t.key === "open" ? null : t.key,
                  chamado: null,
                })
              }
            >
              {t.label}
            </button>
          ))}
        </div>
        <fieldset className="flex flex-wrap items-center gap-2">
          <legend className="sr-only">Severidade</legend>
          {SEVERITIES.map((s) => (
            <label
              key={s}
              className={`inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${
                severity.includes(s) ? "border-brand-600 bg-brand-600 text-white" : "border-slate-300 bg-surface text-slate-700"
              }`}
            >
              <input type="checkbox" className="sr-only" checked={severity.includes(s)} onChange={() => toggleSeverity(s)} />
              <SeverityIcon severity={s} className="size-2.5" />
              {severityLabel[s]}
            </label>
          ))}
          {severity.length > 0 && (
            <button className="text-xs text-slate-500 hover:underline" onClick={() => update({ severity: null })}>
              limpar
            </button>
          )}
        </fieldset>
      </div>

      <div className={selected ? "grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(400px,460px)]" : ""}>
        <Card className="min-w-0">
          {isPending ? (
            <p className="p-6 text-sm text-slate-500">Carregando…</p>
          ) : error ? (
            <p role="alert" className="p-6 text-sm text-red-700">
              Erro ao carregar alarmes: {error.message}
            </p>
          ) : (
            <>
              <AlarmTable
                alarms={data.items}
                history={tab === "cleared"}
              compact={!!selected}
                emptyText={tab === "mine" ? "Nenhum chamado com você agora. Assuma um na aba Abertos." : undefined}
                selectedId={selected}
                onSelect={(a) => update({ chamado: a.id })}
              />
              <Pager total={data.total} limit={LIMIT} offset={offset} onChange={(o) => update({ offset: String(o) })} />
            </>
          )}
        </Card>
        {selected && (
          <aside
            className="order-first rounded-xl border border-slate-200 bg-surface p-4 xl:sticky xl:top-20 xl:order-none xl:max-h-[calc(100vh-6rem)] xl:overflow-y-auto"
            aria-label="Chamado selecionado"
          >
            {me.data ? (
              <Ticket key={selected} id={selected} me={me.data} layout="panel" onClose={() => update({ chamado: null })} />
            ) : (
              <p className="text-sm text-slate-500">Carregando…</p>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}
