import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Customer, MapData } from "../api";
import { CustomersPage } from "../pages/CustomersPage";
import { makeAlarm, me, mockApi, renderWithQuery } from "./helpers";

// o Leaflet desenha em canvas, que o jsdom não tem: o mapa vira um marcador simples
vi.mock("../components/NetworkMap", () => ({
  NetworkMap: ({ data }: { data: MapData }) => <div aria-label="Mapa da rede">{data.customers.length} pontos</div>,
}));

const customer = (over: Partial<Customer> = {}): Customer => ({
  id: "c1",
  code: "C10009",
  name: "Maria Souza",
  phone: "(14) 99999-0000",
  address: "Rua das Palmeiras, 120",
  district: "Centro",
  city: "Marília",
  plan: "500 Mega",
  lat: -22.21,
  lon: -49.94,
  serial: "HWTC0877432D",
  onu_id: "onu-1",
  olt_id: "olt-1",
  olt_name: "HW - CENTRO - 01",
  pon: "0/1/0",
  onu_index: 0,
  rx_dbm: -20.1,
  state: "online",
  ticket_id: null,
  ...over,
});

describe("clientes", () => {
  it("importa o CSV e mostra o resultado", async () => {
    const calls = mockApi({
      "GET /customers": () => ({ json: { items: [customer()], total: 1 } }),
      "POST /customers/import": () => ({ json: { created: 255, updated: 1, unmatched: 2, errors: [{ line: 7, error: "serial e nome são obrigatórios" }] } }),
    });
    renderWithQuery(<CustomersPage me={me} />);
    expect(await screen.findByText("Maria Souza")).toBeInTheDocument();
    const file = new File(["serial;nome\nHWTC1;Ana\n"], "clientes.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("Arquivo CSV de clientes"), file);
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("255 clientes novos, 1 atualizados");
    expect(status).toHaveTextContent("2 ainda sem ONU");
    expect(status).toHaveTextContent("linha 7");
    expect(calls.find((c) => c.key === "POST /customers/import")!.body).toEqual({ csv: "serial;nome\nHWTC1;Ana\n" });
  });

  it("cliente sem serviço mostra o chamado; operador não importa", async () => {
    mockApi({
      "GET /customers": () => ({ json: { items: [customer({ state: "offline", rx_dbm: null, ticket_id: "t1" })], total: 1 } }),
    });
    renderWithQuery(<CustomersPage me={{ ...me, role: "operator" }} />);
    const row = (await screen.findByText("Maria Souza")).closest("tr")!;
    expect(within(row).getByText("Sem serviço")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "ver chamado" })).toHaveAttribute("href", "/alarms/t1");
    expect(screen.queryByText("Importar clientes")).toBeNull();
  });
});

describe("mapa e modo TV", () => {
  const data: MapData = {
    olts: [{ id: "olt-1", name: "HW - ZONA SUL - 01", lat: -22.23, lon: -49.94, located: false, reachable: true, onus_total: 64, onus_online: 48, open_alarms: 1 }],
    customers: [
      customer({ id: "a", name: "Ana Lima", state: "offline", ticket_id: "t1", pon: "0/1/1", olt_name: "HW - ZONA SUL - 01" }),
      customer({ id: "b", name: "Bruno Dias", state: "offline", ticket_id: "t1", pon: "0/1/1", olt_name: "HW - ZONA SUL - 01" }),
      customer({ id: "c", name: "Carla Rocha", state: "trend" }),
      customer({ id: "d", name: "Diego Alves" }),
    ],
  };

  it("mapa lista quem está sem serviço, agrupado pelo chamado", async () => {
    mockApi({ "GET /map": () => ({ json: data }) });
    const { MapPage } = await import("../pages/MapPage");
    renderWithQuery(<MapPage />);
    const panel = (await screen.findByText("Sem serviço (2)")).closest("section")!;
    expect(within(panel).getByText(/HW - ZONA SUL - 01 · PON 0\/1\/1 · 2 clientes/)).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "chamado" })).toHaveAttribute("href", "/alarms/t1");
    expect(screen.getByText("Carla Rocha")).toBeInTheDocument();          // sinal em atenção
    expect(screen.getByRole("checkbox", { name: /Sinal piorando/ })).toBeChecked();
  });

  it("modo TV mostra os números e a fila com o cronômetro", async () => {
    const waiting = makeAlarm({ created_at: new Date(Date.now() - 20 * 60_000).toISOString(), affected_customers: 14 });
    mockApi({
      "GET /overview": () => ({
        json: { olts: { total: 5, ok: 5, error: 0, late: 0, pending: 0, disabled: 0 }, onus: { total: 256, online: 240, offline: 16, unknown: 0 }, rx_low: 0, rx_trend: 3, customers: 256, alarms: { critical: 1, major: 0, minor: 0, warning: 0, total: 1 }, recent_alarms: [] },
      }),
      "GET /alarms": () => ({ json: { items: [waiting], total: 1 } }),
      "GET /map": () => ({ json: data }),
      "GET /reports/attendance": () => ({ json: { summary: { tickets: 4, assumed: 3, unattended: 1, closed: 2, in_progress: 1, tme_min: 6, tma_min: 42, tma_max_min: 60, sla_assume_min: 15, assumed_within_sla_pct: 75 }, operators: [], causes: [] } }),
      "GET /events": () => ({ status: 503 }),
    });
    const { TvPage } = await import("../pages/TvPage");
    renderWithQuery(<TvPage me={me} />);
    await waitFor(() => expect(screen.getByRole("region", { name: "Clientes sem serviço" })).toHaveTextContent("2"));
    await waitFor(() => expect(screen.getByRole("region", { name: "ONUs online" })).toHaveTextContent("93,8%"));
    expect(screen.getByRole("region", { name: "TMA hoje" })).toHaveTextContent("42 min");
    expect(screen.getByText(/14 clientes/)).toBeInTheDocument();
    expect(screen.getByText("sem dono há mais de 15 min")).toBeInTheDocument();
    expect(screen.getByText(/3 ONUs com sinal piorando/)).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
