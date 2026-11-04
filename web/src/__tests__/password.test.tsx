import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { session } from "../api";
import { AccountPage } from "../pages/AccountPage";
import { AuthPage } from "../pages/AuthPage";
import { ResetPasswordPage } from "../pages/ResetPasswordPage";
import { me, mockApi, renderWithQuery } from "./helpers";

afterEach(() => {
  window.history.replaceState(null, "", "/");
  localStorage.clear();
});

describe("senha", () => {
  it("esqueci minha senha pede o e-mail e não diz se ele existe", async () => {
    const calls = mockApi({
      "POST /auth/forgot": () => ({ status: 202, json: { detail: "se o e-mail estiver cadastrado, enviamos um link para redefinir a senha" } }),
    });
    renderWithQuery(<AuthPage onLogin={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Esqueci minha senha" }));
    expect(screen.queryByLabelText("Senha")).toBeNull();
    await userEvent.type(screen.getByLabelText("E-mail"), "ana@provedor.com.br");
    await userEvent.click(screen.getByRole("button", { name: "Enviar link" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Se o e-mail estiver cadastrado");
    expect(calls.find((c) => c.key === "POST /auth/forgot")!.body).toEqual({ email: "ana@provedor.com.br" });
  });

  it("link do e-mail cria a senha nova", async () => {
    window.history.replaceState(null, "", "/redefinir-senha?token=abc123token");
    session.set("token-antigo");
    const calls = mockApi({ "POST /auth/reset": () => ({ status: 204 }) });
    renderWithQuery(<ResetPasswordPage />);
    await userEvent.type(screen.getByLabelText("Senha nova"), "senha-nova-456");
    await userEvent.type(screen.getByLabelText("Repita a senha nova"), "senha-nova-456");
    await userEvent.click(screen.getByRole("button", { name: "Salvar senha nova" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Senha alterada");
    expect(calls.find((c) => c.key === "POST /auth/reset")!.body).toEqual({ token: "abc123token", new_password: "senha-nova-456" });
    expect(session.get()).toBeNull();
  });

  it("link vencido mostra o motivo", async () => {
    window.history.replaceState(null, "", "/redefinir-senha?token=abc123token");
    mockApi({ "POST /auth/reset": () => ({ status: 400, json: { detail: "link inválido ou vencido; peça um novo" } }) });
    renderWithQuery(<ResetPasswordPage />);
    await userEvent.type(screen.getByLabelText("Senha nova"), "senha-nova-456");
    await userEvent.type(screen.getByLabelText("Repita a senha nova"), "senha-nova-456");
    await userEvent.click(screen.getByRole("button", { name: "Salvar senha nova" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("link inválido ou vencido");
  });

  it("minha conta troca a senha e guarda a sessão nova", async () => {
    const calls = mockApi({ "POST /auth/password": () => ({ json: { access_token: "token-novo", token_type: "bearer" } }) });
    renderWithQuery(<AccountPage me={me} />);
    await userEvent.type(screen.getByLabelText("Senha atual"), "senha-forte-123");
    await userEvent.type(screen.getByLabelText("Senha nova"), "senha-nova-456");
    await userEvent.type(screen.getByLabelText("Repita a senha nova"), "senha-diferente");
    await userEvent.click(screen.getByRole("button", { name: "Trocar senha" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("não são iguais");
    expect(calls.length).toBe(0);

    await userEvent.clear(screen.getByLabelText("Repita a senha nova"));
    await userEvent.type(screen.getByLabelText("Repita a senha nova"), "senha-nova-456");
    await userEvent.click(screen.getByRole("button", { name: "Trocar senha" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Senha alterada");
    expect(session.get()).toBe("token-novo");
  });
});
