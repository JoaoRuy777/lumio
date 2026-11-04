import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ChangeEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { api, ApiError, query, type Customer, type CustomerState, type ImportResult, type Me, type Page } from "../api";
import { STATE_COLOR, STATE_LABEL } from "../mapStates";
import { Button, Card, inputClass, Pager, td, th } from "../components/ui";
import { dbm } from "../format";

const LIMIT = 50;
const TEMPLATE =
  "serial;codigo;nome;telefone;endereco;bairro;cidade;plano;latitude;longitude\n" +
  "HWTC0877432D;C10009;Maria Souza;(14) 99999-0000;Rua das Palmeiras, 120;Centro;Marília;500 Mega;-22.2140;-49.9460\n";

function StateDot({ state }: { state: CustomerState }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium">
      <span className="size-2 rounded-full" style={{ background: STATE_COLOR[state] }} aria-hidden />
      {STATE_LABEL[state]}
    </span>
  );
}

function Importer({ onDone }: { onDone: () => void }) {
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function pick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api<ImportResult>("/customers/import", { method: "POST", body: { csv: await file.text() } }));
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "não foi possível importar");
    } finally {
      setBusy(false);
    }
  }

  function template() {
    const url = URL.createObjectURL(new Blob(["﻿" + TEMPLATE], { type: "text/csv;charset=utf-8" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "modelo-clientes-lumio.csv" });
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <Card title="Importar clientes">
      <div className="space-y-3 p-4 text-sm">
        <p className="text-slate-600">
          CSV com uma linha por cliente. Obrigatórios: <b>serial</b> da ONU e <b>nome</b>. Opcionais: código, telefone,
          endereço, bairro, cidade, plano, latitude e longitude (para o mapa). Separador ";" ou ","; quem já existe (mesmo
          serial) é atualizado.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <label className={`inline-flex cursor-pointer rounded-md bg-brand-600 px-3 py-2 font-medium text-white hover:bg-brand-800 ${busy ? "opacity-60" : ""}`}>
            {busy ? "Importando…" : "Escolher arquivo CSV"}
            <input type="file" accept=".csv,text/csv" className="sr-only" onChange={pick} disabled={busy} aria-label="Arquivo CSV de clientes" />
          </label>
          <Button variant="secondary" onClick={template}>
            Baixar modelo
          </Button>
        </div>
        {error && (
          <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-red-700">
            {error}
          </p>
        )}
        {result && (
          <div role="status" className="rounded-md bg-emerald-50 px-3 py-2 text-emerald-800">
            <p>
              {result.created} {result.created === 1 ? "cliente novo" : "clientes novos"}, {result.updated} atualizados.
              {result.unmatched > 0 && ` ${result.unmatched} ainda sem ONU com o serial informado (aparecem como "sem dados da ONU").`}
            </p>
            {result.errors.length > 0 && (
              <ul className="mt-1 list-inside list-disc text-amber-800">
                {result.errors.slice(0, 5).map((e) => (
                  <li key={e.line}>
                    linha {e.line}: {e.error}
                  </li>
                ))}
                {result.errors.length > 5 && <li>e mais {result.errors.length - 5} linhas com erro</li>}
              </ul>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

export function CustomersPage({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const state = (params.get("state") as CustomerState | null) ?? null;
  const offset = Number(params.get("offset") ?? 0);
  const [text, setText] = useState(q);

  const { data, isPending } = useQuery({
    queryKey: ["customers", q, state, offset],
    queryFn: () => api<Page<Customer>>(`/customers${query({ q: q || null, state, limit: LIMIT, offset })}`),
  });

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      if (v === null || v === "") next.delete(k);
      else next.set(k, v);
    }
    if (!("offset" in changes)) next.delete("offset");
    setParams(next);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Clientes</h1>
          <p className="text-sm text-slate-500">Ligados às ONUs pelo serial. Alarmes, e-mails e o mapa mostram quem foi afetado.</p>
        </div>
        <Link to="/mapa" className="text-sm font-medium text-brand-600 hover:underline">
          Ver no mapa →
        </Link>
      </div>

      {me.role === "admin" && <Importer onDone={() => qc.invalidateQueries({ queryKey: ["customers"] })} />}

      <form
        className="flex flex-wrap items-center gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          update({ q: text.trim() || null });
        }}
      >
        <input
          className={`${inputClass} max-w-sm`}
          placeholder="Nome, código, serial, endereço ou bairro"
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-label="Buscar cliente"
        />
        <select className={`${inputClass} w-auto`} value={state ?? ""} onChange={(e) => update({ state: e.target.value || null })} aria-label="Estado">
          <option value="">Todos os estados</option>
          {(Object.keys(STATE_LABEL) as CustomerState[]).map((s) => (
            <option key={s} value={s}>
              {STATE_LABEL[s]}
            </option>
          ))}
        </select>
        <Button type="submit" variant="secondary">
          Buscar
        </Button>
      </form>

      <Card>
        {isPending ? (
          <p className="p-6 text-sm text-slate-500">Carregando…</p>
        ) : !data?.items.length ? (
          <p className="px-4 py-10 text-center text-sm text-slate-500">
            {q || state ? "Nenhum cliente encontrado." : "Nenhum cliente importado ainda."}
          </p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-slate-200 bg-slate-50">
                  <tr>
                    <th className={th}>Cliente</th>
                    <th className={th}>Endereço</th>
                    <th className={th}>Telefone</th>
                    <th className={th}>ONU</th>
                    <th className={th}>Situação</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.items.map((c) => (
                    <tr key={c.id}>
                      <td className={td}>
                        <p className="font-medium">{c.name}</p>
                        <p className="text-xs text-slate-500">
                          {[c.code, c.plan].filter(Boolean).join(" · ")}
                        </p>
                      </td>
                      <td className={td}>
                        <p>{c.address ?? "—"}</p>
                        <p className="text-xs text-slate-500">{[c.district, c.city].filter(Boolean).join(" · ")}</p>
                      </td>
                      <td className={`${td} whitespace-nowrap`}>{c.phone ?? "—"}</td>
                      <td className={td}>
                        {c.onu_id ? (
                          <Link to={`/onus/${c.onu_id}`} className="font-mono text-xs font-medium text-brand-700 hover:underline">
                            {c.serial}
                          </Link>
                        ) : (
                          <span className="font-mono text-xs text-slate-500">{c.serial}</span>
                        )}
                        {c.olt_name && (
                          <p className="text-xs text-slate-500">
                            {c.olt_name} · PON {c.pon} · ONU {c.onu_index}
                          </p>
                        )}
                      </td>
                      <td className={td}>
                        <StateDot state={c.state} />
                        {c.rx_dbm !== null && c.state !== "offline" && <p className="text-xs text-slate-500">{dbm(c.rx_dbm)}</p>}
                        {c.ticket_id && (
                          <Link to={`/alarms/${c.ticket_id}`} className="text-xs font-medium text-brand-600 hover:underline">
                            ver chamado
                          </Link>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={data.total} limit={LIMIT} offset={offset} onChange={(o) => update({ offset: String(o) })} />
          </>
        )}
      </Card>
    </div>
  );
}
