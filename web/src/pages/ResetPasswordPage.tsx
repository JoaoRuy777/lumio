import { useState, type FormEvent } from "react";
import { api, ApiError, session } from "../api";
import { Button, Field, inputClass } from "../components/ui";
import { ThemeToggle } from "../theme";
import { Logo } from "../components/Logo";

/** Aberta pelo link do e-mail de "esqueci minha senha" (/redefinir-senha?token=...). */
export function ResetPasswordPage() {
  const token = new URLSearchParams(window.location.search).get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setError("as duas senhas não são iguais");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await api<void>("/auth/reset", { method: "POST", body: { token, new_password: password } });
      session.clear(); // qualquer sessão guardada neste navegador era da senha antiga
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "não foi possível falar com a API");
    } finally {
      setBusy(false);
    }
  }

  const goToLogin = () => window.location.assign("/");

  return (
    <main className="relative flex min-h-screen items-center justify-center px-4">
      <ThemeToggle className="absolute top-4 right-4" />
      <div className="w-full max-w-sm">
        <h1 className="mb-6">
          <Logo size={44} />
        </h1>
        <div className="space-y-4 rounded-xl border border-slate-200 bg-surface p-6 shadow-sm">
          <h2 className="text-lg font-medium">Criar senha nova</h2>
          {done ? (
            <>
              <p role="status" className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                Senha alterada. Entre com a senha nova.
              </p>
              <Button className="w-full" onClick={goToLogin}>
                Ir para o login
              </Button>
            </>
          ) : !token ? (
            <>
              <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
                Link incompleto. Abra o link do e-mail de novo ou peça outro na tela de login.
              </p>
              <Button variant="secondary" className="w-full" onClick={goToLogin}>
                Voltar ao login
              </Button>
            </>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              <Field label="Senha nova" hint="mínimo de 8 caracteres">
                <input className={inputClass} type="password" autoComplete="new-password" minLength={8} required value={password} onChange={(e) => setPassword(e.target.value)} />
              </Field>
              <Field label="Repita a senha nova">
                <input className={inputClass} type="password" autoComplete="new-password" minLength={8} required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
              </Field>
              {error && (
                <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
                  {error}
                </p>
              )}
              <Button type="submit" disabled={busy} className="w-full">
                {busy ? "Aguarde…" : "Salvar senha nova"}
              </Button>
            </form>
          )}
        </div>
      </div>
    </main>
  );
}
