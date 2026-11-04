import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { ThemeToggle } from "../theme";

afterEach(() => {
  delete document.documentElement.dataset.theme;
  localStorage.clear();
});

describe("modo noturno", () => {
  it("alterna o tema e lembra a escolha", async () => {
    document.documentElement.dataset.theme = "light";
    render(<ThemeToggle />);
    await userEvent.click(screen.getByRole("button", { name: "Ativar modo noturno" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("lumio-theme")).toBe("dark");
    await userEvent.click(screen.getByRole("button", { name: "Ativar modo claro" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("lumio-theme")).toBe("light");
  });
});
