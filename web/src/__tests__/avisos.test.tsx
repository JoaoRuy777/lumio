import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { AppRoutes } from "../App";
import { CriticalAlerts } from "../components/CriticalAlerts";
import { ALARM_EVENT } from "../live";
import { ToastProvider } from "../toast";
import { me, mockApi, renderWithQuery } from "./helpers";

afterEach(() => localStorage.clear());

const fire = (detail: object) => act(() => void window.dispatchEvent(new CustomEvent(ALARM_EVENT, { detail })));

describe("avisos", () => {
  it("alarme crítico novo aparece na tela; menor não", async () => {
    renderWithQuery(
      <ToastProvider>
        <CriticalAlerts />
      </ToastProvider>,
    );
    fire({ type: "alarm.opened", alarm_id: "a1", kind: "onu_offline", severity: "minor" });
    fire({ type: "alarm.opened", alarm_id: "a2", kind: "pon_fiber_cut", severity: "critical" });
    expect(await screen.findByText("Novo alarme crítico: Rompimento de fibra")).toBeInTheDocument();
    expect(screen.queryByText(/ONU offline/)).not.toBeInTheDocument();
  });

  it("o sino liga e desliga o alerta sonoro e lembra a escolha", async () => {
    renderWithQuery(
      <ToastProvider>
        <CriticalAlerts />
      </ToastProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Ligar alerta sonoro de alarmes críticos" }));
    expect(localStorage.getItem("lumio-alert-sound")).toBe("on");
    expect(await screen.findByText("Alerta sonoro de críticos ligado")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Desligar alerta sonoro de alarmes críticos" })).toHaveAttribute("aria-pressed", "true");
  });

  it("título da aba mostra quantos alarmes estão abertos", async () => {
    mockApi({
      "GET /auth/me": () => ({ json: me }),
      "GET /overview": () => ({
        json: { olts: { total: 1, ok: 1, error: 0, late: 0, pending: 0, disabled: 0 }, onus: { total: 1, online: 1, offline: 0, unknown: 0 }, rx_low: 0, rx_trend: 0, customers: 0, alarms: { critical: 2, major: 1, minor: 0, warning: 0, total: 3 }, recent_alarms: [] },
      }),
      "GET /events": () => ({ status: 503 }),
    });
    renderWithQuery(<AppRoutes onLogout={() => {}} />, { route: "/conta" });
    await waitFor(() => expect(document.title).toBe("(3) Lumio · Monitoramento GPON"));
  });
});
