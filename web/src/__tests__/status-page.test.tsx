import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { StatusPage, type PublicStatus } from "../pages/StatusPage";
import { AccountPage } from "../pages/AccountPage";
import { me, mockApi, renderWithQuery } from "./helpers";

const now = new Date().toISOString();
const base: PublicStatus = { name: "Fibra Sul", updated_at: now, incidents: [], maintenance: [], history: [] };

function open(status: PublicStatus | null) {
  const calls = mockApi({
    "GET /public/status/fibrasul": () => (status ? { json: status } : { status: 404, json: { detail: "página não encontrada" } }),
  });
  renderWithQuery(<StatusPage slug="fibrasul" />);
  return calls;
}

describe("página pública de status", () => {
  it("rede normal, sem mandar o token de quem estiver logado", async () => {
    localStorage.setItem("lumio.token", "segredo");
    const calls = open(base);
    expect(await screen.findByRole("heading", { name: "Fibra Sul" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Tudo funcionando normalmente");
    expect(screen.getByText("Nenhuma interrupção nos últimos 7 dias.")).toBeInTheDocument();
    expect(calls[0].auth).toBeNull();
    localStorage.removeItem("lumio.token");
  });

  it("rompimento mostra os bairros afetados e o histórico", async () => {
    const since = new Date(Date.now() - 20 * 60_000).toISOString();
    open({
      ...base,
      incidents: [{ kind: "pon_fiber_cut", since, districts: ["Centro", "Vila Nova"] }],
      history: [{ kind: "olt_unreachable", since: "2026-11-09T10:00:00Z", until: "2026-11-09T10:12:00Z", districts: [] }],
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Interrupção em 2 bairros");
    expect(screen.getByText("Rompimento de fibra")).toBeInTheDocument();
    expect(screen.getByText("Centro, Vila Nova")).toBeInTheDocument();
    expect(screen.getByText(/há 20 min/)).toBeInTheDocument();
    expect(screen.getByText(/Falha em equipamento da rede · Algumas regiões/)).toBeInTheDocument();
    expect(screen.getByText(/resolvido em 12 min/)).toBeInTheDocument();
  });

  it("manutenção em andamento", async () => {
    open({
      ...base,
      maintenance: [{ starts_at: now, ends_at: new Date(Date.now() + 3600_000).toISOString(), in_progress: true, districts: ["Jardim"] }],
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Manutenção programada em andamento");
    expect(screen.getByText("Em andamento")).toBeInTheDocument();
    expect(screen.getByText("Jardim")).toBeInTheDocument();
  });

  it("endereço desligado ou inexistente", async () => {
    open(null);
    expect(await screen.findByText("Página não encontrada")).toBeInTheDocument();
  });
});

describe("configuração da página pública", () => {
  it("o admin liga, troca o endereço e vê o link", async () => {
    const calls = mockApi({
      "GET /status-page": () => ({ json: { enabled: false, slug: "rnet-d9a64a" } }),
      "PUT /status-page": (body) => ({ json: body }),
    });
    renderWithQuery(<AccountPage me={me} />);
    const slug = await screen.findByRole("textbox", { name: /Endereço/ });
    await userEvent.click(screen.getByRole("checkbox", { name: "Página pública ligada" }));
    await userEvent.clear(slug);
    await userEvent.type(slug, "RNet");
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => expect(calls.find((c) => c.key === "PUT /status-page")?.body).toEqual({ enabled: true, slug: "rnet" }));
    expect(await screen.findByRole("link", { name: /\/status\/rnet$/ })).toHaveAttribute("href", `${window.location.origin}/status/rnet`);
  });

  it("operador não vê o cartão", () => {
    mockApi({});
    renderWithQuery(<AccountPage me={{ ...me, role: "operator" }} />);
    expect(screen.queryByText("Página pública de status")).not.toBeInTheDocument();
  });
});
