import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { AuditEntry } from "../api";
import { AuditPage } from "../pages/AuditPage";
import { me, mockApi, renderWithQuery } from "./helpers";

const entry = (over: Partial<AuditEntry> = {}): AuditEntry => ({
  id: "e1",
  at: "2026-11-05T13:00:00Z",
  actor_id: "u1",
  actor_name: "Ana",
  action: "olt.update",
  action_label: "Alterou OLT",
  target_type: "olt",
  target_id: "o1",
  target_label: "olt-centro",
  details: { community: "(alterada)", status_interval_s: 30 },
  ip: "200.150.10.20",
  ...over,
});

describe("auditoria", () => {
  it("lista quem fez o quê e filtra por categoria", async () => {
    const calls = mockApi({
      "GET /audit-log": (_, url) => ({
        json:
          url.searchParams.get("category") === "auth"
            ? { items: [entry({ id: "e2", action: "auth.login_failed", action_label: "Errou a senha ao entrar", target_label: "ana@a.com.br", details: {} })], total: 1 }
            : { items: [entry()], total: 1 },
      }),
    });
    renderWithQuery(<AuditPage me={me} />, { route: "/auditoria" });

    const row = (await screen.findByText("Alterou OLT")).closest("tr")!;
    expect(row).toHaveTextContent("Ana");
    expect(row).toHaveTextContent("olt-centro");
    expect(row).toHaveTextContent("community: (alterada)");
    expect(row).toHaveTextContent("intervalo de status (s): 30");
    expect(row).toHaveTextContent("200.150.10.20");

    await userEvent.click(screen.getByRole("button", { name: "Acesso" }));
    expect(await screen.findByText("Errou a senha ao entrar")).toBeInTheDocument();
    await waitFor(() => expect(calls.at(-1)?.url.searchParams.get("category")).toBe("auth"));
    expect(screen.getByRole("button", { name: "Acesso" })).toHaveAttribute("aria-pressed", "true");
  });

  it("operador não vê o log", () => {
    mockApi({});
    renderWithQuery(<AuditPage me={{ ...me, role: "operator" }} />);
    expect(screen.getByText("Só administradores veem o log de auditoria.")).toBeInTheDocument();
  });
});
