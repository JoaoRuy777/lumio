import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";
import type { Me, Olt } from "../api";

type Handler = (body: unknown) => { status?: number; json?: unknown };

/** fetch falso: responde por "MÉTODO /caminho" e guarda as chamadas. */
export function mockApi(routes: Record<string, Handler>) {
  const calls: { key: string; body: unknown; auth: string | null }[] = [];
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const key = `${init.method ?? "GET"} ${url.replace(/^\/api/, "")}`;
    const body = init.body ? JSON.parse(init.body as string) : undefined;
    const headers = (init.headers ?? {}) as Record<string, string>;
    calls.push({ key, body, auth: headers.Authorization ?? null });
    const handler = routes[key];
    if (!handler) return new Response(JSON.stringify({ detail: `rota não simulada: ${key}` }), { status: 500 });
    const { status = 200, json } = handler(body);
    return new Response(status === 204 ? null : JSON.stringify(json ?? {}), { status });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

export function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

export const me: Me = {
  user_id: "u1",
  email: "admin@a.com.br",
  name: "Ana",
  role: "admin",
  tenant_id: "t1",
  tenant_name: "Provedor A",
  olts: { used: 1, limit: 2 },
};

export function makeOlt(over: Partial<Olt> = {}): Olt {
  return {
    id: "olt-1-id",
    name: "olt-centro",
    host: "10.0.0.2",
    snmp_port: 161,
    vendor: "huawei",
    model: "MA5800-X7",
    sys_name: "olt-centro",
    status_interval_s: 60,
    optical_interval_s: 300,
    enabled: true,
    has_community: true,
    collection_status: "ok",
    last_poll_at: "2026-11-03T12:00:00Z",
    last_error: null,
    discovered_at: "2026-11-03T11:00:00Z",
    pon_ports: 4,
    onus_total: 64,
    onus_online: 62,
    active_alarms: 2,
    ...over,
  };
}
