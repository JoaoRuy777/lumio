import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { OltsPage } from "../pages/OltsPage";
import { makeOlt, me, mockApi, renderWithQuery } from "./helpers";

describe("lista de OLTs", () => {
  it("mostra status da coleta, ONUs, alarmes e uso do plano", async () => {
    mockApi({
      "GET /olts": () => ({
        json: {
          items: [makeOlt(), makeOlt({ id: "2", name: "olt-norte", collection_status: "error", last_error: "timeout" })],
          usage: { used: 2, limit: 2 },
        },
      }),
    });
    renderWithQuery(<OltsPage me={me} />);

    const row = (await screen.findByText("olt-centro")).closest("tr")!;
    expect(within(row).getByText("Coletando")).toBeInTheDocument();
    expect(within(row).getByText("62 / 64")).toBeInTheDocument();
    expect(within(row).getByText("Huawei MA5800-X7")).toBeInTheDocument();
    const other = screen.getByText("olt-norte").closest("tr")!;
    expect(within(other).getByText("Sem resposta")).toBeInTheDocument();
    expect(within(other).getByText("timeout")).toBeInTheDocument();

    expect(screen.getByText("2 de 2 OLTs")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nova OLT" })).toBeDisabled();
  });

  it("estado vazio convida a cadastrar", async () => {
    mockApi({ "GET /olts": () => ({ json: { items: [], usage: { used: 0, limit: 2 } } }) });
    renderWithQuery(<OltsPage me={{ ...me, olts: { used: 0, limit: 2 } }} />);
    expect(await screen.findByText("Nenhuma OLT cadastrada")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nova OLT" })).toBeEnabled();
  });

  it("operador vê a lista mas não altera o cadastro", async () => {
    mockApi({ "GET /olts": () => ({ json: { items: [makeOlt()], usage: { used: 1, limit: 2 } } }) });
    renderWithQuery(<OltsPage me={{ ...me, role: "operator" }} />);
    await screen.findByText("olt-centro");
    expect(screen.queryByRole("button", { name: "Nova OLT" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Editar" })).toBeNull();
  });

  it("remove com confirmação", async () => {
    const calls = mockApi({
      "GET /olts": () => ({ json: { items: [makeOlt()], usage: { used: 1, limit: 2 } } }),
      "DELETE /olts/olt-1-id": () => ({ status: 204 }),
      "GET /auth/me": () => ({ json: me }),
    });
    vi.stubGlobal("confirm", vi.fn(() => true));
    renderWithQuery(<OltsPage me={me} />);
    await userEvent.click(await screen.findByRole("button", { name: "Remover" }));
    expect(await screen.findByText("OLT olt-centro removida.")).toBeInTheDocument();
    expect(calls.some((c) => c.key === "DELETE /olts/olt-1-id")).toBe(true);
  });
});

describe("cadastro de OLT", () => {
  async function fillForm() {
    await userEvent.type(screen.getByLabelText("Nome"), "olt-centro");
    await userEvent.type(screen.getByLabelText("Endereço (IP ou nome)"), "simulator");
    const port = screen.getByLabelText("Porta");
    await userEvent.clear(port);
    await userEvent.type(port, "16101");
    await userEvent.type(screen.getByLabelText("Community"), "public");
  }

  it("testar conexão mostra fabricante, modelo, portas e ONUs", async () => {
    const calls = mockApi({
      "GET /olts": () => ({ json: { items: [], usage: { used: 0, limit: 2 } } }),
      "POST /olts/test-connection": () => ({
        json: { ok: true, vendor: "huawei", model: "MA5800-X7", sys_name: "olt-centro", pon_ports: ["0/1/0", "0/1/1"], onus: 64 },
      }),
    });
    renderWithQuery(<OltsPage me={{ ...me, olts: { used: 0, limit: 2 } }} />);
    await userEvent.click(await screen.findByRole("button", { name: "Nova OLT" }));

    const testButton = screen.getByRole("button", { name: "Testar conexão" });
    expect(testButton).toBeDisabled();                 // sem endereço e community ainda
    await fillForm();
    await userEvent.click(testButton);

    expect(await screen.findByText(/Huawei MA5800-X7/)).toBeInTheDocument();
    expect(screen.getByText(/2 portas PON · 64 ONUs/)).toBeInTheDocument();
    const call = calls.find((c) => c.key === "POST /olts/test-connection")!;
    expect(call.body).toEqual({ host: "simulator", snmp_port: 16101, community: "public" });
  });

  it("salva e mostra o resultado da descoberta", async () => {
    const calls = mockApi({
      "GET /olts": () => ({ json: { items: [], usage: { used: 0, limit: 2 } } }),
      "GET /auth/me": () => ({ json: me }),
      "POST /olts": () => ({
        status: 201,
        json: { olt: makeOlt(), discovery: { ok: true, pon_ports: 4, onus: 64, error: null } },
      }),
    });
    renderWithQuery(<OltsPage me={{ ...me, olts: { used: 0, limit: 2 } }} />);
    await userEvent.click(await screen.findByRole("button", { name: "Nova OLT" }));
    await fillForm();
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));

    expect(await screen.findByText(/4 portas PON e 64 ONUs descobertas/)).toBeInTheDocument();
    const call = calls.find((c) => c.key === "POST /olts")!;
    expect(call.body).toEqual({
      name: "olt-centro", host: "simulator", snmp_port: 16101, community: "public",
      status_interval_s: 60, optical_interval_s: 300, enabled: true,
    });
    expect(screen.queryByRole("form", { name: "Nova OLT" })).toBeNull();
  });

  it("mostra erro de validação da API", async () => {
    mockApi({
      "GET /olts": () => ({ json: { items: [], usage: { used: 0, limit: 2 } } }),
      "POST /olts": () => ({ status: 409, json: { detail: "já existe uma OLT chamada 'olt-centro'" } }),
    });
    renderWithQuery(<OltsPage me={{ ...me, olts: { used: 0, limit: 2 } }} />);
    await userEvent.click(await screen.findByRole("button", { name: "Nova OLT" }));
    await fillForm();
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("já existe uma OLT chamada");
  });

  it("na edição, community em branco mantém a salva e não é enviada", async () => {
    const calls = mockApi({
      "GET /olts": () => ({ json: { items: [makeOlt()], usage: { used: 1, limit: 2 } } }),
      "GET /auth/me": () => ({ json: me }),
      "POST /olts/olt-1-id/test-connection": () => ({ json: { ok: false, error: "sem resposta SNMP" } }),
      "PATCH /olts/olt-1-id": () => ({ json: { olt: makeOlt({ name: "Centro" }), discovery: { ok: true, pon_ports: 0, onus: 0, error: null } } }),
    });
    renderWithQuery(<OltsPage me={me} />);
    await userEvent.click(await screen.findByRole("button", { name: "Editar" }));

    await userEvent.click(screen.getByRole("button", { name: "Testar conexão" }));
    expect(await screen.findByText("sem resposta SNMP")).toBeInTheDocument();

    const name = screen.getByLabelText("Nome");
    await userEvent.clear(name);
    await userEvent.type(name, "Centro");
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await screen.findByText(/OLT Centro salva/);
    const patch = calls.find((c) => c.key === "PATCH /olts/olt-1-id")!;
    expect(patch.body).not.toHaveProperty("community");
    expect(patch.body).toMatchObject({ name: "Centro" });
  });
});
