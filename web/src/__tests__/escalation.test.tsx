import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Channel, EscalationRule } from "../api";
import { AlarmTable } from "../components/AlarmTable";
import { EscalationRules } from "../components/EscalationRules";
import { makeAlarm, mockApi, renderWithQuery } from "./helpers";

const channel: Channel = {
  id: "c1",
  name: "Supervisor",
  type: "email",
  target: "sup@a.com.br",
  min_severity: "critical",
  notify_clear: true,
  enabled: true,
  created_at: "2026-11-01T00:00:00Z",
  last_delivery: null,
};
const rule: EscalationRule = {
  id: "r1",
  name: "Gerente",
  min_severity: "major",
  after_minutes: 30,
  channel_id: "c1",
  channel_name: "Supervisor",
  channel_type: "email",
  enabled: true,
  created_at: "2026-11-01T00:00:00Z",
  escalations_30d: 4,
};

describe("escalonamento", () => {
  it("lista as regras e cria uma nova", async () => {
    const calls = mockApi({
      "GET /escalation-rules": () => ({ json: [rule] }),
      "POST /escalation-rules": () => ({ status: 201, json: { ...rule, id: "r2", name: "Supervisor do plantão" } }),
    });
    renderWithQuery(<EscalationRules channels={[channel]} isAdmin />);
    const row = (await screen.findByText("Gerente")).closest("tr")!;
    expect(row).toHaveTextContent("Grave ou pior");
    expect(row).toHaveTextContent("sem responsável há 30 min");
    expect(row).toHaveTextContent("4");

    await userEvent.click(screen.getByRole("button", { name: "Nova regra" }));
    const form = screen.getByRole("form", { name: "Nova regra de escalonamento" });
    await userEvent.type(within(form).getByLabelText("Nome da regra"), "Supervisor do plantão");
    const minutes = within(form).getByLabelText("Sem responsável há (min)");
    await userEvent.clear(minutes);
    await userEvent.type(minutes, "10");
    await userEvent.selectOptions(within(form).getByLabelText("Avisar o canal"), "c1");
    await userEvent.click(within(form).getByRole("button", { name: "Salvar regra" }));
    await waitFor(() =>
      expect(calls.find((c) => c.key === "POST /escalation-rules")?.body).toEqual({
        name: "Supervisor do plantão",
        after_minutes: 10,
        min_severity: "critical",
        channel_id: "c1",
      }),
    );
  });

  it("operador vê as regras sem os botões de alterar; alarme escalado ganha selo", async () => {
    mockApi({ "GET /escalation-rules": () => ({ json: [rule] }) });
    renderWithQuery(
      <>
        <EscalationRules channels={[channel]} isAdmin={false} />
        <AlarmTable alarms={[makeAlarm({ escalated_at: new Date().toISOString() })]} />
      </>,
    );
    expect(await screen.findByText("Gerente")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Nova regra" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apagar" })).not.toBeInTheDocument();
    expect(screen.getByTitle(/Ninguém assumiu a tempo/)).toHaveTextContent("Escalonado");
  });
});
