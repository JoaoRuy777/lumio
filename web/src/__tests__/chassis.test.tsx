import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ChassisPon } from "../api";
import { OltChassis } from "../components/OltChassis";
import { renderWithQuery } from "./helpers";

const onus = (state: ChassisPon["onus"][number]["state"], n: number, prefix: string) =>
  Array.from({ length: n }, (_, i) => ({ id: `${prefix}${i}`, onu_index: i, serial: `HWTC${prefix}${i}`, state, rx_dbm: -21.4, customer: i === 0 ? "Maria Souza" : null }));

describe("chassi da OLT", () => {
  it("uma linha por PON, um quadrado por ONU; rompimento destacado", () => {
    const pons: ChassisPon[] = [
      { id: "p0", name: "0/1/0", onus: [...onus("online", 6, "a"), ...onus("low", 1, "b"), ...onus("trend", 1, "c")], fiber_cut: false, in_maintenance: false },
      { id: "p1", name: "0/1/1", onus: onus("offline", 8, "d"), fiber_cut: true, in_maintenance: true },
    ];
    renderWithQuery(<OltChassis pons={pons} oltId="olt-1" />);

    const ok = screen.getByRole("list", { name: "ONUs da PON 0/1/0" });
    expect(within(ok).getAllByRole("link")).toHaveLength(8);
    const cut = screen.getByLabelText("PON 0/1/1");
    expect(cut).toHaveTextContent("Rompimento de fibra");
    expect(cut).toHaveTextContent("Em manutenção");
    expect(cut).toHaveTextContent("0/8 online");
    expect(screen.getByLabelText("PON 0/1/0")).toHaveTextContent("8/8 online");

    const first = within(ok).getByRole("link", { name: "ONU 0: Online" });
    expect(first).toHaveAttribute("href", "/onus/a0");
    expect(first.getAttribute("title")).toContain("Maria Souza");
    expect(first.getAttribute("title")).toContain("-21,4 dBm");
    // legenda com as contagens
    const legend = screen.getByRole("list", { name: "Legenda" });
    expect(legend).toHaveTextContent("Online 6");
    expect(legend).toHaveTextContent("Sem serviço 8");
    expect(legend).toHaveTextContent("Sinal baixo 1");
  });
});
