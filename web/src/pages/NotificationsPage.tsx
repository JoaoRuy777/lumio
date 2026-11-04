import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState, type FormEvent } from "react";
import { api, ApiError, type Channel, type ChannelCreated, type ChannelType, type Delivery, type Me, type Severity } from "../api";
import { Button, Card, Field, inputClass, SeverityIcon, td, th } from "../components/ui";
import { ago, dateTime, kindLabel, severityLabel } from "../format";

const SEVERITIES: Severity[] = ["critical", "major", "minor", "warning"];

const deliveryLabel: Record<Delivery["status"], [string, string]> = {
  pending: ["Na fila", "text-slate-600"],
  sending: ["Enviando", "text-slate-600"],
  sent: ["Enviado", "text-emerald-700"],
  failed: ["Falhou", "text-red-700"],
  suppressed: ["Agrupado/cancelado", "text-slate-500"],
};

function minSeverityText(s: Severity) {
  const i = SEVERITIES.indexOf(s);
  return SEVERITIES.slice(0, i + 1).map((x) => severityLabel[x].toLowerCase()).join(", ");
}

function DeliveryStatus({ d }: { d: Delivery }) {
  const [label, color] = deliveryLabel[d.status];
  return (
    <span className={`text-xs font-medium ${color}`} title={d.last_error ?? undefined}>
      {label}
      {d.status === "pending" && d.attempts > 0 && ` (tentativa ${d.attempts + 1})`}
    </span>
  );
}

function ChannelForm({ onCreated, onCancel }: { onCreated: (c: ChannelCreated) => void; onCancel: () => void }) {
  const [form, setForm] = useState({ name: "", type: "email" as ChannelType, target: "", min_severity: "major" as Severity, notify_clear: true });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      onCreated(await api<ChannelCreated>("/notification-channels", { method: "POST", body: form }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "não foi possível salvar");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4 p-4" aria-label="Novo canal">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Nome do canal">
          <input className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required placeholder="NOC por e-mail" />
        </Field>
        <Field label="Tipo">
          <select className={inputClass} value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as ChannelType, target: "" })}>
            <option value="email">E-mail</option>
            <option value="webhook">Webhook</option>
          </select>
        </Field>
        <Field label={form.type === "email" ? "E-mail" : "URL do webhook"} hint={form.type === "webhook" ? "recebe um POST JSON assinado (HMAC-SHA256)" : undefined}>
          <input
            className={inputClass}
            type={form.type === "email" ? "email" : "url"}
            value={form.target}
            onChange={(e) => setForm({ ...form, target: e.target.value })}
            required
            placeholder={form.type === "email" ? "noc@provedor.com.br" : "https://..."}
          />
        </Field>
      </div>
      <div className="flex flex-wrap items-end gap-6">
        <Field label="Avisar a partir de" hint={`recebe: ${minSeverityText(form.min_severity)}`}>
          <select className={inputClass} value={form.min_severity} onChange={(e) => setForm({ ...form, min_severity: e.target.value as Severity })}>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {severityLabel[s]}
              </option>
            ))}
          </select>
        </Field>
        <label className="flex items-center gap-2 pb-6 text-sm">
          <input type="checkbox" checked={form.notify_clear} onChange={(e) => setForm({ ...form, notify_clear: e.target.checked })} />
          Avisar também quando normalizar
        </label>
      </div>
      {error && (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel}>
          Cancelar
        </Button>
        <Button type="submit" disabled={saving}>
          Salvar canal
        </Button>
      </div>
    </form>
  );
}

