import type { CustomerState } from "./api";

/** Cores e nomes dos estados do cliente (mapa, legenda e tabelas). */
export const STATE_COLOR: Record<CustomerState, string> = {
  online: "#16a34a",
  trend: "#eab308",
  low: "#ea580c",
  offline: "#dc2626",
  unknown: "#94a3b8",
};

export const STATE_LABEL: Record<CustomerState, string> = {
  online: "Online",
  trend: "Sinal piorando",
  low: "Sinal baixo",
  offline: "Sem serviço",
  unknown: "Sem dados da ONU",
};
