import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Assistant, Markdown } from "../components/Assistant";
import { mockApi, renderWithQuery } from "./helpers";

const status = { configured: true, provider: "Google Gemini", daily_limit: 40, remaining_today: 40 };

describe("assistente de IA", () => {
  it("pergunta, mostra a resposta e devolve o mapa de marcadores na próxima pergunta", async () => {
    let n = 0;
    const calls = mockApi({
      "GET /assistant/status": () => ({ json: status }),
      "POST /assistant/chat": () => ({
        json:
          n++ === 0
            ? {
                reply: "**1 crítico**: rompimento na olt-centro.\n- Cliente afetada: Maria Souza",
                mapping: { "[CLIENTE_1]": "Maria Souza" },
                tools: ["listar_alarmes", "detalhar_chamado"],
                model: "gemini-3.5-flash",
                remaining_today: 39,
              }
            : { reply: "Ela está offline.", mapping: { "[CLIENTE_1]": "Maria Souza" }, tools: ["buscar_clientes"], model: "x", remaining_today: 38 },
      }),
    });
    renderWithQuery(<Assistant />, { route: "/alarms/11111111-2222-3333-4444-555555555555" });

    await userEvent.click(screen.getByRole("button", { name: "Abrir assistente de IA" }));
    const panel = screen.getByRole("dialog", { name: "Assistente de IA" });
    expect(await within(panel).findByText(/40 de 40 perguntas hoje/)).toBeInTheDocument();
    // dentro de um chamado, sugere resumir o chamado
    await userEvent.click(within(panel).getByRole("button", { name: "Resuma este chamado e diga o próximo passo." }));

    expect(await within(panel).findByText("1 crítico")).toContainHTML("strong");
    expect(within(panel).getByText("Cliente afetada: Maria Souza").tagName).toBe("LI");
    expect(within(panel).getByText("Consultei: alarmes, chamado")).toBeInTheDocument();
    expect(within(panel).getByText(/39 de 40/)).toBeInTheDocument();
    const first = calls.find((c) => c.key === "POST /assistant/chat")!.body as Record<string, unknown>;
    expect(first.alarm_id).toBe("11111111-2222-3333-4444-555555555555");

    await userEvent.type(within(panel).getByRole("textbox", { name: "Pergunta para o assistente" }), "e a Maria?{Enter}");
    expect(await within(panel).findByText("Ela está offline.")).toBeInTheDocument();
    const second = calls.filter((c) => c.key === "POST /assistant/chat")[1].body as { mapping: object; messages: object[] };
    expect(second.mapping).toEqual({ "[CLIENTE_1]": "Maria Souza" });
    expect(second.messages).toHaveLength(3);
  });

  it("erro do provedor aparece e a pergunta volta para a caixa", async () => {
    mockApi({
      "GET /assistant/status": () => ({ json: status }),
      "POST /assistant/chat": () => ({ status: 429, json: { detail: "o limite gratuito do assistente foi atingido agora" } }),
    });
    renderWithQuery(<Assistant />);
    await userEvent.click(screen.getByRole("button", { name: "Abrir assistente de IA" }));
    const box = screen.getByRole("textbox", { name: "Pergunta para o assistente" });
    await userEvent.type(box, "oi{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("limite gratuito");
    await waitFor(() => expect(box).toHaveValue("oi"));
  });

  it("sem chave no servidor, avisa que está desligado", async () => {
    mockApi({ "GET /assistant/status": () => ({ json: { ...status, configured: false } }) });
    renderWithQuery(<Assistant />);
    await userEvent.click(screen.getByRole("button", { name: "Abrir assistente de IA" }));
    expect(await screen.findByText(/ainda não foi ligado/)).toBeInTheDocument();
  });

  it("markdown não interpreta HTML vindo da IA", () => {
    render(<Markdown text={'<img src=x onerror="alert(1)"> **ok**'} />);
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
  });
});
