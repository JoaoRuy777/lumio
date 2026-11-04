import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { api, query, type Alarm, type Page, type Severity } from "../api";
import { AlarmTable } from "../components/AlarmTable";
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

  const { data, isPending, error } = useQuery({
    queryKey: ["alarms", tab, severity, offset],
    queryFn: () =>
      api<Page<Alarm>>(`/alarms${query(tab === "mine" ? { mine: true, severity, limit: LIMIT, offset } : { status: tab, severity, limit: LIMIT, offset })}`),
    refetchInterval: 30_000,
  });

  function update(changes: Record<string, string | string[] | null>) {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      next.delete(k);
      for (const item of v === null ? [] : Array.isArray(v) ? v : [v]) next.append(k, item);
    }
    if (!("offset" in changes)) next.delete("offset");
    setParams(next);
  }

  const toggleSeverity = (s: Severity) =>
    update({ severity: severity.includes(s) ? severity.filter((x) => x !== s) : [...severity, s] });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Alarmes</h1>

      {/* filtros numa linha só, acima da lista */}
      <div className="flex flex-wrap items-center gap-4">
        <div role="tablist" className="inline-flex rounded-lg border border-slate-200 bg-surface p-0.5">
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              className={`rounded-md px-3 py-1.5 text-sm font-medium ${tab === t.key ? "bg-brand-600 text-white" : "text-slate-600 hover:text-slate-900"}`}
              onClick={() => update({ status: t.key === "open" ? null : t.key })}
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

      <Card>
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
              emptyText={tab === "mine" ? "Nenhum chamado com você agora. Assuma um na aba Abertos." : undefined}
            />
            <Pager total={data.total} limit={LIMIT} offset={offset} onChange={(o) => update({ offset: String(o) })} />
          </>
        )}
      </Card>
    </div>
  );
}
