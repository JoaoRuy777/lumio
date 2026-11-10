import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { api, ApiError, downloadFile, query, type AuditPage as AuditData, type AuditCategory, type Me } from "../api";
import { Button, Card, inputClass, Loading, Pager, td, th } from "../components/ui";
import { dateTime } from "../format";

const LIMIT = 50;
const CATEGORIES: { value: AuditCategory | ""; label: string }[] = [
  { value: "", label: "Tudo" },
  { value: "auth", label: "Acesso" },
  { value: "user", label: "Usuários" },
  { value: "olt", label: "OLTs" },
  { value: "channel", label: "Notificações" },
  { value: "escalation", label: "Escalonamento" },
  { value: "maintenance", label: "Manutenção" },
  { value: "customer", label: "Clientes" },
  { value: "status_page", label: "Página pública" },
];

// ações de segurança ganham destaque
const ALERT = new Set(["auth.login_failed", "user.delete", "olt.delete", "channel.delete", "channel.rotate_secret"]);

const FIELD: Record<string, string> = {
  role: "papel",
  host: "endereço",
  snmp_port: "porta",
  community: "community",
  name: "nome",
  type: "tipo",
  target: "destino",
  min_severity: "severidade mínima",
  notify_clear: "avisa normalização",
  enabled: "ativo",
  after_minutes: "minutos",
  channel: "canal",
  reason: "motivo",
  starts_at: "início",
  ends_at: "fim",
  created: "criados",
  updated: "atualizados",
  unmatched: "sem ONU",
  errors: "erros",
  serial: "serial",
  lat: "latitude",
  lon: "longitude",
  status_interval_s: "intervalo de status (s)",
  optical_interval_s: "intervalo óptico (s)",
};

const VALUE: Record<string, string> = {
  critical: "crítico",
  major: "grave",
  minor: "menor",
  warning: "aviso",
  admin: "administrador",
  operator: "operador",
  email: "e-mail",
};

function formatValue(v: unknown): string {
  if (typeof v === "string" && v in VALUE) return VALUE[v];
  if (typeof v === "boolean") return v ? "sim" : "não";
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return dateTime(v);
  if (v === null || v === undefined) return "—";
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}

function Details({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details);
  if (!entries.length) return <span className="text-slate-400">—</span>;
  return (
    <ul className="space-y-0.5 text-xs text-slate-600">
      {entries.map(([k, v]) => (
        <li key={k}>
          <span className="text-slate-500">{FIELD[k] ?? k}:</span> {formatValue(v)}
        </li>
      ))}
    </ul>
  );
}

/** Log de auditoria: quem fez o quê, quando e de onde (só administradores). */
export function AuditPage({ me }: { me: Me }) {
  const [params, setParams] = useSearchParams();
  const category = (params.get("categoria") ?? "") as AuditCategory | "";
  const q = params.get("q") ?? "";
  const from = params.get("de") ?? "";
  const to = params.get("ate") ?? "";
  const offset = Number(params.get("offset") ?? 0);
  const [search, setSearch] = useState(q);
  const [error, setError] = useState<string | null>(null);

  const filters = {
    category: category || undefined,
    q: q || undefined,
    from: from ? new Date(`${from}T00:00:00`).toISOString() : undefined,
    to: to ? new Date(new Date(`${to}T00:00:00`).getTime() + 86_400_000).toISOString() : undefined,
  };
  const {
    data,
    isPending,
    error: loadError,
  } = useQuery({
    queryKey: ["audit", filters, offset],
    queryFn: () => api<AuditData>(`/audit-log${query({ ...filters, limit: LIMIT, offset })}`),
    enabled: me.role === "admin",
  });

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    if (!("offset" in changes)) next.delete("offset");
    setParams(next);
  }

  async function exportCsv() {
    try {
      setError(null);
      await downloadFile(`/audit-log/export.csv${query(filters)}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "não foi possível exportar");
    }
  }

  if (me.role !== "admin") {
    return (
      <p className="rounded-xl border border-slate-200 bg-surface p-6 text-sm text-slate-600">
        Só administradores veem o log de auditoria.
      </p>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-slate-500">Gestão</p>
          <h1 className="text-2xl font-bold tracking-tight">Auditoria</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">
            Quem fez o quê, quando e de onde: acessos, usuários, OLTs, notificações, manutenções e clientes. O registro só cresce: ninguém
            altera nem apaga.
          </p>
        </div>
        <Button variant="secondary" onClick={exportCsv}>
          Exportar CSV
        </Button>
      </div>

      <div className="flex flex-col gap-3">
        <div role="group" aria-label="Categoria" className="flex flex-wrap gap-1.5">
          {CATEGORIES.map((c) => (
            <button
              key={c.value}
              type="button"
              aria-pressed={category === c.value}
              onClick={() => update({ categoria: c.value || null })}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium ${
                category === c.value
                  ? "border-brand-600 bg-brand-600 text-white"
                  : "border-slate-300 bg-surface text-slate-700 hover:bg-slate-50"
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            update({ q: search.trim() || null });
          }}
        >
          <input
            type="search"
            className={`${inputClass} max-w-xs`}
            placeholder="Buscar pessoa, alvo ou detalhe…"
            aria-label="Buscar no log"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <label className="text-xs text-slate-600">
            De
            <input type="date" className={`${inputClass} mt-0.5`} value={from} onChange={(e) => update({ de: e.target.value || null })} />
          </label>
          <label className="text-xs text-slate-600">
            Até
            <input type="date" className={`${inputClass} mt-0.5`} value={to} onChange={(e) => update({ ate: e.target.value || null })} />
          </label>
        </form>
      </div>

      {error && (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <Card>
        {isPending ? (
          <Loading rows={6} />
        ) : loadError ? (
          <p role="alert" className="p-6 text-sm text-red-700">
            Erro ao carregar: {loadError.message}
          </p>
        ) : !data.items.length ? (
          <p className="px-4 py-10 text-center text-sm text-slate-500">Nada registrado com esses filtros.</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-slate-200 bg-slate-50">
                  <tr>
                    <th className={th}>Quando</th>
                    <th className={th}>Quem</th>
                    <th className={th}>O quê</th>
                    <th className={th}>Detalhes</th>
                    <th className={th}>IP</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.items.map((e) => (
                    <tr key={e.id} className={ALERT.has(e.action) ? "shadow-[inset_4px_0_0_#ea580c]" : undefined}>
                      <td className={`${td} whitespace-nowrap text-slate-600 tabular-nums`}>{dateTime(e.at)}</td>
                      <td className={`${td} whitespace-nowrap`}>{e.actor_name ?? <span className="text-slate-400">—</span>}</td>
                      <td className={td}>
                        <p className={`font-medium ${e.action === "auth.login_failed" ? "text-orange-700" : ""}`}>{e.action_label}</p>
                        {e.target_label && <p className="text-xs text-slate-500">{e.target_label}</p>}
                      </td>
                      <td className={td}>
                        <Details details={e.details} />
                      </td>
                      <td className={`${td} font-mono text-xs whitespace-nowrap text-slate-500`}>{e.ip ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={data.total} limit={LIMIT} offset={offset} onChange={(o) => update({ offset: String(o) })} />
          </>
        )}
      </Card>
    </div>
  );
}