function Deliveries({ channel }: { channel: Channel }) {
  const { data } = useQuery({
    queryKey: ["channels", channel.id, "deliveries"],
    queryFn: () => api<Delivery[]>(`/notification-channels/${channel.id}/deliveries`),
    refetchInterval: 5_000,
  });
  if (!data) return <p className="px-4 py-3 text-sm text-slate-500">Carregando…</p>;
  if (data.length === 0) return <p className="px-4 py-3 text-sm text-slate-500">Nenhuma entrega ainda.</p>;
  return (
    <table className="w-full text-sm" aria-label={`Entregas do canal ${channel.name}`}>
      <tbody className="divide-y divide-slate-100">
        {data.map((d) => (
          <tr key={d.id}>
            <td className="px-4 py-2 whitespace-nowrap text-slate-600" title={dateTime(d.created_at)}>
              {ago(d.created_at)}
            </td>
            <td className="px-4 py-2">
              {d.event === "test" ? "Mensagem de teste" : `${d.event === "cleared" ? "Normalizou: " : ""}${d.alarm_kind ? kindLabel[d.alarm_kind] : "alarme"}`}
            </td>
            <td className="px-4 py-2">
              <DeliveryStatus d={d} />
            </td>
            <td className="max-w-80 truncate px-4 py-2 text-xs text-slate-500" title={d.last_error ?? undefined}>
              {d.last_error}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function NotificationsPage({ me }: { me: Me }) {
  const qc = useQueryClient();
  const isAdmin = me.role === "admin";
  const [adding, setAdding] = useState(false);
  const [secret, setSecret] = useState<{ name: string; value: string } | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const { data, isPending } = useQuery({
    queryKey: ["channels"],
    queryFn: () => api<Channel[]>("/notification-channels"),
    refetchInterval: 15_000,
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["channels"] });
  const test = useMutation({
    mutationFn: (c: Channel) => api<Delivery>(`/notification-channels/${c.id}/test`, { method: "POST" }),
    onSuccess: (_, c) => {
      setOpen(c.id);
      refresh();
    },
  });
  const toggle = useMutation({
    mutationFn: (c: Channel) => api<Channel>(`/notification-channels/${c.id}`, { method: "PATCH", body: { enabled: !c.enabled } }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (c: Channel) => api<void>(`/notification-channels/${c.id}`, { method: "DELETE" }),
    onSuccess: refresh,
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Notificações</h1>
          <p className="text-sm text-slate-500">Para onde a Lumio avisa quando um alarme abre ou normaliza.</p>
        </div>
        {isAdmin && !adding && <Button onClick={() => setAdding(true)}>Novo canal</Button>}
      </div>

      {secret && (
        <div role="status" className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <p className="font-medium">Segredo do webhook "{secret.name}". Copie agora: ele não aparece de novo.</p>
          <p className="mt-1">
            Cada POST traz o cabeçalho <code>X-Lumio-Signature: sha256=…</code> (HMAC-SHA256 do corpo com este segredo).
          </p>
          <code className="mt-2 block rounded bg-white px-2 py-1 font-mono text-xs break-all select-all">{secret.value}</code>
          <button className="mt-2 text-xs underline" onClick={() => setSecret(null)}>
            Já copiei
          </button>
        </div>
      )}

      {adding && (
        <Card title="Novo canal">
          <ChannelForm
            onCancel={() => setAdding(false)}
            onCreated={({ channel, secret: s }) => {
              setAdding(false);
              if (s) setSecret({ name: channel.name, value: s });
              refresh();
            }}
          />
        </Card>
      )}

      <Card>
        {isPending ? (
          <p className="p-6 text-sm text-slate-500">Carregando…</p>
        ) : !data?.length ? (
          <p className="px-4 py-10 text-center text-sm text-slate-500">
            Nenhum canal ainda. Sem canal, os alarmes aparecem só no painel.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-200 bg-slate-50">
                <tr>
                  <th className={th}>Canal</th>
                  <th className={th}>Recebe</th>
                  <th className={th}>Última entrega</th>
                  <th className={th} aria-label="Ações" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.map((c) => (
                  <Fragment key={c.id}>
                    <tr className={c.enabled ? undefined : "opacity-60"}>
                      <td className={td}>
                        <p className="font-medium">
                          {c.name} <span className="text-xs font-normal text-slate-500">({c.type === "email" ? "e-mail" : "webhook"})</span>
                        </p>
                        <p className="font-mono text-xs break-all text-slate-500">{c.target}</p>
                      </td>
                      <td className={td}>
                        <span className="inline-flex items-center gap-1.5 text-xs">
                          <SeverityIcon severity={c.min_severity} className="size-2.5" />
                          {minSeverityText(c.min_severity)}
                        </span>
                        {!c.enabled && <p className="text-xs text-slate-500">desativado</p>}
                      </td>
                      <td className={td}>
                        {c.last_delivery ? (
                          <>
                            <DeliveryStatus d={c.last_delivery} />
                            <p className="text-xs text-slate-500">{ago(c.last_delivery.created_at)}</p>
                          </>
                        ) : (
                          <span className="text-xs text-slate-400">—</span>
                        )}
                      </td>
                      <td className={`${td} space-x-2 text-right whitespace-nowrap`}>
                        <Button variant="secondary" onClick={() => test.mutate(c)} disabled={test.isPending}>
                          Enviar teste
                        </Button>
                        <Button variant="secondary" onClick={() => setOpen(open === c.id ? null : c.id)} aria-expanded={open === c.id}>
                          Entregas
                        </Button>
                        {isAdmin && (
                          <>
                            <Button variant="secondary" onClick={() => toggle.mutate(c)}>
                              {c.enabled ? "Desativar" : "Ativar"}
                            </Button>
                            <Button variant="danger" onClick={() => confirm(`Remover o canal ${c.name}?`) && remove.mutate(c)}>
                              Remover
                            </Button>
                          </>
                        )}
                      </td>
                    </tr>
                    {open === c.id && (
                      <tr className="bg-slate-50">
                        <td colSpan={4}>
                          <Deliveries channel={c} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
