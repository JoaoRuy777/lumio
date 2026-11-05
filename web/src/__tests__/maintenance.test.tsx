import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { MaintenanceWindow } from "../api";
import { AlarmTable } from "../components/AlarmTable";
import { MaintenanceBanner } from "../components/MaintenanceBanner";
import { MaintenancePage } from "../pages/MaintenancePage";
import { makeAlarm, makeOlt, mockApi, renderWithQuery } from "./helpers";

const inMinutes = (m: number) => new Date(Date.now() + m * 60_000).toISOString();
const win = (over: Partial<MaintenanceWindow> = {}): MaintenanceWindow => ({
  id: "w1",
  olt_id: "olt-1-id",
  olt_name: "olt-centro",
  pon_id: "pon-2",
  pon: "0/1/2",
  reason: "Troca do splitter",
  starts_at: inMinutes(-10),
  ends_at: inMinutes(50),
  created_by: "Ana",
  created_at: inMinutes(-20),
  cancelled_at: null,
  state: "active",
  alarms_silenced: 2,
  ...over,
});

describe("manutenção programada", () => {
  it("agenda uma janela para uma PON e encerra a que está em andamento", async () => {
    const calls = mockApi({
      "GET /olts": () => ({ json: { items: [makeOlt()], usage: { used: 1, limit: 2 } } }),
      "GET /olts/olt-1-id/pons": () => ({ json: [{ id: "pon-2", name: "0/1/2", onus_total: 16, onus_online: 16 }] }),
      "GET /maintenance": () => ({ json: [win(), win({ id: "w0", state: "finished", reason: "Firmware", pon: null, pon_id: null })] }),
      "POST /maintenance": () => ({ status: 201, json: win({ id: "w2", state: "scheduled" }) }),
      "POST /maintenance/w1/end": () => ({ json: win({ state: "finished" }) }),
    });
    renderWithQuery(<MaintenancePage />);

    expect(await screen.findByText("olt-centro · PON 0/1/2")).toBeInTheDocument();
    expect(screen.getByText("olt-centro (OLT inteira)")).toBeInTheDocument();

    const form = screen.getByRole("form", { name: "Agendar manutenção" });
    await userEvent.selectOptions(within(form).getByLabelText("OLT"), "olt-1-id");
    await waitFor(() => expect(within(form).getByRole("option", { name: "PON 0/1/2" })).toBeInTheDocument());
    await userEvent.selectOptions(within(form).getByLabelText("Abrangência"), "pon-2");
    await userEvent.type(within(form).getByLabelText("Motivo"), "Troca do splitter da Rua 7");
    await userEvent.click(within(form).getByRole("button", { name: "1 h" }));
    await userEvent.click(within(form).getByRole("button", { name: "Agendar" }));

    await waitFor(() => expect(calls.some((c) => c.key === "POST /maintenance")).toBe(true));
    const body = calls.find((c) => c.key === "POST /maintenance")!.body as Record<string, string>;
    expect(body).toMatchObject({ olt_id: "olt-1-id", pon_id: "pon-2", reason: "Troca do splitter da Rua 7" });
    expect(new Date(body.ends_at).getTime() - new Date(body.starts_at).getTime()).toBe(3_600_000);
    expect(await screen.findByRole("status")).toHaveTextContent("Manutenção agendada: olt-centro · PON 0/1/2.");

    await userEvent.click(screen.getByRole("button", { name: "Encerrar agora" }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /maintenance/w1/end")).toBe(true));
  }, 15_000); // digita bastante: com a suíte inteira em paralelo passa dos 5 s padrão

  it("faixa de aviso e selo no alarme silenciado", async () => {
    mockApi({ "GET /maintenance": () => ({ json: [win()] }) });
    renderWithQuery(
      <>
        <MaintenanceBanner />
        <AlarmTable alarms={[makeAlarm({ maintenance_id: "w1", maintenance_reason: "Troca do splitter" })]} />
      </>,
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Manutenção em andamento");
    expect(screen.getByRole("status")).toHaveTextContent("olt-centro · PON 0/1/2");
    expect(screen.getByTitle(/Manutenção programada: Troca do splitter/)).toHaveTextContent("Manutenção");
  });
});
