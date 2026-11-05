import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, ApiError, type AppUser, type Me, type Role, type UserInput } from "../api";
import { Button, Card, Field, inputClass, Loading, td, th } from "../components/ui";
import { dateTime } from "../format";

export const roleLabel: Record<Role, string> = { admin: "Administrador", operator: "Operador" };
const roleHint: Record<Role, string> = {
  admin: "vê tudo e pode alterar OLTs, canais e usuários",
  operator: "vê tudo e reconhece alarmes; não altera cadastros",
};

function UserForm({ onCreated, onCancel }: { onCreated: (u: AppUser) => void; onCancel: () => void }) {
  const [form, setForm] = useState<UserInput>({ name: "", email: "", password: "", role: "admin" });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      onCreated(await api<AppUser>("/users", { method: "POST", body: form }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "não foi possível salvar");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4 p-4" aria-label="Novo usuário">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Nome">
          <input
            className={inputClass}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
            minLength={2}
            placeholder="Maria Souza"
          />
        </Field>
        <Field label="E-mail" hint="é o login do usuário">
          <input
            className={inputClass}
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            required
            placeholder="maria@seuprovedor.com.br"
          />
        </Field>
        <Field label="Senha inicial" hint="mínimo de 8 caracteres; passe para a pessoa por um canal seguro">
          <input
            className={inputClass}
            type="text"
            autoComplete="new-password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            required
            minLength={8}
          />
        </Field>
        <Field label="Papel" hint={roleHint[form.role]}>
          <select className={inputClass} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            <option value="admin">{roleLabel.admin}</option>
            <option value="operator">{roleLabel.operator}</option>
          </select>
        </Field>
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
          Criar usuário
        </Button>
      </div>
    </form>
  );
}

export function UsersPage({ me }: { me: Me }) {
  const qc = useQueryClient();
  const isAdmin = me.role === "admin";
  const [adding, setAdding] = useState(false);
  const [created, setCreated] = useState<AppUser | null>(null);
  const { data, isPending } = useQuery({ queryKey: ["users"], queryFn: () => api<{ items: AppUser[] }>("/users") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["users"] });
  const remove = useMutation({
    mutationFn: (u: AppUser) => api<void>(`/users/${u.id}`, { method: "DELETE" }),
    onSuccess: refresh,
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-slate-500">Gestão</p>
          <h1 className="text-2xl font-bold tracking-tight">Usuários</h1>
          <p className="text-sm text-slate-500">Quem acessa o painel de {me.tenant_name}. Todos veem as mesmas OLTs, ONUs e alarmes.</p>
        </div>
        {isAdmin && !adding && <Button onClick={() => setAdding(true)}>Novo usuário</Button>}
      </div>

      {created && (
        <div role="status" className="rounded-md border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
          Usuário <strong>{created.name}</strong> criado. Ele entra com o e-mail <strong>{created.email}</strong> e a senha que você
          definiu.{" "}
          <button className="underline" onClick={() => setCreated(null)}>
            fechar
          </button>
        </div>
      )}

      {adding && (
        <Card title="Novo usuário">
          <UserForm
            onCancel={() => setAdding(false)}
            onCreated={(u) => {
              setAdding(false);
              setCreated(u);
              refresh();
            }}
          />
        </Card>
      )}

      <Card>
        {isPending ? (
          <Loading rows={3} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-200 bg-slate-50">
                <tr>
                  <th className={th}>Nome</th>
                  <th className={th}>E-mail</th>
                  <th className={th}>Papel</th>
                  <th className={th}>Criado em</th>
                  <th className={th} aria-label="Ações" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data?.items.map((u) => (
                  <tr key={u.id}>
                    <td className={`${td} font-medium`}>
                      {u.name}
                      {u.id === me.user_id && <span className="ml-1.5 text-xs font-normal text-slate-500">(você)</span>}
                    </td>
                    <td className={`${td} text-slate-600`}>{u.email}</td>
                    <td className={td}>{roleLabel[u.role]}</td>
                    <td className={`${td} whitespace-nowrap text-slate-600`}>{dateTime(u.created_at)}</td>
                    <td className={`${td} text-right`}>
                      {isAdmin && u.id !== me.user_id && (
                        <Button variant="danger" onClick={() => confirm(`Remover o acesso de ${u.name}?`) && remove.mutate(u)}>
                          Remover
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
