import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router";
import { api, query, type Alarm, type Customer, type OltList, type Onu, type Page } from "../api";
import { kindLabel, location, severityLabel } from "../format";
import { Icon } from "./icons";

interface Result {
  group: string;
  label: string;
  detail?: string;
  to: string;
}

const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

function useDebounced(value: string, ms = 200) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/**
 * Busca universal do topo (Ctrl+K): telas, chamados abertos, clientes, ONUs
 * (serial) e OLTs, numa lista só. Enter abre o resultado marcado.
 */
export function GlobalSearch({ pages }: { pages: { to: string; label: string }[] }) {
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const term = useDebounced(q.trim());
  const enabled = term.length >= 2;

  const customers = useQuery({
    queryKey: ["search", "customers", term],
    queryFn: () => api<Page<Customer>>(`/customers${query({ q: term, limit: 5 })}`),
    enabled,
  });
  const onus = useQuery({
    queryKey: ["search", "onus", term],
    queryFn: () => api<Page<Onu>>(`/onus${query({ q: term, limit: 5 })}`),
    enabled,
  });
  const olts = useQuery({ queryKey: ["olts"], queryFn: () => api<OltList>("/olts"), enabled });
  const alarms = useQuery({
    queryKey: ["search", "alarms"],
    queryFn: () => api<Page<Alarm>>(`/alarms${query({ status: "open", limit: 100 })}`),
    enabled,
    staleTime: 15_000,
  });

  // Ctrl+K / ⌘K de qualquer tela
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        input.current?.focus();
        input.current?.select();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const results = useMemo<Result[]>(() => {
    if (!enabled) return [];
    const t = norm(term);
    const out: Result[] = [];
    for (const p of pages) if (norm(p.label).includes(t)) out.push({ group: "Telas", label: p.label, to: p.to });
    for (const a of alarms.data?.items ?? []) {
      const text = `${kindLabel[a.kind]} ${location(a)} ${a.customer_name ?? ""}`;
      if (norm(text).includes(t) && out.filter((r) => r.group === "Chamados").length < 5)
        out.push({
          group: "Chamados",
          label: kindLabel[a.kind],
          detail: `${severityLabel[a.severity]} · ${location(a)}`,
          to: `/alarms/${a.id}`,
        });
    }
    for (const c of (customers.data?.items ?? []).slice(0, 5))
      out.push({
        group: "Clientes",
        label: c.name,
        detail: [c.code, c.district, c.serial].filter(Boolean).join(" · "),
        to: c.onu_id ? `/onus/${c.onu_id}` : `/clientes?q=${encodeURIComponent(c.name)}`,
      });
    for (const o of (onus.data?.items ?? []).slice(0, 5))
      out.push({
        group: "ONUs",
        label: o.serial ?? `ONU ${o.onu_index}`,
        detail: `${o.olt_name} · PON ${o.pon} · ONU ${o.onu_index}`,
        to: `/onus/${o.id}`,
      });
    for (const o of olts.data?.items ?? [])
      if (norm(o.name).includes(t)) out.push({ group: "OLTs", label: o.name, detail: o.host ?? undefined, to: `/olts/${o.id}` });
    out.push({ group: "Buscar", label: `Buscar “${term}” nos clientes`, to: `/clientes?q=${encodeURIComponent(term)}` });
    return out;
  }, [enabled, term, pages, alarms.data, customers.data, onus.data, olts.data]);

  useEffect(() => setActive(0), [term]);

  function go(r: Result) {
    navigate(r.to);
    setOpen(false);
    setQ("");
    input.current?.blur();
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const term = q.trim();
      if (results[active]) go(results[active]);
      else if (term) go({ group: "Buscar", label: term, to: `/clientes?q=${encodeURIComponent(term)}` });
    } else if (e.key === "Escape") {
      setOpen(false);
      input.current?.blur();
    }
  }

  const loading = enabled && (customers.isFetching || onus.isFetching) && results.length <= 1;
  let lastGroup = "";

  return (
    <div className="relative max-w-md flex-1">
      <div
        role="search"
        className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-500/20"
      >
        <Icon name="search" className="size-4 shrink-0 text-slate-400" />
        <input
          ref={input}
          type="search"
          role="combobox"
          aria-expanded={open && enabled}
          aria-controls="busca-resultados"
          aria-activedescendant={open && results[active] ? `busca-${active}` : undefined}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={onKeyDown}
          placeholder="Buscar cliente, serial, OLT, chamado…"
          aria-label="Buscar cliente, serial, OLT ou chamado"
          className="h-9 w-full min-w-0 bg-transparent text-sm outline-none placeholder:text-slate-400"
        />
        <kbd className="hidden rounded border border-slate-300 px-1.5 text-[10px] font-medium whitespace-nowrap text-slate-500 md:inline">Ctrl K</kbd>
      </div>

      {open && enabled && (
        <ul
          id="busca-resultados"
          role="listbox"
          aria-label="Resultados da busca"
          className="absolute inset-x-0 top-full z-50 mt-1 max-h-[70vh] overflow-y-auto rounded-xl border border-slate-200 bg-surface py-1 shadow-xl"
        >
          {loading && <li className="px-3 py-2 text-sm text-slate-500">Buscando…</li>}
          {results.map((r, i) => {
            const header = r.group !== lastGroup && r.group !== "Buscar";
            lastGroup = r.group;
            return (
              <li key={`${r.group}-${r.to}-${i}`} role="presentation">
                {header && <p className="px-3 pt-2 pb-1 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">{r.group}</p>}
                <button
                  id={`busca-${i}`}
                  role="option"
                  aria-selected={i === active}
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => go(r)}
                  className={`flex w-full flex-col items-start px-3 py-1.5 text-left text-sm ${i === active ? "bg-brand-50" : ""} ${
                    r.group === "Buscar" ? "border-t border-slate-100 text-brand-700" : ""
                  }`}
                >
                  <span className="font-medium">{r.label}</span>
                  {r.detail && <span className="text-xs text-slate-500">{r.detail}</span>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
