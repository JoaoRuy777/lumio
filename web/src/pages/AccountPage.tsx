import { useState, type FormEvent } from "react";
import { api, ApiError, session, type Me } from "../api";
import { Button, Card, Field, inputClass } from "../components/ui";
import { roleLabel } from "./UsersPage";
import { StatusPageSettings } from "../components/StatusPageSettings";

export function AccountPage({ me }: { me: Me }) {
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaved(false);
    if (form.next !== form.confirm) {
      setError("as duas senhas novas não são iguais");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const { access_token } = await api<{ access_token: string }>("/auth/password", {
        method: "POST",
        body: { current_password: form.current, new_password: form.next },
      });
      session.set(access_token); // esta sessão continua; as outras foram encerradas
      setForm({ current: "", next: "", confirm: "" });
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "não foi possível salvar");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-slate-500">Conta</p>
        <h1 className="text-2xl font-bold tracking-tight">Minha conta</h1>
        <p className="text-sm text-slate-500">
          {me.name} · {me.email} · {roleLabel[me.role]} em {me.tenant_name}
        </p>
      </div>
      <Card title="Trocar senha">
        <form onSubmit={submit} className="max-w-md space-y-4 p-4" aria-label="Trocar senha">
          <Field label="Senha atual">
            <input
              className={inputClass}
              type="password"
              autoComplete="current-password"
              required
              value={form.current}
              onChange={(e) => setForm({ ...form, current: e.target.value })}
            />
          </Field>
          <Field label="Senha nova" hint="mínimo de 8 caracteres">
            <input
              className={inputClass}
              type="password"
              autoComplete="new-password"
              minLength={8}
              required
              value={form.next}
              onChange={(e) => setForm({ ...form, next: e.target.value })}
            />
          </Field>
          <Field label="Repita a senha nova">
            <input
              className={inputClass}
              type="password"
              autoComplete="new-password"
              minLength={8}
              required
              value={form.confirm}
              onChange={(e) => setForm({ ...form, confirm: e.target.value })}
            />
          </Field>
          {error && (
            <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          )}
          {saved && (
            <p role="status" className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
              Senha alterada. Se você estava logado em outros aparelhos, lá vai pedir login de novo.
            </p>
          )}
          <Button type="submit" disabled={busy}>
            {busy ? "Salvando…" : "Trocar senha"}
          </Button>
        </form>
      </Card>
      {me.role === "admin" && <StatusPageSettings />}
    </div>
  );
}
