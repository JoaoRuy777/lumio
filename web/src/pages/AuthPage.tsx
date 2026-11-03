import { useState, type FormEvent } from "react";
import { api, ApiError, session } from "../api";
import { Button, Field, inputClass } from "../components/ui";

type Mode = "login" | "signup";

export function AuthPage({ onLogin }: { onLogin: () => void }) {
  const [mode, setMode] = useState<Mode>("login");
  const [form, setForm] = useState({ company: "", name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const body = mode === "login" ? { email: form.email, password: form.password } : form;
      const { access_token } = await api<{ access_token: string }>(`/auth/${mode}`, { method: "POST", body });
      session.set(access_token);
      onLogin();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "não foi possível falar com a API");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <h1 className="mb-1 text-3xl font-semibold tracking-tight text-brand-700">Lumio</h1>
        <p className="mb-6 text-sm text-slate-500">Monitoramento de OLTs para provedores</p>
        <form onSubmit={submit} className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-medium">{mode === "login" ? "Entrar" : "Criar conta do provedor"}</h2>
          {mode === "signup" && (
            <>
              <Field label="Empresa (provedor)">
                <input className={inputClass} value={form.company} onChange={set("company")} required minLength={2} />
              </Field>
              <Field label="Seu nome">
                <input className={inputClass} value={form.name} onChange={set("name")} required minLength={2} />
              </Field>
            </>
          )}
          <Field label="E-mail">
            <input className={inputClass} type="email" value={form.email} onChange={set("email")} required autoComplete="email" />
          </Field>
          <Field label="Senha" hint={mode === "signup" ? "mínimo de 8 caracteres" : undefined}>
            <input
              className={inputClass}
              type="password"
              value={form.password}
              onChange={set("password")}
              required
              minLength={mode === "signup" ? 8 : undefined}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
            />
          </Field>
          {error && (
            <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "Aguarde…" : mode === "login" ? "Entrar" : "Criar conta"}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-slate-500">
          {mode === "login" ? "Ainda não tem conta? " : "Já tem conta? "}
          <button
            type="button"
            className="font-medium text-brand-600 hover:underline"
            onClick={() => {
              setMode(mode === "login" ? "signup" : "login");
              setError(null);
            }}
          >
            {mode === "login" ? "Criar conta" : "Entrar"}
          </button>
        </p>
      </div>
    </main>
  );
}
