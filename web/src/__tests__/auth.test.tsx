import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { session } from "../api";
import { AuthPage } from "../pages/AuthPage";
import { mockApi } from "./helpers";

describe("tela de login", () => {
  it("entra e guarda o token", async () => {
    const calls = mockApi({ "POST /auth/login": () => ({ json: { access_token: "tok-123" } }) });
    const onLogin = vi.fn();
    render(<AuthPage onLogin={onLogin} />);

    await userEvent.type(screen.getByLabelText("E-mail"), "admin@a.com.br");
    await userEvent.type(screen.getByLabelText("Senha"), "senha-forte-123");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));

    expect(onLogin).toHaveBeenCalled();
    expect(session.get()).toBe("tok-123");
    expect(calls[0].body).toEqual({ email: "admin@a.com.br", password: "senha-forte-123" });
  });

  it("mostra o erro da API sem entrar", async () => {
    mockApi({ "POST /auth/login": () => ({ status: 401, json: { detail: "e-mail ou senha incorretos" } }) });
    const onLogin = vi.fn();
    render(<AuthPage onLogin={onLogin} />);

    await userEvent.type(screen.getByLabelText("E-mail"), "admin@a.com.br");
    await userEvent.type(screen.getByLabelText("Senha"), "errada");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("e-mail ou senha incorretos");
    expect(onLogin).not.toHaveBeenCalled();
    expect(session.get()).toBeNull();
  });

  it("cria a conta do provedor", async () => {
    const calls = mockApi({ "POST /auth/signup": () => ({ status: 201, json: { access_token: "novo" } }) });
    render(<AuthPage onLogin={() => {}} />);

    await userEvent.click(screen.getByRole("button", { name: "Criar conta" }));
    await userEvent.type(screen.getByLabelText("Empresa (provedor)"), "Fibra Norte");
    await userEvent.type(screen.getByLabelText("Seu nome"), "Ana");
    await userEvent.type(screen.getByLabelText("E-mail"), "ana@fibranorte.com.br");
    await userEvent.type(screen.getByLabelText("Senha"), "senha-forte-123");
    await userEvent.click(screen.getByRole("button", { name: "Criar conta" }));

    expect(calls[0].key).toBe("POST /auth/signup");
    expect(calls[0].body).toMatchObject({ company: "Fibra Norte", name: "Ana" });
    expect(session.get()).toBe("novo");
  });
});
