import { useQuery } from "@tanstack/react-query";
import { api, type CollectionHealth } from "../api";
import { ago, dateTime } from "../format";

/**
 * Faixa no topo quando nenhuma OLT manda leitura há alguns minutos (coletor
 * desligado, computador em suspensão, sem rede). Sem ela, a tela continua
 * mostrando o último estado como se fosse o atual.
 */
export function CollectionBanner() {
  const { data } = useQuery({
    queryKey: ["collection-health"],
    queryFn: () => api<CollectionHealth>("/overview/collection"),
    refetchInterval: 60_000,
  });
  if (!data?.stopped) return null;
  return (
    <div role="alert" className="border-b border-amber-300 bg-amber-50 px-4 py-2.5 text-sm text-amber-900 lg:px-8">
      <p>
        <strong className="font-semibold">Coleta parada:</strong> nenhuma leitura das OLTs desde{" "}
        <span title={dateTime(data.last_reading_at)}>
          {dateTime(data.last_reading_at)} ({ago(data.last_reading_at)})
        </span>
        . Alarmes e sinais não estão sendo atualizados. Confira se o coletor está ligado e se o computador dele não entrou em suspensão.
      </p>
    </div>
  );
}
