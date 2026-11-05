import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../App";
import { me, mockApi, renderWithQuery } from "./helpers";

const overview = {
  olts: { total: 1, ok: 1, error: 0, late: 0, pending: 0, disabled: 0 },
  onus: { total: 64, online: 64, offline: 0, unknown: 0 },
  rx_low: 0,
  rx_trend: 0,
  customers: 0,
  alarms: { critical: 2, major: 1, minor: 0, warning: 0, total: 3 },
  recent_alarms: [],
};

function setup() {
  const calls = mockApi({
    "GET /auth/me": () => ({ json: me }),
    "GET /overview": () => ({ json: overview }),
    "GET /customers": () => ({ json: { items: [], total: 0 } }),
    "GET /events": () => ({ status: 503 }),
  });
  const onLogout = vi.fn();
  renderWithQuery(<AppRoutes onLogout={onLogout} />, { route: "/conta" });
  return { calls, onLogout };
}

describe("menu lateral", () => {
  it("agrupa as telas e mostra o contador de alarmes", async () => {
    setup();
    const nav = screen.getByRole("navigation", { name: "Principal" });
    for (const group of ["Monitoramento", "Atendimento", "Rede", "Gestão"]) expect(within(nav).getByText(group)).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Mapa da rede" })).toHaveAttribute("href", "/mapa");
    expect(within(nav).getByRole("link", { name: "Modo TV" })).toHaveAttribute("href", "/tv");
    expect(await within(nav).findByRole("link", { name: /Alarmes.*3 abertos/ })).toHaveAttribute("href", "/alarms");
  });

  it("mostra quem está logado, leva para a conta e sai", async () => {
    const { onLogout } = setup();
    expect(await screen.findByRole("link", { name: /Ana.*Administrador/ })).toHaveAttribute("href", "/conta");
    expect(screen.getByText("Provedor A")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sair" }));
    expect(onLogout).toHaveBeenCalled();
  });

  it("a busca do topo procura em Clientes", async () => {
    const { calls } = setup();
    await userEvent.type(screen.getByRole("searchbox", { name: /Buscar cliente/ }), "maria{Enter}");
    await waitFor(() => expect(calls.some((c) => c.key === "GET /customers" && c.url.searchParams.get("q") === "maria")).toBe(true));
  });
});
