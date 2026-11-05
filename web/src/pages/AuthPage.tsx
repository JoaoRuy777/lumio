import { useState, type FormEvent } from "react";
import { api, ApiError, session } from "../api";
import { ThemeToggle } from "../theme";
import { Logo } from "../components/Logo";
import { Button, Field, inputClass } from "../components/ui";

type Mode = "login" | "signup" | "forgot";

export function AuthPage({ onLogin }: { onLogin: () => void }) {
  const [mode, setMode] = useState<Mode>("login");
  const [form, setForm] = useState({ company: "", name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<string | null>(null);

  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  function switchTo(next: Mode) {
    setMode(next);
    setError(null);
    setSent(null);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "forgot") {
        const { detail } = await api<{ detail: string }>("/auth/forgot", { method: "POST", body: { email: form.email } });
        setSent(detail);
        return;
      }
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
    <main className="relative flex min-h-screen items-center justify-center px-4">
      <ThemeToggle className="absolute top-4 right-4" />
      <div className="w-full max-w-sm">
        <h1 className="mb-2">
          <Logo size={44} />
        </h1>
        <p className="mb-6 text-sm text-slate-500">Monitoramento de redes GPON para provedores</p>
        <form onSubmit={submit} className="space-y-4 rounded-xl border border-slate-200 bg-surface p-6 shadow-sm">
          <h2 className="text-lg font-medium">{{ login: "Entrar", signup: "Criar conta do provedor", forgot: "Esqueci minha senha" }[mode]}</h2>
          {mode === "forgot" && <p className="text-sm text-slate-500">Mandamos para o seu e-mail um link para criar uma senha nova.</p>}
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
          {mode !== "forgot" && (
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
          )}
          {mode === "login" && (
            <button type="button" className="-mt-2 text-sm font-medium text-brand-600 hover:underline" onClick={() => switchTo("forgot")}>
              Esqueci minha senha
            </button>
          )}
          {sent && (
            <p role="status" className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
              {sent[0].toUpperCase() + sent.slice(1)}. Confira também o spam.
            </p>
          )}
          {error && (
            <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "Aguarde…" : { login: "Entrar", signup: "Criar conta", forgot: "Enviar link" }[mode]}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-slate-500">
          {mode === "login" ? "Ainda não tem conta? " : mode === "signup" ? "Já tem conta? " : "Lembrou a senha? "}
          <button type="button" className="font-medium text-brand-600 hover:underline" onClick={() => switchTo(mode === "login" ? "signup" : "login")}>
            {mode === "login" ? "Criar conta" : "Entrar"}
          </button>
        </p>
      </div>
    </main>
  );
}
