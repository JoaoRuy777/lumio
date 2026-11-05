import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AlarmTable } from "../components/AlarmTable";
import { makeAlarm, renderWithQuery } from "./helpers";

afterEach(() => vi.unstubAllGlobals());

describe("alarmes no celular", () => {
  it("vira lista de cartões com assumir, abrir chamado e ONUs afetadas", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("max-width"), media: q, addEventListener() {}, removeEventListener() {} }));
    renderWithQuery(
      <AlarmTable
        alarms={[makeAlarm(), makeAlarm({ id: "a2", kind: "olt_cpu_high", severity: "major", children: 0, assigned_to: "Ana", assigned_to_id: "u1", first_assigned_at: new Date().toISOString() })]}
      />,
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const cards = within(screen.getByRole("list", { name: "Alarmes" })).getAllByRole("listitem");
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByRole("button", { name: "Assumir" })).toBeInTheDocument();
    expect(within(cards[0]).getByRole("button", { name: "Ver 16 ONUs" })).toBeInTheDocument();
    expect(within(cards[1]).queryByRole("button", { name: "Assumir" })).not.toBeInTheDocument();
    expect(within(cards[1]).getByRole("link", { name: "Abrir chamado" })).toHaveAttribute("href", "/alarms/a2");
  });
});
