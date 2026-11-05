import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, type ReactNode } from "react";
import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes, useLocation, useNavigate } from "react-router";
import { api, LOGOUT_EVENT, session, type Me, type Overview } from "./api";
import { LiveIndicator, LiveProvider } from "./live";
import { ThemeToggle } from "./theme";
import { Icon, type IconName } from "./components/icons";
import { Logo, LogoMark } from "./components/Logo";
import { AlarmsPage } from "./pages/AlarmsPage";
import { AccountPage } from "./pages/AccountPage";
import { AlarmPage } from "./pages/AlarmPage";
import { AuthPage } from "./pages/AuthPage";
import { OltPage } from "./pages/OltPage";
import { OltsPage } from "./pages/OltsPage";
// a tela da ONU traz o Recharts (o maior pedaço do painel): carrega só quando abrir
const OnuPage = lazy(() => import("./pages/OnuPage").then((m) => ({ default: m.OnuPage })));
import { OnusPage } from "./pages/OnusPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ReportsPage } from "./pages/ReportsPage";
import { CustomersPage } from "./pages/CustomersPage";
// mapa e modo TV trazem o Leaflet: carregam só quando abrir
const MapPage = lazy(() => import("./pages/MapPage").then((m) => ({ default: m.MapPage })));
const TvPage = lazy(() => import("./pages/TvPage").then((m) => ({ default: m.TvPage })));
import { ResetPasswordPage } from "./pages/ResetPasswordPage";
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

  // link do e-mail de "esqueci minha senha": abre logado ou não
  if (window.location.pathname === "/redefinir-senha") return <ResetPasswordPage />;
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
      <Route
        path="tv"
        element={
          <Suspense fallback={<p className="p-6 text-sm text-slate-500">Carregando…</p>}>
            <MeGate>{(me) => <TvPage me={me} />}</MeGate>
          </Suspense>
        }
      />
      <Route element={<Shell onLogout={onLogout} />}>
        <Route index element={<OverviewPage />} />
        <Route path="olts" element={<MeGate>{(me) => <OltsPage me={me} />}</MeGate>} />
        <Route path="olts/:id" element={<OltPage />} />
        <Route path="onus" element={<OnusPage />} />
        <Route
          path="mapa"
          element={
            <Suspense fallback={<p className="text-sm text-slate-500">Carregando mapa…</p>}>
              <MapPage />
            </Suspense>
          }
        />
        <Route path="clientes" element={<MeGate>{(me) => <CustomersPage me={me} />}</MeGate>} />
        <Route
          path="onus/:id"
          element={
            <Suspense fallback={<p className="text-sm text-slate-500">Carregando…</p>}>
              <OnuPage />
            </Suspense>
          }
        />
        <Route path="alarms" element={<AlarmsPage />} />
        <Route path="alarms/:id" element={<MeGate>{(me) => <AlarmPage me={me} />}</MeGate>} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="notifications" element={<MeGate>{(me) => <NotificationsPage me={me} />}</MeGate>} />
        <Route path="users" element={<MeGate>{(me) => <UsersPage me={me} />}</MeGate>} />
        <Route path="conta" element={<MeGate>{(me) => <AccountPage me={me} />}</MeGate>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

function MeGate({ children }: { children: (me: Me) => ReactNode }) {
  const { data } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });
  return data ? <>{children(data)}</> : <p className="text-sm text-slate-500">Carregando…</p>;
}

type NavItem = { to: string; label: string; icon: IconName; end?: boolean; badge?: "alarms" };
const NAV: { title: string; items: NavItem[] }[] = [
  {
    title: "Monitoramento",
    items: [
      { to: "/", label: "Visão geral", icon: "overview", end: true },
      { to: "/alarms", label: "Alarmes", icon: "alarms", badge: "alarms" },
      { to: "/mapa", label: "Mapa da rede", icon: "map" },
      { to: "/tv", label: "Modo TV", icon: "tv" },
    ],
  },
  {
    title: "Atendimento",
    items: [
      { to: "/clientes", label: "Clientes", icon: "customers" },
      { to: "/reports", label: "Relatórios", icon: "reports" },
    ],
  },
  {
    title: "Rede",
    items: [
      { to: "/olts", label: "OLTs", icon: "olts" },
      { to: "/onus", label: "ONUs", icon: "onus" },
    ],
  },
  {
    title: "Gestão",
    items: [
      { to: "/notifications", label: "Notificações", icon: "notifications" },
      { to: "/users", label: "Usuários", icon: "users" },
    ],
  },
];

const navClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors ${
    isActive ? "bg-[#2dd4bf]/15 font-semibold text-white [&_svg]:text-[#2dd4bf]" : "text-[#c9d2de] hover:bg-white/5 hover:text-white"
  }`;

function initials(name: string) {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

function Shell({ onLogout }: { onLogout: () => void }) {
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });
  // contador de alarmes no menu, sempre visível
  const { data: ov } = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/overview"), refetchInterval: 30_000 });
  const open = ov?.alarms.total ?? 0;
  // no celular o menu é uma gaveta; fecha ao trocar de página
  const [drawer, setDrawer] = useState(false);
  const location = useLocation();
  useEffect(() => setDrawer(false), [location.pathname]);

  return (
    <LiveProvider>
      <div className="min-h-screen lg:pl-60">
        {drawer && <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={() => setDrawer(false)} aria-hidden />}
        <aside
          className={`fixed inset-y-0 left-0 z-40 flex w-60 flex-col gap-6 overflow-y-auto bg-[#0b1220] px-3 py-5 transition-transform lg:translate-x-0 ${
            drawer ? "translate-x-0" : "max-lg:invisible max-lg:-translate-x-full"
          }`}
        >
          <div className="flex items-center justify-between px-2">
            <Logo size={30} onDark subtitle={me?.tenant_name} />
            <button className="rounded-md p-1 text-[#c9d2de] hover:bg-white/10 lg:hidden" onClick={() => setDrawer(false)} aria-label="Fechar menu">
              <Icon name="close" />
            </button>
          </div>
          <nav className="flex flex-col gap-5" aria-label="Principal">
            {NAV.map((group) => (
              <div key={group.title} className="flex flex-col gap-0.5">
                <span className="px-2.5 pb-1 text-[11px] font-semibold tracking-wider text-[#8a96a8] uppercase">{group.title}</span>
                {group.items.map((item) => (
                  <NavLink key={item.to} to={item.to} end={item.end} className={navClass}>
                    <Icon name={item.icon} />
                    <span className="flex-1">{item.label}</span>
                    {item.badge === "alarms" && open > 0 && (
                      <span className="rounded-full bg-red-600 px-1.5 py-0.5 text-[11px] leading-none font-bold text-white tabular-nums" aria-label={`${open} abertos`}>
                        {open}
                      </span>
                    )}
                  </NavLink>
                ))}
              </div>
            ))}
          </nav>
          {me && (
            <div className="mt-auto flex items-center gap-2.5 border-t border-white/10 px-2 pt-4">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-[#134e4a] text-xs font-semibold text-[#5eead4]" aria-hidden>
                {initials(me.name)}
              </span>
              <NavLink to="/conta" className="flex min-w-0 flex-1 flex-col leading-tight" title="Minha conta">
                <span className="truncate text-sm font-semibold text-white hover:underline">{me.name}</span>
                <span className="text-xs text-[#8a96a8]">{me.role === "admin" ? "Administrador" : "Operador"}</span>
              </NavLink>
              <button className="rounded-md p-1.5 text-[#8a96a8] hover:bg-white/10 hover:text-white" onClick={onLogout} aria-label="Sair" title="Sair">
                <Icon name="logout" className="size-4" />
              </button>
            </div>
          )}
        </aside>

        <header className="sticky top-0 z-20 border-b border-slate-200 bg-surface/95 backdrop-blur">
          <div className="flex items-center gap-3 px-4 py-2.5 lg:px-8">
            <button className="-ml-1 rounded-md p-1.5 text-slate-600 hover:bg-slate-100 lg:hidden" onClick={() => setDrawer(true)} aria-label="Abrir menu">
              <Icon name="menu" className="size-5" />
            </button>
            <span className="lg:hidden">
              <LogoMark size={26} />
            </span>
            <SearchBox />
            <div className="ml-auto flex items-center gap-3">
              <span className="hidden sm:inline">
                <LiveIndicator />
              </span>
              <ThemeToggle />
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-[1400px] px-4 py-6 lg:px-8 lg:py-8">
          <Outlet />
        </main>
      </div>
    </LiveProvider>
  );
}

/** Busca rápida: leva para Clientes (nome, código, serial, endereço ou bairro). */
function SearchBox() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  return (
    <form
      role="search"
      className="flex max-w-md flex-1 items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-500/20"
      onSubmit={(e) => {
        e.preventDefault();
        const term = q.trim();
        navigate(term ? `/clientes?q=${encodeURIComponent(term)}` : "/clientes");
      }}
    >
      <Icon name="search" className="size-4 shrink-0 text-slate-400" />
      <input
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Buscar cliente, serial ou endereço…"
        aria-label="Buscar cliente, serial ou endereço"
        className="h-9 w-full min-w-0 bg-transparent text-sm outline-none placeholder:text-slate-400"
      />
    </form>
  );
}
