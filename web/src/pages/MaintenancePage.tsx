import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, ApiError, type MaintenanceState, type MaintenanceWindow, type OltList, type Pon } from "../api";
import { scope } from "../components/MaintenanceBanner";
import { Button, Card, Field, inputClass, td, th } from "../components/ui";
import { dateTime } from "../format";

const DURATIONS = [
  { label: "30 min", min: 30 },
  { label: "1 h", min: 60 },
  { label: "2 h", min: 120 },
  { label: "4 h", min: 240 },
];

const STATE: Record<MaintenanceState, [string, string]> = {
  active: ["Em andamento", "bg-sky-50 text-sky-800 ring-sky-600/20"],
  scheduled: ["Agendada", "bg-brand-50 text-brand-700 ring-brand-600/20"],
  finished: ["Encerrada", "bg-slate-100 text-slate-600 ring-slate-500/20"],
  cancelled: ["Cancelada", "bg-slate-100 text-slate-500 ring-slate-500/20"],
};

/** "2026-11-08T02:00" (campo datetime-local, hora local) a partir de um Date. */
function localInput(d: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function nextQuarter() {
  const d = new Date();
  d.setSeconds(0, 0);
  d.setMinutes(Math.ceil((d.getMinutes() + 1) / 15) * 15);
  return d;
}

export function MaintenancePage() {
  const qc = useQueryClient();
  const olts = useQuery({ queryKey: ["olts"], queryFn: () => api<OltList>("/olts") });
  const list = useQuery({
    queryKey: ["maintenance", "all"],
    queryFn: () => api<MaintenanceWindow[]>("/maintenance"),
    refetchInterval: 30_000,
  });

  const [oltId, setOltId] = useState("");
  const [ponId, setPonId] = useState("");
  const [reason, setReason] = useState("");
  const [start, setStart] = useState(() => localInput(nextQuarter()));
  const [end, setEnd] = useState(() => localInput(new Date(nextQuarter().getTime() + 2 * 3_600_000)));
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const pons = useQuery({
    queryKey: ["pons", oltId],
    queryFn: () => api<Pon[]>(`/olts/${oltId}/pons`),
    enabled: !!oltId,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["maintenance"] });
    qc.invalidateQueries({ queryKey: ["overview"] });
  };
  const create = useMutation({
    mutationFn: () =>
      api<MaintenanceWindow>("/maintenance", {
        method: "POST",
        body: {
          olt_id: oltId,
          pon_id: ponId || null,
          reason,
          starts_at: new Date(start).toISOString(),
          ends_at: new Date(end).toISOString(),
        },
      }),
    onSuccess: (w) => {
      setError(null);
      setSaved(`Manutenção ${w.state === "active" ? "iniciada" : "agendada"}: ${scope(w)}.`);
      setReason("");
      refresh();
    },
    onError: (e) => {
      setSaved(null);
      setError(e instanceof ApiError ? e.message : "não foi possível agendar");
    },
  });
  const end_ = useMutation({
    mutationFn: (id: string) => api<MaintenanceWindow>(`/maintenance/${id}/end`, { method: "POST" }),
    onSuccess: refresh,
    onError: (e) => setError(e instanceof ApiError ? e.message : "não foi possível encerrar"),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  const setDuration = (min: number) => setEnd(localInput(new Date(new Date(start).getTime() + min * 60_000)));
  const items = list.data ?? [];
  const open = items.filter((w) => w.state === "active" || w.state === "scheduled");
  const past = items.filter((w) => w.state === "finished" || w.state === "cancelled");

  return (
    <div className="space-y-5">
      <div>
        <p className="text-sm text-slate-500">Rede</p>
        <h1 className="text-2xl font-bold tracking-tight">Manutenções programadas</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          Durante a janela, os alarmes da OLT (ou da PON escolhida) continuam aparecendo no painel, marcados como manutenção, mas{" "}
          <b>não disparam e-mail nem webhook</b>. Fora dela, tudo volta ao normal sozinho.
        </p>
      </div>

      <Card title="Agendar manutenção">
        <form onSubmit={submit} className="grid gap-4 p-4 md:grid-cols-2 xl:grid-cols-4" aria-label="Agendar manutenção">
          <Field label="OLT">
            <select
              className={inputClass}
              required
              value={oltId}
              onChange={(e) => {
                setOltId(e.target.value);
                setPonId("");
              }}
            >
              <option value="">Escolha a OLT…</option>
              {olts.data?.items.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Abrangência" hint="Uma PON só, ou a OLT inteira">
            <select className={inputClass} value={ponId} onChange={(e) => setPonId(e.target.value)} disabled={!oltId}>
              <option value="">OLT inteira</option>
              {pons.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  PON {p.name}
                </option>
              ))}
            </select>
          </Field>
          <div className="md:col-span-2">
            <Field label="Motivo" hint="Aparece no painel e no chamado dos alarmes da janela">
              <input
                className={inputClass}
                required
                minLength={3}
                maxLength={300}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Ex.: troca do splitter da Rua 7; atualização de firmware"
              />
            </Field>
          </div>
          <Field label="Início">
            <input type="datetime-local" className={inputClass} required value={start} onChange={(e) => setStart(e.target.value)} />
          </Field>
          <Field label="Fim">
            <input type="datetime-local" className={inputClass} required value={end} onChange={(e) => setEnd(e.target.value)} />
          </Field>
          <div className="flex flex-wrap items-end gap-2 md:col-span-2">
            <span className="w-full text-sm text-slate-600 xl:w-auto xl:pb-2">Duração:</span>
            {DURATIONS.map((d) => (
              <button
                key={d.min}
                type="button"
                className="rounded-full border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
                onClick={() => setDuration(d.min)}
              >
                {d.label}
              </button>
            ))}
            <span className="flex-1" />
            <Button
              variant="secondary"
              onClick={() => {
                const now = new Date();
                setStart(localInput(now));
                setEnd(localInput(new Date(now.getTime() + 2 * 3_600_000)));
              }}
            >
              Começar agora
            </Button>
            <Button type="submit" disabled={create.isPending}>
              Agendar
            </Button>
          </div>
          {(error || saved) && (
            <p
              role={error ? "alert" : "status"}
              className={`rounded-md px-3 py-2 text-sm md:col-span-2 xl:col-span-4 ${error ? "bg-red-50 text-red-700" : "bg-emerald-50 text-emerald-800"}`}
            >
              {error ?? saved}
            </p>
          )}
        </form>
      </Card>

      <WindowTable
        title="Em andamento e agendadas"
        items={open}
        empty="Nenhuma manutenção em andamento ou agendada."
        onEnd={(id) => end_.mutate(id)}
        busy={end_.isPending}
      />
      <WindowTable title="Últimos 30 dias" items={past} empty="Nenhuma manutenção encerrada nos últimos 30 dias." />
    </div>
  );
}

function WindowTable({
  title,
  items,
  empty,
  onEnd,
  busy,
}: {
  title: string;
  items: MaintenanceWindow[];
  empty: string;
  onEnd?: (id: string) => void;
  busy?: boolean;
}) {
  return (
    <Card title={title}>
      {items.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-slate-500">{empty}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                <th className={th}>Situação</th>
                <th className={th}>Onde</th>
                <th className={th}>Motivo</th>
                <th className={th}>Período</th>
                <th className={th}>Alarmes sem aviso</th>
                {onEnd && <th className={th} aria-label="Ações" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((w) => {
                const [label, cls] = STATE[w.state];
                return (
                  <tr key={w.id}>
                    <td className={td}>
                      <span
                        className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset ${cls}`}
                      >
                        {label}
                      </span>
                    </td>
                    <td className={`${td} font-medium`}>{scope(w)}</td>
                    <td className={td}>
                      {w.reason}
                      {w.created_by && <span className="block text-xs text-slate-500">por {w.created_by}</span>}
                    </td>
                    <td className={`${td} whitespace-nowrap text-slate-600`}>
                      {dateTime(w.starts_at)}
                      <span className="block">até {dateTime(w.ends_at)}</span>
                    </td>
                    <td className={`${td} tabular-nums`}>{w.alarms_silenced}</td>
                    {onEnd && (
                      <td className={`${td} text-right`}>
                        <Button variant="secondary" disabled={busy} onClick={() => onEnd(w.id)}>
                          {w.state === "active" ? "Encerrar agora" : "Cancelar"}
                        </Button>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
