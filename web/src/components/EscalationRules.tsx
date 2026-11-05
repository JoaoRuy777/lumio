import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, ApiError, type Channel, type EscalationRule, type Severity } from "../api";
import { severityLabel } from "../format";
import { Button, Card, Field, inputClass, SeverityIcon, td, th } from "./ui";

const LEVELS: { value: Severity; label: string }[] = [
  { value: "critical", label: "Só críticos" },
  { value: "major", label: "Graves ou piores" },
  { value: "minor", label: "Menores ou piores" },
  { value: "warning", label: "Todos" },
];

/**
 * Escalonamento: alarme sem ninguém assumir depois de X minutos avisa outro canal
 * (supervisor, gerente). Várias regras = vários níveis.
 */
export function EscalationRules({ channels, isAdmin }: { channels: Channel[]; isAdmin: boolean }) {
  const qc = useQueryClient();
  const { data: rules } = useQuery({ queryKey: ["escalation-rules"], queryFn: () => api<EscalationRule[]>("/escalation-rules") });
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", after_minutes: 15, min_severity: "critical" as Severity, channel_id: "" });
  const [error, setError] = useState<string | null>(null);

  const refresh = () => qc.invalidateQueries({ queryKey: ["escalation-rules"] });
  const create = useMutation({
    mutationFn: () => api<EscalationRule>("/escalation-rules", { method: "POST", body: form }),
    onSuccess: () => {
      setAdding(false);
      setError(null);
      setForm({ name: "", after_minutes: 15, min_severity: "critical", channel_id: "" });
      refresh();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "não foi possível salvar"),
  });
  const toggle = useMutation({
    mutationFn: (r: EscalationRule) => api<EscalationRule>(`/escalation-rules/${r.id}`, { method: "PATCH", body: { enabled: !r.enabled } }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (r: EscalationRule) => api<void>(`/escalation-rules/${r.id}`, { method: "DELETE" }),
    onSuccess: refresh,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <Card
      title="Escalonamento"
      actions={
        isAdmin &&
        !adding && (
          <Button variant="secondary" onClick={() => setAdding(true)} disabled={!channels.length}>
            Nova regra
          </Button>
        )
      }
    >
      <p className="border-b border-slate-200 px-4 py-3 text-sm text-slate-600">
        Se <b>ninguém assumir</b> um alarme dentro do prazo, a Lumio avisa um canal a mais, por exemplo o supervisor do plantão. Use várias
        regras para criar níveis (10 min → supervisor, 30 min → gerente). Alarmes em manutenção programada não escalam.
      </p>

      {adding && (
        <form
          onSubmit={submit}
          className="grid gap-4 border-b border-slate-200 p-4 md:grid-cols-2 xl:grid-cols-4"
          aria-label="Nova regra de escalonamento"
        >
          <Field label="Nome da regra">
            <input
              className={inputClass}
              required
              minLength={2}
              maxLength={80}
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Ex.: Supervisor do plantão"
            />
          </Field>
          <Field label="Sem responsável há (min)">
            <input
              type="number"
              className={inputClass}
              required
              min={1}
              max={1440}
              value={form.after_minutes}
              onChange={(e) => setForm({ ...form, after_minutes: Number(e.target.value) })}
            />
          </Field>
          <Field label="Quais alarmes">
            <select
              className={inputClass}
              value={form.min_severity}
              onChange={(e) => setForm({ ...form, min_severity: e.target.value as Severity })}
            >
              {LEVELS.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Avisar o canal">
            <select
              className={inputClass}
              required
              value={form.channel_id}
              onChange={(e) => setForm({ ...form, channel_id: e.target.value })}
            >
              <option value="">Escolha o canal…</option>
              {channels.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.type === "email" ? "e-mail" : "webhook"})
                </option>
              ))}
            </select>
          </Field>
          {error && (
            <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 md:col-span-2 xl:col-span-4">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2 md:col-span-2 xl:col-span-4">
            <Button variant="secondary" onClick={() => setAdding(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={create.isPending}>
              Salvar regra
            </Button>
          </div>
        </form>
      )}

      {!rules?.length ? (
        <p className="px-4 py-8 text-center text-sm text-slate-500">
          {channels.length
            ? "Nenhuma regra ainda: alarmes sem responsável não são escalados."
            : "Cadastre um canal antes de criar regras de escalonamento."}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                <th className={th}>Regra</th>
                <th className={th}>Quando</th>
                <th className={th}>Avisa</th>
                <th className={th}>Escalados (30 dias)</th>
                {isAdmin && <th className={th} aria-label="Ações" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rules.map((r) => (
                <tr key={r.id} className={r.enabled ? undefined : "opacity-60"}>
                  <td className={`${td} font-medium`}>
                    {r.name}
                    {!r.enabled && <span className="block text-xs font-normal text-slate-500">desligada</span>}
                  </td>
                  <td className={td}>
                    <span className="inline-flex items-center gap-1.5">
                      <SeverityIcon severity={r.min_severity} className="size-2.5" />
                      {r.min_severity === "warning"
                        ? "Qualquer alarme"
                        : `${severityLabel[r.min_severity]}${r.min_severity === "critical" ? "" : " ou pior"}`}
                    </span>
                    <span className="block text-xs text-slate-500">sem responsável há {r.after_minutes} min</span>
                  </td>
                  <td className={td}>
                    {r.channel_name} <span className="text-xs text-slate-500">({r.channel_type === "email" ? "e-mail" : "webhook"})</span>
                  </td>
                  <td className={`${td} tabular-nums`}>{r.escalations_30d}</td>
                  {isAdmin && (
                    <td className={`${td} space-x-2 text-right whitespace-nowrap`}>
                      <Button variant="secondary" onClick={() => toggle.mutate(r)}>
                        {r.enabled ? "Desligar" : "Ligar"}
                      </Button>
                      <Button variant="danger" onClick={() => confirm(`Apagar a regra ${r.name}?`) && remove.mutate(r)}>
                        Apagar
                      </Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
