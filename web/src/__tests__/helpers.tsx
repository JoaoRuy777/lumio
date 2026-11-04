import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import type { Alarm, Me, Olt, Onu } from "../api";

type Handler = (body: unknown, url: URL) => { status?: number; json?: unknown; stream?: ReadableStream<Uint8Array> };

/** fetch falso: responde por "MÉTODO /caminho" (sem a query) e guarda as chamadas. */
export function mockApi(routes: Record<string, Handler>) {
  const calls: { key: string; url: URL; body: unknown; auth: string | null }[] = [];
  const fetchMock = vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = new URL(input, "http://lumio.test");
    const key = `${init.method ?? "GET"} ${url.pathname.replace(/^\/api/, "")}`;
    const body = init.body ? JSON.parse(init.body as string) : undefined;
    const headers = (init.headers ?? {}) as Record<string, string>;
    calls.push({ key, url, body, auth: headers.Authorization ?? null });
    const handler = routes[key];
    if (!handler) return new Response(JSON.stringify({ detail: `rota não simulada: ${key}` }), { status: 500 });
    const { status = 200, json, stream } = handler(body, url);
    if (stream) return new Response(stream, { status, headers: { "content-type": "text/event-stream" } });
    return new Response(status === 204 ? null : JSON.stringify(json ?? {}), { status });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

/** Stream SSE controlado pelo teste: push("texto") entrega dados ao painel. */
export function sseStream() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({ start: (c) => (controller = c) });
  const enc = new TextEncoder();
  return {
    stream,
    push: (text: string) => controller.enqueue(enc.encode(text)),
    event: (data: object) => controller.enqueue(enc.encode(`data: ${JSON.stringify(data)}\n\n`)),
  };
}

export function renderWithQuery(ui: ReactElement, { route = "/" }: { route?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </QueryClientProvider>,
    ),
  };
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

export function makeAlarm(over: Partial<Alarm> = {}): Alarm {
  const now = new Date().toISOString();
  return {
    id: "alarm-1",
    kind: "pon_fiber_cut",
    severity: "critical",
    status: "active",
    source: "trap",
    olt_id: "olt-1-id",
    olt_name: "olt-centro",
    pon_id: "pon-2",
    pon: "0/1/2",
    onu_id: null,
    onu_index: null,
    onu_serial: null,
    parent_id: null,
    children: 16,
    occurrences: 1,
    details: {},
    first_seen_at: now,
    last_seen_at: now,
    created_at: now,
    cleared_at: null,
    latency_ms: 80,
    acknowledged_at: null,
    acknowledged_by: null,
    ...over,
  };
}

export function makeOnu(over: Partial<Onu> = {}): Onu {
  return {
    id: "onu-1",
    olt_id: "olt-1-id",
    olt_name: "olt-centro",
    pon_id: "pon-2",
    pon: "0/1/2",
    onu_index: 3,
    serial: "HWTC12345678",
    online: true,
    rx_dbm: -21.4,
    tx_dbm: 2.2,
    last_change_at: new Date().toISOString(),
    last_seen_at: new Date().toISOString(),
    active_alarms: [],
    ...over,
  };
}
