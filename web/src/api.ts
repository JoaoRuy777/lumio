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
  lat: number | null;
  lon: number | null;
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
  lat?: number | null;
  lon?: number | null;
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

// ------------------------------------------------------------------ painel (sprint 4)

export type Severity = "critical" | "major" | "minor" | "warning";
export type AlarmStatus = "active" | "acknowledged" | "cleared";
export type AlarmKind = "pon_fiber_cut" | "onu_offline" | "onu_rx_low" | "olt_unreachable" | "olt_cpu_high";

export interface Alarm {
  id: string;
  kind: AlarmKind;
  severity: Severity;
  status: AlarmStatus;
  source: "trap" | "poll";
  olt_id: string;
  olt_name: string;
  pon_id: string | null;
  pon: string | null;
  onu_id: string | null;
  onu_index: number | null;
  onu_serial: string | null;
  parent_id: string | null;
  children: number;
  occurrences: number;
  details: Record<string, unknown>;
  first_seen_at: string;
  last_seen_at: string;
  created_at: string;
  cleared_at: string | null;
  latency_ms: number | null;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  // atendimento (chamado)
  assigned_to_id: string | null;
  assigned_to: string | null;
  assigned_at: string | null;
  first_assigned_at: string | null;
  work_closed_at: string | null;
  work_closed_by: string | null;
  resolution_cause: Cause | null;
  resolution_notes: string | null;
  customer_name: string | null;
  affected_customers: number;
  maintenance_id?: string | null;
  maintenance_reason?: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
}

export interface Overview {
  olts: Record<"total" | "ok" | "error" | "late" | "pending" | "disabled", number>;
  onus: Record<"total" | "online" | "offline" | "unknown", number>;
  rx_low: number;
  rx_trend: number;
  customers: number;
  customers_offline?: number;
  maintenance_active?: number;
  alarms: Record<Severity | "total", number>;
  recent_alarms: Alarm[];
}

/** Uma hora das últimas 24 h (mini-gráficos da visão geral). */
export interface HourPoint {
  t: string;
  critical: number;
  major: number;
  other: number;
  open: number;
  onus_offline: number;
}

export interface Pon {
  id: string;
  name: string;
  onus_total: number;
  onus_online: number;
  rx_avg: number | null;
  rx_min: number | null;
  active_alarms: number;
}

export interface Onu {
  id: string;
  olt_id: string;
  olt_name: string;
  pon_id: string;
  pon: string;
  onu_index: number;
  serial: string | null;
  online: boolean | null;
  rx_dbm: number | null;
  tx_dbm: number | null;
  last_change_at: string | null;
  last_seen_at: string | null;
  active_alarms: AlarmKind[];
}

export interface Readings {
  items: { ts: string; rx_dbm: number | null; tx_dbm: number | null }[];
  bucket_s: number;
}

