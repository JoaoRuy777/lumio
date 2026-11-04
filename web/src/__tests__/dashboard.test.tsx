import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { session, type Overview } from "../api";
import { AlarmTable } from "../components/AlarmTable";
import { RxChart } from "../components/RxChart";
import { LiveProvider, parseSse, useLive } from "../live";
import { AlarmsPage } from "../pages/AlarmsPage";
import { OnusPage } from "../pages/OnusPage";
import { OverviewPage } from "../pages/OverviewPage";
import { makeAlarm, makeOlt, makeOnu, mockApi, renderWithQuery, sseStream } from "./helpers";

const overview = (over: Partial<Overview> = {}): Overview => ({
  olts: { total: 2, ok: 1, error: 1, late: 0, pending: 0, disabled: 0 },
  onus: { total: 128, online: 112, offline: 16, unknown: 0 },
  rx_low: 3,
  alarms: { critical: 1, major: 0, minor: 0, warning: 2, total: 3 },
  recent_alarms: [makeAlarm()],
  ...over,
});

describe("visão geral", () => {
  it("mostra os números da rede e os alarmes abertos", async () => {
    mockApi({
      "GET /overview": () => ({ json: overview() }),
      "GET /olts": () => ({ json: { items: [makeOlt()], usage: { used: 1, limit: 2 } } }),
    });
    renderWithQuery(<OverviewPage />);

    const alarms = await screen.findByRole("region", { name: "Alarmes abertos" });
    expect(within(alarms).getByText("3")).toBeInTheDocument();
    expect(within(alarms).getByText(/1 crítico/)).toBeInTheDocument();
    const onus = screen.getByRole("region", { name: "ONUs online" });
    expect(within(onus).getByText("112 / 128")).toBeInTheDocument();
    expect(within(onus).getByRole("link", { name: "16 offline" })).toHaveAttribute("href", "/onus?status=offline");
    expect(within(screen.getByRole("region", { name: "OLTs coletando" })).getByText("1 sem resposta")).toBeInTheDocument();
    // lista de alarmes recentes: severidade com texto, tipo e local
    expect(screen.getByText("Rompimento de fibra")).toBeInTheDocument();
    expect(screen.getByText("olt-centro · PON 0/1/2")).toBeInTheDocument();
    expect(screen.getByText("62/64 ONUs online")).toBeInTheDocument();
  });

  it("sem OLT cadastrada, convida a cadastrar", async () => {
    mockApi({
      "GET /overview": () => ({ json: overview({ olts: { total: 0, ok: 0, error: 0, late: 0, pending: 0, disabled: 0 } }) }),
      "GET /olts": () => ({ json: { items: [], usage: { used: 0, limit: 2 } } }),
    });
    renderWithQuery(<OverviewPage />);
    expect(await screen.findByRole("link", { name: "Cadastrar OLT" })).toHaveAttribute("href", "/olts");
  });
});

