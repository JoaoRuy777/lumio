import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, type ReactNode } from "react";
import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes } from "react-router";
import { api, LOGOUT_EVENT, session, type Me, type Overview } from "./api";
import { LiveIndicator, LiveProvider } from "./live";
import { ThemeToggle } from "./theme";
import { AlarmsPage } from "./pages/AlarmsPage";
import { AuthPage } from "./pages/AuthPage";
import { OltPage } from "./pages/OltPage";
import { OltsPage } from "./pages/OltsPage";
// a tela da ONU traz o Recharts (o maior pedaço do painel): carrega só quando abrir
const OnuPage = lazy(() => import("./pages/OnuPage").then((m) => ({ default: m.OnuPage })));
import { OnusPage } from "./pages/OnusPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ReportsPage } from "./pages/ReportsPage";
import { UsersPage } from "./pages/UsersPage";

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
  const logout = () => {
    session.clear();
    qc.clear();
    setLoggedIn(false);
  };
  return (
    <BrowserRouter>
      <AppRoutes onLogout={logout} />
    </BrowserRouter>
  );
}

export function AppRoutes({ onLogout }: { onLogout: () => void }) {
  return (
    <Routes>
      <Route element={<Shell onLogout={onLogout} />}>
        <Route index element={<OverviewPage />} />
        <Route path="olts" element={<MeGate>{(me) => <OltsPage me={me} />}</MeGate>} />
        <Route path="olts/:id" element={<OltPage />} />
        <Route path="onus" element={<OnusPage />} />
        <Route
          path="onus/:id"
          element={
            <Suspense fallback={<p className="text-sm text-slate-500">Carregando…</p>}>
              <OnuPage />
            </Suspense>
          }
        />
        <Route path="alarms" element={<AlarmsPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="notifications" element={<MeGate>{(me) => <NotificationsPage me={me} />}</MeGate>} />
        <Route path="users" element={<MeGate>{(me) => <UsersPage me={me} />}</MeGate>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

function MeGate({ children }: { children: (me: Me) => ReactNode }) {
  const { data } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });
  return data ? <>{children(data)}</> : <p className="text-sm text-slate-500">Carregando…</p>;
}

const navClass = ({ isActive }: { isActive: boolean }) =>
  `whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium ${isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:text-slate-900"}`;

function Shell({ onLogout }: { onLogout: () => void }) {
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });
  // contador de alarmes no menu, sempre visível
  const { data: ov } = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/overview"), refetchInterval: 30_000 });
  const open = ov?.alarms.total ?? 0;

  return (
    <LiveProvider>
      <div className="min-h-screen">
        <header className="border-b border-slate-200 bg-surface">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3">
            <div className="flex items-baseline gap-3">
              <span className="text-lg font-semibold tracking-tight text-brand-700">Lumio</span>
              {me && <span className="text-sm text-slate-500">{me.tenant_name}</span>}
            </div>
            <div className="flex items-center gap-4 text-sm">
              <LiveIndicator />
              <ThemeToggle />
              {me && <span className="hidden text-slate-600 sm:inline">{me.name}</span>}
              <button className="text-slate-500 hover:text-slate-800" onClick={onLogout}>
                Sair
              </button>
            </div>
          </div>
          <nav className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-4 pb-2" aria-label="Principal">
            <NavLink to="/" end className={navClass}>
              Visão geral
            </NavLink>
            <NavLink to="/alarms" className={navClass}>
              Alarmes
              {open > 0 && (
                <span className="ml-1.5 rounded-full bg-red-600 px-1.5 py-0.5 text-xs text-white tabular-nums" aria-label={`${open} abertos`}>
                  {open}
                </span>
              )}
            </NavLink>
            <NavLink to="/olts" className={navClass}>
              OLTs
            </NavLink>
            <NavLink to="/onus" className={navClass}>
              ONUs
            </NavLink>
            <NavLink to="/reports" className={navClass}>
              Relatórios
            </NavLink>
            <NavLink to="/notifications" className={navClass}>
              Notificações
            </NavLink>
            <NavLink to="/users" className={navClass}>
              Usuários
            </NavLink>
          </nav>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-8">
          <Outlet />
        </main>
      </div>
    </LiveProvider>
  );
}
