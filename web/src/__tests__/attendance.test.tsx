import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";
import type { Alarm, AttendanceReport, TimelineItem } from "../api";
import { AlarmPage } from "../pages/AlarmPage";
import { ReportsPage } from "../pages/ReportsPage";
import { makeAlarm, me, mockApi, renderWithQuery } from "./helpers";

const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();

function renderChamado(alarm: Alarm, timeline: TimelineItem[], extra: Parameters<typeof mockApi>[0] = {}) {
  const calls = mockApi({
    "GET /alarms/alarm-1": () => ({ json: alarm }),
    "GET /alarms/alarm-1/timeline": () => ({ json: timeline }),
    "GET /users": () => ({
      json: { items: [{ id: "u1", name: "Ana", email: "a@a", role: "admin", created_at: minutesAgo(999) }, { id: "u2", name: "Bruno", email: "b@b", role: "operator", created_at: minutesAgo(999) }] },
    }),
    ...extra,
  });
  renderWithQuery(
    <Routes>
      <Route path="/alarms/:id" element={<AlarmPage me={me} />} />
    </Routes>,
    { route: "/alarms/alarm-1" },
  );
  return calls;
}

describe("chamado", () => {
  it("aguardando: mostra o tempo de espera e assume", async () => {
    const calls = renderChamado(makeAlarm({ created_at: minutesAgo(5) }), [{ at: minutesAgo(5), kind: "opened", actor: null, target: null, body: null }], {
      "POST /alarms/alarm-1/assign": () => ({ json: makeAlarm({ assigned_to: "Ana", assigned_to_id: "u1", first_assigned_at: new Date().toISOString() }) }),
    });
    expect(await screen.findByText("Aguardando atendimento")).toBeInTheDocument();
    const espera = screen.getByText("Espera até assumir").closest("div")!;
    expect(within(espera).getByText(/^05:0\d$/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Assumir chamado" }));
    await waitFor(() => expect(calls.find((c) => c.key === "POST /alarms/alarm-1/assign")?.body).toEqual({}));
  });

  it("em atendimento: anota, transfere e encerra com a causa", async () => {
    const alarm = makeAlarm({ created_at: minutesAgo(30), first_assigned_at: minutesAgo(20), assigned_at: minutesAgo(20), assigned_to: "Ana", assigned_to_id: "u1", status: "acknowledged" });
    const timeline: TimelineItem[] = [
      { at: minutesAgo(30), kind: "opened", actor: null, target: null, body: null },
      { at: minutesAgo(20), kind: "assigned", actor: "Ana", target: "Ana", body: null },
      { at: minutesAgo(10), kind: "note", actor: "Ana", target: null, body: "Equipe de campo enviada" },
    ];
    const calls = renderChamado(alarm, timeline, {
      "POST /alarms/alarm-1/notes": () => ({ status: 201, json: alarm }),
      "POST /alarms/alarm-1/assign": () => ({ json: alarm }),
      "POST /alarms/alarm-1/close": () => ({ json: { ...alarm, work_closed_at: new Date().toISOString(), work_closed_by: "Ana" } }),
    });
    expect(await screen.findByText("Em atendimento")).toBeInTheDocument();
    const tma = screen.getByText("Tempo de atendimento").closest("div")!;
    expect(within(tma).getByText(/^20:0\d$/)).toBeInTheDocument();
    const lista = screen.getByRole("list", { name: "Linha do tempo" });
    expect(within(lista).getByText("Equipe de campo enviada")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Anotação"), "Cliente confirmou sem sinal");
    await userEvent.click(screen.getByRole("button", { name: "Anotar" }));
    await waitFor(() => expect(calls.find((c) => c.key === "POST /alarms/alarm-1/notes")?.body).toEqual({ body: "Cliente confirmou sem sinal" }));

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Transferir para" }), "u2");
    await userEvent.click(screen.getByRole("button", { name: "Transferir" }));
    await waitFor(() => expect(calls.find((c) => c.key === "POST /alarms/alarm-1/assign")?.body).toEqual({ user_id: "u2" }));

    await userEvent.click(screen.getByRole("button", { name: "Encerrar atendimento" }));
    expect(screen.getByText(/A falha ainda está ativa na rede/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Causa"), "power");
    await userEvent.type(screen.getByLabelText("O que foi feito"), "Disjuntor do POP religado");
    await userEvent.click(screen.getByRole("button", { name: "Encerrar" }));
    await waitFor(() =>
      expect(calls.find((c) => c.key === "POST /alarms/alarm-1/close")?.body).toEqual({ cause: "power", notes: "Disjuntor do POP religado" }),
    );
  });
});

describe("relatório de atendimento", () => {
  it("mostra TME, TMA, ranking por operador e causas", async () => {
    const rep: AttendanceReport = {
      summary: { tickets: 12, assumed: 10, unattended: 2, closed: 9, in_progress: 1, tme_min: 4.5, tma_min: 65, tma_max_min: 180, sla_assume_min: 15, assumed_within_sla_pct: 90 },
      operators: [
        { name: "Ana", taken: 7, closed: 6, open: 1, tme_min: 3, tma_min: 50, time_in_attendance_min: 400, notes: 12 },
        { name: "Bruno", taken: 3, closed: 3, open: 0, tme_min: 8, tma_min: 95, time_in_attendance_min: 285, notes: 4 },
      ],
      causes: [{ cause: "fiber_third_party", label: "Rompimento por terceiros (obra, veículo)", count: 5, pct: 55.6, tma_min: 120 }],
    };
    mockApi({
      "GET /reports/availability": () => ({ json: { overall_availability_pct: 99.9, olts: [], worst_onus: [] } }),
      "GET /reports/alarms": () => ({ json: { total: 12, open: 1, mttr_min: 30, by_kind: {}, by_severity: {}, items: [] } }),
      "GET /reports/attendance": () => ({ json: rep }),
    });
    renderWithQuery(<ReportsPage />);
    const section = await screen.findByRole("region", { name: "Atendimento da equipe" });
    await within(section).findByRole("cell", { name: "Ana" });
    expect(within(section).getByRole("region", { name: "TMA" })).toHaveTextContent("1 h 05 min");
    expect(within(section).getByRole("region", { name: "TME" })).toHaveTextContent("4 min");
    const ana = within(section).getByRole("cell", { name: "Ana" }).closest("tr")!;
    // TMA por operador também em barras
    expect(within(section).getByRole("list", { name: "TMA por operador" })).toHaveTextContent("Ana");
    expect(ana).toHaveTextContent("7");
    expect(ana).toHaveTextContent("6 h 40 min");
    expect(within(section).getByText("Rompimento por terceiros (obra, veículo)")).toBeInTheDocument();
  });
});

describe("central de alarmes", () => {
  it("em tela larga, abre o chamado no painel ao lado da lista e fecha", async () => {
    const { vi } = await import("vitest");
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("min-width"), media: q, addEventListener() {}, removeEventListener() {} }));
    const { AlarmsPage } = await import("../pages/AlarmsPage");
    const alarm = makeAlarm({ created_at: minutesAgo(12), assigned_to: "Ana", assigned_to_id: "u1", first_assigned_at: minutesAgo(10), assigned_at: minutesAgo(10) });
    const waiting = makeAlarm({ id: "alarm-2", kind: "olt_unreachable", pon: null, children: 0, created_at: minutesAgo(3) });
    mockApi({
      "GET /alarms": () => ({ json: { items: [alarm, waiting], total: 2 } }),
      "GET /auth/me": () => ({ json: me }),
      "GET /alarms/alarm-1": () => ({ json: alarm }),
      "GET /alarms/alarm-1/timeline": () => ({ json: [{ at: minutesAgo(12), kind: "opened", actor: null, target: null, body: null }] }),
      "GET /users": () => ({ json: { items: [] } }),
    });
    renderWithQuery(<AlarmsPage />, { route: "/alarms" });

    expect(await screen.findByText(/sem responsável/)).toHaveTextContent("1 sem responsável");
    await userEvent.click(screen.getByRole("link", { name: "Rompimento de fibra" }));
    const panel = await screen.findByRole("complementary", { name: "Chamado selecionado" });
    expect(await within(panel).findByText("Em atendimento")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Abrir em tela cheia" })).toHaveAttribute("href", "/alarms/alarm-1");
    expect(screen.getByRole("link", { name: "Rompimento de fibra" }).closest("tr")).toHaveAttribute("aria-current", "true");

    await userEvent.click(within(panel).getByRole("button", { name: "Fechar chamado" }));
    expect(screen.queryByRole("complementary", { name: "Chamado selecionado" })).not.toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});
