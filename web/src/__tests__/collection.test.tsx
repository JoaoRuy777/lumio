import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "../App";
import { me, mockApi, renderWithQuery } from "./helpers";

function setup(health: object) {
  mockApi({
    "GET /auth/me": () => ({ json: me }),
    "GET /overview": () => ({ json: { olts: {}, onus: {}, alarms: { total: 0 }, recent_alarms: [] } }),
    "GET /overview/collection": () => ({ json: health }),
    "GET /events": () => ({ status: 503 }),
  });
  renderWithQuery(<AppRoutes onLogout={() => {}} />, { route: "/conta" });
}

describe("aviso de coleta parada", () => {
  it("mostra a faixa quando nenhuma OLT manda leitura", async () => {
    setup({ stopped: true, last_reading_at: "2026-11-06T05:16:00Z", olts: 5 });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Coleta parada");
    expect(alert).toHaveTextContent("coletor está ligado");
  });

  it("não mostra nada com a coleta em dia", async () => {
    setup({ stopped: false, last_reading_at: new Date().toISOString(), olts: 5 });
    await screen.findByRole("navigation", { name: "Principal" });
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText(/Coleta parada/)).not.toBeInTheDocument();
  });
});
