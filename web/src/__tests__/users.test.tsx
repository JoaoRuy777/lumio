import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { AppUser } from "../api";
import { UsersPage } from "../pages/UsersPage";
import { me, mockApi, renderWithQuery } from "./helpers";

const ana: AppUser = { id: "u1", name: "Ana", email: "admin@a.com.br", role: "admin", created_at: "2026-11-04T12:00:00Z" };
const noc: AppUser = { id: "u2", name: "Bruno", email: "noc@a.com.br", role: "operator", created_at: "2026-11-04T13:00:00Z" };

describe("usuários", () => {
  it("lista os usuários e só deixa remover os outros", async () => {
    mockApi({ "GET /users": () => ({ json: { items: [ana, noc] } }) });
    renderWithQuery(<UsersPage me={me} />);
    const self = (await screen.findByText("(você)")).closest("tr")!;
    expect(within(self).queryByRole("button", { name: "Remover" })).toBeNull();
    const other = screen.getByText("noc@a.com.br").closest("tr")!;
    expect(within(other).getByText("Operador")).toBeInTheDocument();
    expect(within(other).getByRole("button", { name: "Remover" })).toBeInTheDocument();
  });

  it("administrador cria usuário com o papel escolhido", async () => {
    const calls = mockApi({
      "GET /users": () => ({ json: { items: [ana] } }),
      "POST /users": (body) => ({ status: 201, json: { ...(body as object), id: "u3", created_at: "2026-11-04T14:00:00Z" } }),
    });
    renderWithQuery(<UsersPage me={me} />);
    await userEvent.click(await screen.findByRole("button", { name: "Novo usuário" }));
    await userEvent.type(screen.getByLabelText("Nome"), "Prof. Avaliador");
    await userEvent.type(screen.getByLabelText("E-mail"), "avaliador@unimar.br");
    await userEvent.type(screen.getByLabelText("Senha inicial"), "senha-banca-2026");
    await userEvent.click(screen.getByRole("button", { name: "Criar usuário" }));

    expect(await screen.findByRole("status")).toHaveTextContent("avaliador@unimar.br");
    expect(calls.find((c) => c.key === "POST /users")!.body).toEqual({
      name: "Prof. Avaliador", email: "avaliador@unimar.br", password: "senha-banca-2026", role: "admin",
    });
  });

  it("operador vê a lista mas não cria nem remove", async () => {
    mockApi({ "GET /users": () => ({ json: { items: [ana, noc] } }) });
    renderWithQuery(<UsersPage me={{ ...me, user_id: "u2", role: "operator" }} />);
    await screen.findByText("noc@a.com.br");
    expect(screen.queryByRole("button", { name: "Novo usuário" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remover" })).toBeNull();
  });
});