/** Monta "?a=1&b=2" ignorando vazios; arrays viram parâmetros repetidos. */
export function query(params: Record<string, string | number | boolean | string[] | null | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    for (const item of Array.isArray(v) ? v : [v]) sp.append(k, String(item));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

// ------------------------------------------------------------------ notificações e relatórios (sprint 5)

export type ChannelType = "email" | "webhook";

export interface Delivery {
  id: string;
  event: "opened" | "cleared" | "test";
  status: "pending" | "sending" | "sent" | "failed" | "suppressed";
  attempts: number;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
  alarm_kind: AlarmKind | null;
  alarm_severity: Severity | null;
}

export interface Channel {
  id: string;
  name: string;
  type: ChannelType;
  target: string;
  min_severity: Severity;
  notify_clear: boolean;
  enabled: boolean;
  created_at: string;
  last_delivery: Delivery | null;
}

export interface ChannelCreated {
  channel: Channel;
  secret: string | null;
}

export interface AvailabilityReport {
  period: { from: string; to: string };
  overall_availability_pct: number | null;
  olts: {
    olt: string;
    onus: number;
    availability_pct: number | null;
    onu_downtime_min: number;
    onu_outages: number;
    fiber_cuts: number;
    olt_management_pct: number;
    olt_unreachable_min: number;
  }[];
  worst_onus: { olt: string; pon: string; onu: number; serial: string | null; availability_pct: number; downtime_min: number; outages: number }[];
}

export interface AlarmsReport {
  period: { from: string; to: string };
  total: number;
  open: number;
  mttr_min: number | null;
  by_kind: Partial<Record<AlarmKind, number>>;
  by_severity: Partial<Record<Severity, number>>;
}

/** Baixa um arquivo da API (com o token) e entrega ao navegador. */
export async function downloadFile(path: string): Promise<void> {
  const token = session.get();
  const res = await fetch(`/api${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new ApiError(res.status, `não foi possível baixar (erro ${res.status})`);
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? "lumio-relatorio";
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export type Role = Me["role"];

export interface AppUser {
  id: string;
  name: string;
  email: string;
  role: Role;
  created_at: string;
}

export interface UserInput {
  name: string;
  email: string;
  password: string;
  role: Role;
}

// ------------------------------------------------------------------ atendimento

export type Cause =
  | "fiber_third_party"
  | "fiber_natural"
  | "power"
  | "equipment"
  | "customer"
  | "maintenance"
  | "configuration"
  | "no_fault"
  | "other";

export interface TimelineItem {
  at: string;
  kind: "opened" | "assigned" | "transferred" | "note" | "closed" | "reopened" | "notified" | "cleared";
  actor: string | null;
  target: string | null;
  body: string | null;
}

export interface AttendanceOperator {
  name: string;
  taken: number;
  closed: number;
  open: number;
  tme_min: number | null;
  tma_min: number | null;
  time_in_attendance_min: number;
  notes: number;
}

export interface AttendanceReport {
  summary: {
    tickets: number;
    assumed: number;
    unattended: number;
    closed: number;
    in_progress: number;
    tme_min: number | null;
    tma_min: number | null;
    tma_max_min: number | null;
    sla_assume_min: number;
    assumed_within_sla_pct: number | null;
  };
  operators: AttendanceOperator[];
  causes: { cause: Cause; label: string; count: number; pct: number; tma_min: number | null }[];
}

// ------------------------------------------------------------------ clientes e mapa

export type CustomerState = "online" | "offline" | "low" | "trend" | "unknown";

export interface Customer {
  id: string;
  code: string | null;
  name: string;
  phone: string | null;
  address: string | null;
  district: string | null;
  city: string | null;
  plan: string | null;
  lat: number | null;
  lon: number | null;
  serial: string;
  onu_id: string | null;
  olt_id: string | null;
  olt_name: string | null;
  pon: string | null;
  onu_index: number | null;
  rx_dbm: number | null;
  state: CustomerState;
  ticket_id: string | null;
}

export interface ImportResult {
  created: number;
  updated: number;
  unmatched: number;
  errors: { line: number; error: string }[];
}

export interface MapOlt {
  id: string;
  name: string;
  lat: number | null;
  lon: number | null;
  located: boolean;
  reachable: boolean | null;
  onus_total: number;
  onus_online: number;
  open_alarms: number;
}

export interface MapData {
  olts: MapOlt[];
  customers: Customer[];
}

export interface AtRiskOnu {
  onu_id: string;
  serial: string | null;
  onu_index: number;
  rx_dbm: number;
  olt_id: string;
  olt_name: string;
  pon: string;
  slope_db_day: number;
  points: number;
  days_to_limit: number;
}

// ------------------------------------------------------------------ manutenção programada

export type MaintenanceState = "active" | "scheduled" | "finished" | "cancelled";

export interface MaintenanceWindow {
  id: string;
  olt_id: string;
  olt_name: string;
  pon_id: string | null;
  pon: string | null;
  reason: string;
  starts_at: string;
  ends_at: string;
  created_by: string | null;
  created_at: string;
  cancelled_at: string | null;
  state: MaintenanceState;
  alarms_silenced: number;
}
