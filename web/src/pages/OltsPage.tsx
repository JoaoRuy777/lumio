import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api, type Me, type Olt, type OltList, type OltSaved } from "../api";
import { OltForm } from "../components/OltForm";
import { Button, PlanUsageBar, StatusBadge } from "../components/ui";

type Editing = { mode: "new" } | { mode: "edit"; olt: Olt } | null;

function equipment(o: Olt) {
  if (!o.vendor) return <span className="text-slate-400">—</span>;
  return `${o.vendor[0].toUpperCase()}${o.vendor.slice(1)} ${o.model ?? ""}`;
}

export function OltsPage({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<Editing>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const isAdmin = me.role === "admin";

  // atualiza sozinho: o status da coleta muda conforme o coletor trabalha
  const { data, isPending, error } = useQuery({
    queryKey: ["olts"],
    queryFn: () => api<OltList>("/olts"),
    refetchInterval: 10_000,
  });

  const remove = useMutation({
    mutationFn: (olt: Olt) => api<void>(`/olts/${olt.id}`, { method: "DELETE" }),
    onSuccess: (_, olt) => {
      setNotice({ ok: true, text: `OLT ${olt.name} removida.` });
      qc.invalidateQueries({ queryKey: ["olts"] });
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });

  function saved({ olt, discovery }: OltSaved) {
    setEditing(null);
    setNotice(
      discovery.ok
        ? { ok: true, text: `OLT ${olt.name} salva. ${discovery.pon_ports} portas PON e ${discovery.onus} ONUs descobertas.` }
        : { ok: false, text: `OLT ${olt.name} salva, mas a descoberta falhou: ${discovery.error}` },
    );
    qc.invalidateQueries({ queryKey: ["olts"] });
    qc.invalidateQueries({ queryKey: ["me"] });
  }

  const usage = data?.usage ?? me.olts;
  const atLimit = usage.used >= usage.limit;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">OLTs</h1>
          <p className="text-sm text-slate-500">Cadastro e status da coleta</p>
        </div>
        <div className="flex items-end gap-4">
          <PlanUsageBar used={usage.used} limit={usage.limit} />
          {isAdmin && (
            <Button
              onClick={() => setEditing({ mode: "new" })}
              disabled={atLimit}
              title={atLimit ? "limite do plano atingido" : undefined}
            >
              Nova OLT
            </Button>
          )}
        </div>
      </div>

      {notice && (
        <div
          role="status"
          className={`flex items-start justify-between gap-4 rounded-md px-4 py-3 text-sm ${
            notice.ok ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-900"
          }`}
        >
          <span>{notice.text}</span>
          <button className="text-xs opacity-70 hover:opacity-100" onClick={() => setNotice(null)}>
            fechar
          </button>
        </div>
      )}

      {editing && (
        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-lg font-medium">{editing.mode === "new" ? "Nova OLT" : `Editar ${editing.olt.name}`}</h2>
          <OltForm
            key={editing.mode === "edit" ? editing.olt.id : "new"}
            olt={editing.mode === "edit" ? editing.olt : undefined}
            onSaved={saved}
            onCancel={() => setEditing(null)}
          />
        </section>
      )}

      <section className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        {isPending ? (
          <p className="p-6 text-sm text-slate-500">Carregando…</p>
        ) : error ? (
          <p role="alert" className="p-6 text-sm text-red-700">
            Não foi possível carregar as OLTs: {error.message}
          </p>
        ) : data.items.length === 0 ? (
          <div className="p-10 text-center">
            <p className="font-medium">Nenhuma OLT cadastrada</p>
            <p className="mt-1 text-sm text-slate-500">
              Cadastre a primeira para a Lumio começar a coletar. Use "Testar conexão" para conferir o acesso SNMP antes de salvar.
            </p>
          </div>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs text-slate-500 uppercase">
              <tr>
                <th className="px-4 py-3 font-medium">Nome</th>
                <th className="px-4 py-3 font-medium">Endereço</th>
                <th className="px-4 py-3 font-medium">Equipamento</th>
                <th className="px-4 py-3 text-right font-medium">ONUs online</th>
                <th className="px-4 py-3 font-medium">Coleta</th>
                <th className="px-4 py-3 text-right font-medium">Alarmes</th>
                {isAdmin && <th className="px-4 py-3" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.items.map((o) => (
                <tr key={o.id}>
                  <td className="px-4 py-3 font-medium">
                    <Link to={`/olts/${o.id}`} className="hover:underline">
                      {o.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-600">
                    {o.host}:{o.snmp_port}
                  </td>
                  <td className="px-4 py-3">{equipment(o)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {o.onus_online} / {o.onus_total}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={o.collection_status} />
                    {o.last_error && o.collection_status !== "ok" && (
                      <p className="mt-1 max-w-64 truncate text-xs text-slate-500" title={o.last_error}>
                        {o.last_error}
                      </p>
                    )}
                  </td>
                  <td className={`px-4 py-3 text-right tabular-nums ${o.active_alarms ? "font-semibold text-red-700" : "text-slate-400"}`}>
                    {o.active_alarms}
                  </td>
                  {isAdmin && (
                    <td className="space-x-2 px-4 py-3 text-right whitespace-nowrap">
                      <Button variant="secondary" onClick={() => setEditing({ mode: "edit", olt: o })}>
                        Editar
                      </Button>
                      <Button
                        variant="danger"
                        onClick={() => {
                          if (confirm(`Remover a OLT ${o.name}? O histórico de leituras e alarmes dela também é apagado.`)) {
                            remove.mutate(o);
                          }
                        }}
                      >
                        Remover
                      </Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
