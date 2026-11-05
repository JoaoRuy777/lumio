import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { api, ApiError, type Alarm, type AppUser, type Cause, type Me, type TimelineItem } from "../api";
import { Children } from "./AlarmTable";
import { Icon } from "./icons";
import { AlarmStatusBadge, Button, Card, Field, inputClass, Loading, SeverityBadge } from "./ui";
import { causeLabel, dateTime, dbm, kindLabel, location, stopwatch } from "../format";
import { useToast } from "../toast";
import { useNow } from "../useNow";

const CAUSES = Object.keys(causeLabel) as Cause[];

function WorkBadge({ alarm: a }: { alarm: Alarm }) {
  const [label, cls] = a.work_closed_at
    ? ["Atendimento encerrado", "bg-emerald-50 text-emerald-800 ring-emerald-600/20"]
    : a.assigned_to
      ? ["Em atendimento", "bg-brand-50 text-brand-700 ring-brand-600/20"]
      : ["Aguardando atendimento", "bg-amber-50 text-amber-800 ring-amber-600/20"];
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${cls}`}>{label}</span>;
}

function Clock({
  label,
  value,
  running,
  detail,
  mono = true,
}: {
  label: string;
  value: string;
  running?: boolean;
  detail?: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-surface p-3.5">
      <p className="flex items-center gap-1.5 text-xs font-medium tracking-wide text-slate-500 uppercase">
        {running && <span className="size-1.5 animate-pulse rounded-full bg-emerald-500" aria-label="contando" />}
        {label}
      </p>
      <p className={`mt-1 truncate text-xl font-semibold tabular-nums ${mono ? "font-mono" : ""}`}>{value}</p>
      {detail && <p className="mt-0.5 text-xs text-slate-500">{detail}</p>}
    </div>
  );
}

const timelineText: Record<TimelineItem["kind"], (t: TimelineItem) => ReactNode> = {
  opened: () => "Alarme aberto",
  assigned: (t) => (
    <>
      <b>{t.target}</b> assumiu o chamado
    </>
  ),
  transferred: (t) => (
    <>
      <b>{t.actor}</b> transferiu para <b>{t.target}</b>
    </>
  ),
  note: (t) => (
    <>
      <b>{t.actor}</b> anotou
    </>
  ),
  closed: (t) => (
    <>
      <b>{t.actor}</b> encerrou o atendimento
    </>
  ),
  reopened: (t) => (
    <>
      <b>{t.actor}</b> reabriu o chamado
    </>
  ),
  notified: (t) => `Aviso de ${t.body} enviado para o canal "${t.target}"`,
  escalated: (t) => (
    <>
      <b>Escalonado</b> para "{t.target}" ({t.body})
    </>
  ),
  cleared: () => "Rede normalizada (a falha passou)",
};

const dotColor: Record<TimelineItem["kind"], string> = {
  opened: "bg-red-500",
  assigned: "bg-brand-500",
  transferred: "bg-brand-500",
  note: "bg-slate-400",
  closed: "bg-emerald-500",
  reopened: "bg-amber-500",
  notified: "bg-slate-300",
  escalated: "bg-orange-500",
  cleared: "bg-emerald-500",
};

function Timeline({ items }: { items: TimelineItem[] }) {
  return (
    <ol className="space-y-4 p-4" aria-label="Linha do tempo">
      {items.map((t, i) => (
        <li key={i} className="relative flex gap-3">
          <span className={`mt-1.5 size-2.5 shrink-0 rounded-full ${dotColor[t.kind]}`} aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-sm text-slate-700">
              {timelineText[t.kind](t)} <span className="text-xs text-slate-500">· {dateTime(t.at)}</span>
            </p>
            {t.body && (t.kind === "note" || t.kind === "closed") && (
              <p className="mt-1 rounded-md bg-slate-50 px-3 py-2 text-sm whitespace-pre-wrap text-slate-800">{t.body}</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

/**
 * O chamado: relógios, ações (assumir, transferir, encerrar), ONUs afetadas e
 * linha do tempo. Usado na página própria (/alarms/:id) e no painel ao lado da
 * lista da central de alarmes (layout "panel", mais estreito).
 */
export function Ticket({ id, me, layout = "page", onClose }: { id: string; me: Me; layout?: "page" | "panel"; onClose?: () => void }) {
  const panel = layout === "panel";
  const qc = useQueryClient();
  const now = useNow();
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [closing, setClosing] = useState(false);
  const [close, setClose] = useState<{ cause: Cause | ""; notes: string }>({
    cause: "",
    notes: "",
  });
  const [transferTo, setTransferTo] = useState("");

  const alarm = useQuery({
    queryKey: ["alarms", "detail", id],
    queryFn: () => api<Alarm>(`/alarms/${id}`),
    refetchInterval: 15_000,
  });
  const timeline = useQuery({
    queryKey: ["alarms", "detail", id, "timeline"],
    queryFn: () => api<TimelineItem[]>(`/alarms/${id}/timeline`),
    refetchInterval: 15_000,
  });
  const users = useQuery({
    queryKey: ["users"],
    queryFn: () => api<{ items: AppUser[] }>("/users"),
  });

  const toast = useToast();
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => api<Alarm>(`/alarms/${id}/${path}`, { method: "POST", body }),
    onSuccess: (_, { path, body }) => {
      setError(null);
      const transfer = path === "assign" && !!(body as { user_id?: string } | undefined)?.user_id;
      toast(
        transfer
          ? "Chamado transferido"
          : ({ assign: "Chamado assumido", notes: "Anotação registrada", close: "Chamado encerrado", reopen: "Chamado reaberto" } as Record<string, string>)[path] ?? "Salvo",
      );
      qc.invalidateQueries({ queryKey: ["alarms"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "não foi possível salvar"),
  });

  if (alarm.isPending) return <Loading rows={5} />;
  if (alarm.error || !alarm.data) {
    return (
      <p role="alert" className="text-sm text-red-700">
        Chamado não encontrado.{" "}
        <Link to="/alarms" className="underline">
          Voltar aos alarmes
        </Link>
      </p>
    );
  }
  const a = alarm.data;
  const isChild = a.parent_id !== null;
  const closed = a.work_closed_at !== null;
  const others = (users.data?.items ?? []).filter((u) => u.id !== a.assigned_to_id);
  const rx = a.details.rx_dbm;
  const cpu = a.details.cpu;

  function addNote(e: FormEvent) {
    e.preventDefault();
    if (!note.trim()) return;
    act.mutate({ path: "notes", body: { body: note } }, { onSuccess: () => setNote("") });
  }

  function submitClose(e: FormEvent) {
    e.preventDefault();
    act.mutate(
      { path: "close", body: close },
      {
        onSuccess: () => {
          setClosing(false);
          setClose({ cause: "", notes: "" });
        },
      },
    );
  }

  const Title = panel ? "h2" : "h1";
  return (
    <section className={panel ? "space-y-4" : "space-y-6"} aria-label="Chamado">
      <div>
        {panel ? (
          <div className="flex items-center justify-between gap-2">
            <Link to={`/alarms/${a.id}`} className="text-sm font-medium text-brand-600 hover:underline">
              Abrir em tela cheia
            </Link>
            <button
              className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
              onClick={onClose}
              aria-label="Fechar chamado"
            >
              <Icon name="close" className="size-4" />
            </button>
          </div>
        ) : (
          <Link to="/alarms" className="text-sm text-slate-500 hover:underline">
            ← Alarmes
          </Link>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <SeverityBadge severity={a.severity} />
          <Title className={`${panel ? "text-xl" : "text-2xl"} font-bold tracking-tight`}>
            {kindLabel[a.kind]}
            {typeof rx === "number" && <span className="text-slate-500"> · {dbm(rx)}</span>}
            {typeof cpu === "number" && <span className="text-slate-500"> · CPU {cpu}%</span>}
          </Title>
        </div>
        <p className="mt-1 text-sm text-slate-500">
          {location(a)}
          {a.customer_name && <> · cliente {a.customer_name}</>}
          {a.affected_customers > 0 && <> · {a.affected_customers} clientes afetados</>} · aberto em {dateTime(a.created_at)}
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          <AlarmStatusBadge status={a.status} />
          {!isChild && <WorkBadge alarm={a} />}
        </div>
      </div>

      {a.maintenance_id && (
        <p className="rounded-md bg-sky-50 px-4 py-3 text-sm text-sky-800">
          Aberto durante <b>manutenção programada</b> ({a.maintenance_reason}): não foi enviado aviso por e-mail.
        </p>
      )}

      {isChild ? (
        <p className="rounded-md bg-sky-50 px-4 py-3 text-sm text-sky-800">
          Esta ONU faz parte de um rompimento de fibra. O atendimento é feito no{" "}
          <Link to={`/alarms/${a.parent_id}`} className="font-medium underline">
            chamado do rompimento
          </Link>
          .
        </p>
      ) : (
        <>
          <div className={`grid gap-3 sm:grid-cols-2 ${panel ? "" : "lg:grid-cols-4"}`}>
            <Clock
              label={a.cleared_at ? "Duração na rede" : "Falha na rede há"}
              value={stopwatch(a.created_at, a.cleared_at, now)}
              running={!a.cleared_at}
              detail={a.cleared_at ? `normalizou em ${dateTime(a.cleared_at)}` : "até a falha passar"}
            />
            <Clock
              label="Espera até assumir"
              value={stopwatch(a.created_at, a.first_assigned_at, now)}
              running={!a.first_assigned_at && !a.cleared_at}
              detail={a.first_assigned_at ? `assumido em ${dateTime(a.first_assigned_at)}` : "ninguém assumiu ainda"}
            />
            <Clock
              label="Tempo de atendimento"
              value={a.first_assigned_at ? stopwatch(a.first_assigned_at, a.work_closed_at, now) : "—"}
              running={!!a.first_assigned_at && !closed}
              detail={closed ? `encerrado em ${dateTime(a.work_closed_at)}` : "de assumido até encerrar (TMA)"}
            />
            <Clock
              label="Responsável"
              mono={false}
              value={a.work_closed_by ?? a.assigned_to ?? "—"}
              detail={a.assigned_at && !closed ? `com ele desde ${dateTime(a.assigned_at)}` : undefined}
            />
          </div>

          {error && (
            <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          )}

          <Card title="Atendimento">
            <div className="space-y-4 p-4">
              {closed ? (
                <div className="space-y-2">
                  <p className="text-sm">
                    <span className="text-slate-500">Causa:</span>{" "}
                    <span className="font-medium">{a.resolution_cause ? causeLabel[a.resolution_cause] : "—"}</span>
                  </p>
                  <p className="rounded-md bg-slate-50 px-3 py-2 text-sm whitespace-pre-wrap">{a.resolution_notes}</p>
                  <Button variant="secondary" disabled={act.isPending} onClick={() => act.mutate({ path: "reopen" })}>
                    Reabrir chamado
                  </Button>
                </div>
              ) : (
                <div className="flex flex-wrap items-end gap-3">
                  {a.assigned_to_id !== me.user_id && (
                    <Button disabled={act.isPending} onClick={() => act.mutate({ path: "assign", body: {} })}>
                      {a.assigned_to ? "Assumir para mim" : "Assumir chamado"}
                    </Button>
                  )}
                  <label className="text-sm">
                    <span className="mb-1 block text-slate-600">Transferir para</span>
                    <span className="flex gap-2">
                      <select
                        className={inputClass}
                        value={transferTo}
                        onChange={(e) => setTransferTo(e.target.value)}
                        aria-label="Transferir para"
                      >
                        <option value="">Escolha…</option>
                        {others.map((u) => (
                          <option key={u.id} value={u.id}>
                            {u.name}
                          </option>
                        ))}
                      </select>
                      <Button
                        variant="secondary"
                        disabled={!transferTo || act.isPending}
                        onClick={() =>
                          act.mutate({ path: "assign", body: { user_id: transferTo } }, { onSuccess: () => setTransferTo("") })
                        }
                      >
                        Transferir
                      </Button>
                    </span>
                  </label>
                  {a.assigned_to && !closing && (
                    <Button variant="secondary" onClick={() => setClosing(true)}>
                      Encerrar atendimento
                    </Button>
                  )}
                </div>
              )}

              {closing && !closed && (
                <form onSubmit={submitClose} className="space-y-3 rounded-lg border border-slate-200 p-4" aria-label="Encerrar atendimento">
                  {a.status !== "cleared" && (
                    <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
                      A falha ainda está ativa na rede. Encerre só se o atendimento terminou (por exemplo, falso alarme ou problema do
                      cliente); se a equipe ainda está a caminho, registre isso como anotação.
                    </p>
                  )}
                  <Field label="Causa">
                    <select
                      className={inputClass}
                      required
                      value={close.cause}
                      onChange={(e) => setClose({ ...close, cause: e.target.value as Cause })}
                    >
                      <option value="">Escolha a causa…</option>
                      {CAUSES.map((c) => (
                        <option key={c} value={c}>
                          {causeLabel[c]}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="O que foi feito">
                    <textarea
                      className={inputClass}
                      rows={3}
                      required
                      minLength={3}
                      value={close.notes}
                      onChange={(e) => setClose({ ...close, notes: e.target.value })}
                      placeholder="Ex.: fibra rompida por obra na Av. Brasil; equipe fez a fusão e o sinal voltou."
                    />
                  </Field>
                  <div className="flex justify-end gap-2">
                    <Button variant="secondary" onClick={() => setClosing(false)}>
                      Cancelar
                    </Button>
                    <Button type="submit" disabled={act.isPending}>
                      Encerrar
                    </Button>
                  </div>
                </form>
              )}
            </div>
          </Card>
        </>
      )}

      {a.children > 0 && (
        <Card title={`ONUs afetadas (${a.children})`}>
          <Children parent={a} />
        </Card>
      )}

      <Card title="Linha do tempo">
        {!isChild && (
          <form
            onSubmit={addNote}
            className="flex flex-col gap-2 border-b border-slate-200 p-4 sm:flex-row sm:items-end"
            aria-label="Nova anotação"
          >
            <label className="flex-1 text-sm">
              <span className="mb-1 block text-slate-600">Anotação</span>
              <textarea
                className={inputClass}
                rows={2}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Ex.: liguei para o cliente, confirmou sem sinal desde 14h."
              />
            </label>
            <Button type="submit" disabled={!note.trim() || act.isPending}>
              Anotar
            </Button>
          </form>
        )}
        {timeline.data ? <Timeline items={timeline.data} /> : <Loading />}
      </Card>
    </section>
  );
}
