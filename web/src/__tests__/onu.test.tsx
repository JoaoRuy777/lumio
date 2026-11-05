import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";
import { OnuPage } from "../pages/OnuPage";
import { makeAlarm, makeOnu, mockApi, renderWithQuery } from "./helpers";

const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();

describe("tela da ONU", () => {
  it("mostra o cliente, a folga até o limite, as quedas e as faixas de queda no gráfico", async () => {
    const readings = Array.from({ length: 30 }, (_, i) => ({ ts: ago(300 - i * 10), rx_dbm: -24.5, tx_dbm: 2.1 }));
    mockApi({
      "GET /onus/onu-1": () => ({ json: makeOnu({ id: "onu-1", online: true, rx_dbm: -24.5 }) }),
      "GET /onus/onu-1/readings": () => ({ json: { items: readings, bucket_s: 0 } }),
      "GET /onus/onu-1/customer": () => ({
        json: { id: "c1", name: "Maria Souza Lima", phone: "(14) 99111-2222", address: "Rua das Palmeiras, 10", district: "Centro", plan: "500 Mega", code: "C10234" },
      }),
      "GET /onus-at-risk": () => ({ json: [] }),
      "GET /alarms": () => ({
        json: {
          items: [
            makeAlarm({ id: "x1", kind: "onu_offline", severity: "minor", status: "cleared", created_at: ago(200), cleared_at: ago(180) }),
            makeAlarm({ id: "x2", kind: "onu_offline", severity: "minor", status: "cleared", created_at: ago(100), cleared_at: ago(90) }),
          ],
          total: 2,
        },
      }),
    });
    renderWithQuery(
      <Routes>
        <Route path="/onus/:id" element={<OnuPage />} />
      </Routes>,
      { route: "/onus/onu-1" },
    );

    const customer = await screen.findByRole("region", { name: "Cliente" });
    expect(customer).toHaveTextContent("Maria Souza Lima");
    expect(customer).toHaveTextContent("(14) 99111-2222");
    expect(customer).toHaveTextContent("500 Mega · C10234");
    expect(screen.getByText("2,5 dB de folga até o limite")).toBeInTheDocument();
    expect(await screen.findByText("Faixas vermelhas: ONU fora do ar (2 quedas no período)")).toBeInTheDocument();
    expect(screen.getByText("Quedas em 30 dias").nextElementSibling).toHaveTextContent("2");
  });
});
