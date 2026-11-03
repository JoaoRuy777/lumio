import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, LOGOUT_EVENT, session, type Me } from "./api";
import { AuthPage } from "./pages/AuthPage";
import { OltsPage } from "./pages/OltsPage";

export function App() {
  const [loggedIn, setLoggedIn] = useState(() => session.get() !== null);
  const qc = useQueryClient();

  useEffect(() => {
    // token expirado/inválido em qualquer chamada: volta para o login
    const onLogout = () => {
      setLoggedIn(false);
      qc.clear();
    };
    window.addEventListener(LOGOUT_EVENT, onLogout);
    return () => window.removeEventListener(LOGOUT_EVENT, onLogout);
  }, [qc]);

  if (!loggedIn) return <AuthPage onLogin={() => setLoggedIn(true)} />;
  return (
    <Shell
      onLogout={() => {
        session.clear();
        qc.clear();
        setLoggedIn(false);
      }}
    />
  );
}

function Shell({ onLogout }: { onLogout: () => void }) {
  const { data: me, error } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-baseline gap-3">
            <span className="text-lg font-semibold tracking-tight text-brand-700">Lumio</span>
            {me && <span className="text-sm text-slate-500">{me.tenant_name}</span>}
          </div>
          <div className="flex items-center gap-3 text-sm">
            {me && <span className="hidden text-slate-600 sm:inline">{me.name}</span>}
            <button className="text-slate-500 hover:text-slate-800" onClick={onLogout}>
              Sair
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">
        {error ? (
          <p role="alert" className="text-sm text-red-700">
            Erro ao carregar a conta: {error.message}
          </p>
        ) : me ? (
          <OltsPage me={me} />
        ) : (
          <p className="text-sm text-slate-500">Carregando…</p>
        )}
      </main>
    </div>
  );
}