describe("tabela de alarmes", () => {
  it("severidade aparece com texto (não só cor) e o rompimento abre as ONUs afetadas", async () => {
    const calls = mockApi({
      "GET /alarms": () => ({
        json: {
          items: [
            makeAlarm({ id: "c1", kind: "onu_offline", severity: "minor", onu_id: "onu-1", onu_index: 0, onu_serial: "HWTC00000001", parent_id: "alarm-1", children: 0 }),
            makeAlarm({ id: "c2", kind: "onu_offline", severity: "minor", onu_index: 1, onu_serial: "HWTC00000002", parent_id: "alarm-1", children: 0, status: "cleared" }),
          ],
          total: 2,
        },
      }),
    });
    renderWithQuery(<AlarmTable alarms={[makeAlarm()]} />);
    expect(screen.getByText("Crítico")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Ver 16 ONUs afetadas" }));
    const list = await screen.findByRole("list", { name: "ONUs afetadas por Rompimento de fibra" });
    expect(within(list).getByRole("link", { name: "ONU 0" })).toHaveAttribute("href", "/onus/onu-1");
    expect(within(list).getByText("voltou")).toBeInTheDocument();
    expect(calls[0].url.searchParams.get("parent_id")).toBe("alarm-1");
  });

  it("assumir chama a API; chamado assumido mostra quem está com ele e o cronômetro", async () => {
    const calls = mockApi({
      "POST /alarms/alarm-1/assign": () => ({ json: makeAlarm({ status: "acknowledged", assigned_to: "Ana" }) }),
    });
    const tenMinAgo = new Date(Date.now() - 10 * 60_000).toISOString();
    renderWithQuery(
      <AlarmTable
        alarms={[
          makeAlarm(),
          makeAlarm({ id: "x", status: "acknowledged", assigned_to: "Bia", assigned_to_id: "u2", first_assigned_at: tenMinAgo }),
        ]}
      />,
    );
    // só o que ninguém pegou tem o botão; o outro mostra quem está com ele
    expect(screen.getAllByRole("button", { name: "Assumir" })).toHaveLength(1);
    expect(screen.getByText("Bia")).toBeInTheDocument();
    expect(screen.getByTitle("tempo em atendimento")).toHaveTextContent(/^10:0\d$/);
    expect(screen.getByText(/Aguardando há/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Assumir" }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /alarms/alarm-1/assign")).toBe(true));
  });

  it("filtros da tela de alarmes vão para a API e para a URL", async () => {
    const calls = mockApi({ "GET /alarms": () => ({ json: { items: [], total: 0 } }) });
    renderWithQuery(<AlarmsPage />, { route: "/alarms" });
    expect(await screen.findByText("Nenhum alarme aberto. Rede normal.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("checkbox", { name: "Crítico" }));
    await userEvent.click(screen.getByRole("tab", { name: "Histórico" }));
    await screen.findByText("Nenhum alarme no período.");
    const last = calls[calls.length - 1].url.searchParams;
    expect(last.get("status")).toBe("cleared");
    expect(last.getAll("severity")).toEqual(["critical"]);
  });
});

describe("ONUs", () => {
  it("filtros montam a consulta e a lista mostra situação e sinal", async () => {
    const calls = mockApi({
      "GET /olts": () => ({ json: { items: [makeOlt()], usage: { used: 1, limit: 2 } } }),
      "GET /onus": () => ({
        json: {
          items: [makeOnu({ online: false, rx_dbm: null, active_alarms: ["onu_offline"] }), makeOnu({ id: "onu-2", serial: "HWTCAAAA0002", rx_dbm: -28.3, active_alarms: ["onu_rx_low"] })],
          total: 2,
        },
      }),
    });
    renderWithQuery(<OnusPage />, { route: "/onus?status=offline" });

    expect(await screen.findByText("-28,3 dBm")).toHaveClass("text-red-700");
    expect(within(screen.getByRole("table")).getByText("Offline")).toBeInTheDocument();
    expect(screen.getByText("Sinal baixo")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "GET /onus")!.url.searchParams.get("status")).toBe("offline");

    await userEvent.click(screen.getByRole("checkbox", { name: /Só sinal abaixo de -27 dBm/ }));
    await waitFor(() => expect(calls[calls.length - 1].url.searchParams.get("rx_below")).toBe("-27"));
  });

  it("gráfico de potência tem alternativa em tabela", async () => {
    renderWithQuery(
      <RxChart
        hours={24}
        readings={{ bucket_s: 0, items: [{ ts: "2026-11-04T10:00:00Z", rx_dbm: -21.5, tx_dbm: 2.2 }, { ts: "2026-11-04T10:05:00Z", rx_dbm: -27.6, tx_dbm: 2.2 }] }}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Ver como tabela" }));
    const table = screen.getByRole("table", { name: "Potência recebida (RX) por horário" });
    expect(within(table).getByText("-27,6 dBm")).toHaveClass("text-red-700");      // abaixo do limite
    expect(within(table).getAllByRole("row")).toHaveLength(3);
  });
});

describe("tempo real", () => {
  beforeEach(() => session.set("tok"));

  it("parseSse separa eventos e guarda o pedaço incompleto", () => {
    const { events, rest } = parseSse('retry: 3000\nevent: ready\ndata: {}\n\n: ping\n\ndata: {"a":1}\n\ndata: {"b"');
    expect(events).toEqual([{ event: "ready", data: "{}" }, { event: "message", data: '{"a":1}' }]);
    expect(rest).toBe('data: {"b"');
  });

  function Status() {
    const { status, fresh } = useLive();
    return <p data-testid="live">{status}:{[...fresh].join(",")}</p>;
  }

  it("aviso de alarme novo recarrega as telas e destaca o alarme", async () => {
    const sse = sseStream();
    const calls = mockApi({ "GET /events": () => ({ stream: sse.stream }) });
    const { client } = renderWithQuery(
      <LiveProvider>
        <Status />
      </LiveProvider>,
    );
    await waitFor(() => expect(calls[0]?.key).toBe("GET /events"));
    expect(calls[0].auth).toBe("Bearer tok");                 // token no cabeçalho, não na URL

    act(() => sse.push("event: ready\ndata: {}\n\n"));
    await waitFor(() => expect(screen.getByTestId("live")).toHaveTextContent("live:"));

    const spy = vi.spyOn(client, "invalidateQueries");
    act(() => sse.event({ type: "alarm.opened", alarm_id: "a-9", kind: "pon_fiber_cut", severity: "critical" }));
    await waitFor(() => expect(screen.getByTestId("live")).toHaveTextContent("live:a-9"));
    const keys = spy.mock.calls.map(([f]) => f?.queryKey);
    expect(keys).toContainEqual(["alarms"]);
    expect(keys).toContainEqual(["overview"]);
  });

  it("conexão caída mostra que está sem tempo real e tenta de novo", async () => {
    let attempts = 0;
    mockApi({
      "GET /events": () => {
        attempts++;
        return { status: 503, json: { detail: "tempo real desativado" } };
      },
    });
    renderWithQuery(
      <LiveProvider retryMs={10}>
        <Status />
      </LiveProvider>,
    );
    await waitFor(() => expect(attempts).toBeGreaterThanOrEqual(2));
    expect(screen.getByTestId("live").textContent).toMatch(/offline|connecting/);
  });
});
