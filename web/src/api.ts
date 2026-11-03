// Cliente da API da Lumio. O token fica no localStorage do navegador.

export type CollectionStatus = "ok" | "error" | "pending" | "late" | "disabled";

export interface PlanUsage {
  used: number;
  limit: number;
}

export interface Me {
  user_id: string;
  email: string;
  name: string;
  role: "admin" | "operator";
  tenant_id: string;
  tenant_name: string;
  olts: PlanUsage;
}

export interface Olt {
  id: string;
  name: string;
  host: string | null;
  snmp_port: number;
  vendor: string | null;
  model: string | null;
  sys_name: string | null;
  status_interval_s: number;
  optical_interval_s: number;
  enabled: boolean;
  has_community: boolean;
  collection_status: CollectionStatus;
  last_poll_at: string | null;
  last_error: string | null;
  discovered_at: string | null;
  pon_ports: number;
  onus_total: number;
  onus_online: number;
  active_alarms: number;
}

export interface OltList {
  items: Olt[];
  usage: PlanUsage;
}

export interface ConnectionTest {
  ok: boolean;
  vendor?: string | null;
  model?: string | null;
  sys_name?: string | null;
  pon_ports?: string[];
  onus?: number | null;
  error?: string | null;
}

export interface Discovery {
  ok: boolean;
  pon_ports: number;
  onus: number;
  error: string | null;
}

export interface OltSaved {
  olt: Olt;
  discovery: Discovery;
}

export interface OltInput {
  name: string;
  host: string;
  snmp_port: number;
  community?: string;
  status_interval_s: number;
  optical_interval_s: number;
  enabled: boolean;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const TOKEN_KEY = "lumio.token";
export const LOGOUT_EVENT = "lumio:logout";

export const session = {
  get(): string | null {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string) {
    try {
      localStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* navegador sem storage: a sessão dura até recarregar */
    }
  },
  clear() {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* idem */
    }
  },
};

// Mensagens de validação do FastAPI (422) viram uma frase legível
function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => {
        const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : "";
        return field ? `${field}: ${d.msg}` : d.msg;
      })
      .join("; ");
  }
  return `erro ${status}`;
}

export async function api<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const token = session.get();
  const res = await fetch(`/api${path}`, {
    method: options.method ?? "GET",
    headers: {
      ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  if (res.status === 401 && token) {
    session.clear();
    window.dispatchEvent(new Event(LOGOUT_EVENT));
  }
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = undefined;
    }
    throw new ApiError(res.status, errorMessage(detail, res.status));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
