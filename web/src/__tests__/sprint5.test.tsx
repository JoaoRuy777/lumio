import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Channel } from "../api";
import { NotificationsPage } from "../pages/NotificationsPage";
import { periodParams, ReportsPage } from "../pages/ReportsPage";
import { me, mockApi, renderWithQuery } from "./helpers";

const channel = (over: Partial<Channel> = {}): Channel => ({
  id: "ch-1",
  name: "NOC",
  type: "email",
  target: "noc@provedor.com.br",
  min_severity: "major",
  notify_clear: true,
  enabled: true,
  created_at: new Date().toISOString(),
  last_delivery: { id: "d1", event: "opened", status: "failed", attempts: 6, last_error: "SMTP: conexão recusada", created_at: new Date().toISOString(), sent_at: null, alarm_kind: "pon_fiber_cut", alarm_severity: "critical" },
  ...over,
});

describe("notificações", () => {
  it("lista canais com o que cada um recebe e a última entrega", async () => {
    mockApi({ "GET /notification-channels": () => ({ json: [channel()] }) });
    renderWithQuery(<NotificationsPage me={me} />);
    const row = (await screen.findByText("NOC")).closest("tr")!;
    expect(within(row).getByText("crítico, grave")).toBeInTheDocument();
    expect(within(row).getByText("Falhou")).toHaveAttribute("title", "SMTP: conexão recusada");
  });

  it("cria webhook e mostra o segredo uma única vez", async () => {
    const calls = mockApi({
      "GET /notification-channels": () => ({ json: [] }),
      "POST /notification-channels": (body) => ({
        status: 201,
        json: { channel: channel({ ...(body as object), id: "ch-2", last_delivery: null }), secret: "s3gr3do-123" },
      }),
    });
    renderWithQuery(<NotificationsPage me={me} />);
    await userEvent.click(await screen.findByRole("button", { name: "Novo canal" }));
    await userEvent.type(screen.getByLabelText("Nome do canal"), "Integração");
    await userEvent.selectOptions(screen.getByLabelText("Tipo"), "webhook");
    await userEvent.type(screen.getByLabelText("URL do webhook"), "https://hooks.provedor.com.br/lumio");
    await userEvent.selectOptions(screen.getByLabelText("Avisar a partir de"), "critical");
    await userEvent.click(screen.getByRole("button", { name: "Salvar canal" }));

    expect(await screen.findByText("s3gr3do-123")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /notification-channels")!.body).toEqual({
      name: "Integração", type: "webhook", target: "https://hooks.provedor.com.br/lumio", min_severity: "critical", notify_clear: true,
    });
    await userEvent.click(screen.getByRole("button", { name: "Já copiei" }));
    expect(screen.queryByText("s3gr3do-123")).toBeNull();
  });

  it("enviar teste abre a lista de entregas", async () => {
    const calls = mockApi({
      "GET /notification-channels": () => ({ json: [channel({ last_delivery: null })] }),
      "POST /notification-channels/ch-1/test": () => ({ status: 202, json: { id: "t1", event: "test", status: "pending" } }),
      "GET /notification-channels/ch-1/deliveries": () => ({
        json: [{ id: "t1", event: "test", status: "sent", attempts: 1, last_error: null, created_at: new Date().toISOString(), sent_at: new Date().toISOString(), alarm_kind: null, alarm_severity: null }],
      }),
    });
    renderWithQuery(<NotificationsPage me={me} />);
    await userEvent.click(await screen.findByRole("button", { name: "Enviar teste" }));
    const table = await screen.findByRole("table", { name: "Entregas do canal NOC" });
    expect(within(table).getByText("Mensagem de teste")).toBeInTheDocument();
    expect(within(table).getByText("Enviado")).toBeInTheDocument();
    expect(calls.some((c) => c.key === "POST /notification-channels/ch-1/test")).toBe(true);
  });

  it("operador envia teste mas não cria nem remove canal", async () => {
    mockApi({ "GET /notification-channels": () => ({ json: [channel()] }) });
    renderWithQuery(<NotificationsPage me={{ ...me, role: "operator" }} />);
    await screen.findByText("NOC");
    expect(screen.queryByRole("button", { name: "Novo canal" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remover" })).toBeNull();
    expect(screen.getByRole("button", { name: "Enviar teste" })).toBeEnabled();
  });
});

describe("relatórios", () => {
  it("período: presets e datas escolhidas (o 'até' inclui o dia todo)", () => {
    const now = new Date("2026-11-04T15:00:00Z");
    expect(periodParams("7", "", "", now)).toEqual({ from: "2026-10-28T15:00:00.000Z", to: "2026-11-04T15:00:00.000Z" });
    const custom = periodParams("custom", "2026-11-01", "2026-11-03")!;
    expect(new Date(custom.to).getTime() - new Date(custom.from).getTime()).toBe(3 * 86_400_000);
    expect(periodParams("custom", "2026-11-05", "2026-11-01")).toBeNull();
  });

  it("mostra os números e baixa CSV/PDF com o token", async () => {
    const calls = mockApi({
      "GET /reports/availability": (_, url) =>
        url.searchParams.get("format")
          ? { json: {} }
          : {
              json: {
                period: { from: "", to: "" },
                overall_availability_pct: 99.95,
                olts: [{ olt: "Centro", onus: 64, availability_pct: 99.9, onu_downtime_min: 92.2, onu_outages: 17, fiber_cuts: 1, olt_management_pct: 100, olt_unreachable_min: 0 }],
                worst_onus: [{ olt: "Centro", pon: "0/1/2", onu: 3, serial: "HWTC0003", availability_pct: 99.1, downtime_min: 13, outages: 2 }],
              },
            },
      "GET /reports/alarms": () => ({
        json: { period: { from: "", to: "" }, total: 5, open: 1, mttr_min: 12.5, by_kind: { pon_fiber_cut: 1, onu_offline: 4 }, by_severity: {} },
      }),
    });
    const createObjectURL = vi.fn(() => "blob:x");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
    renderWithQuery(<ReportsPage />);

    expect(await screen.findByText("99,95 %")).toBeInTheDocument();
    expect(screen.getByText("12,5 min")).toBeInTheDocument();
    expect(screen.getByText("Rompimento de fibra")).toBeInTheDocument();
    expect(screen.getByText(/13 min fora em 2 quedas/)).toBeInTheDocument();

    const [csvButton] = screen.getAllByRole("button", { name: "Baixar CSV" });
    await userEvent.click(csvButton);
    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    const dl = calls.find((c) => c.url.searchParams.get("format") === "csv")!;
    expect(dl.key).toBe("GET /reports/availability");
    expect(dl.url.searchParams.get("from")).toMatch(/Z$/);          // com fuso
  });
});
