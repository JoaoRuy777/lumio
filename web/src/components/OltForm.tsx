import { useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError, type ConnectionTest, type Olt, type OltInput, type OltSaved } from "../api";
import { Button, Field, inputClass } from "./ui";

interface Props {
  olt?: Olt; // presente = edição
  onSaved: (saved: OltSaved) => void;
  onCancel: () => void;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-3">
      <legend className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">{title}</legend>
      {children}
    </fieldset>
  );
}

export function OltForm({ olt, onSaved, onCancel }: Props) {
  const editing = olt !== undefined;
  const [form, setForm] = useState({
    name: olt?.name ?? "",
    host: olt?.host ?? "",
    snmp_port: String(olt?.snmp_port ?? 161),
    community: "",
    status_interval_s: String(olt?.status_interval_s ?? 60),
    optical_interval_s: String(olt?.optical_interval_s ?? 300),
    enabled: olt?.enabled ?? true,
    lat: olt?.lat != null ? String(olt.lat) : "",
    lon: olt?.lon != null ? String(olt.lon) : "",
  });
  const [test, setTest] = useState<ConnectionTest | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => {
    setForm((f) => ({ ...f, [key]: e.target.value }));
    if (key === "host" || key === "snmp_port" || key === "community") setTest(null);
  };

  // Na edição, community em branco = usa a que já está salva
  const useSavedCommunity = editing && form.community === "";
  const accessChanged =
    editing && (form.host !== olt.host || Number(form.snmp_port) !== olt.snmp_port || form.community !== "");
  const canTest = form.host !== "" && form.snmp_port !== "" && (form.community !== "" || useSavedCommunity);

  async function testConnection() {
    setTesting(true);
    setTest(null);
    try {
      const result =
        useSavedCommunity && !accessChanged
          ? await api<ConnectionTest>(`/olts/${olt.id}/test-connection`, { method: "POST" })
          : await api<ConnectionTest>("/olts/test-connection", {
              method: "POST",
              body: { host: form.host, snmp_port: Number(form.snmp_port), community: form.community },
            });
      setTest(result);
    } catch (err) {
      setTest({ ok: false, error: err instanceof ApiError ? err.message : "falha ao testar" });
    } finally {
      setTesting(false);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const body: OltInput = {
      name: form.name,
      host: form.host,
      snmp_port: Number(form.snmp_port),
      status_interval_s: Number(form.status_interval_s),
      optical_interval_s: Number(form.optical_interval_s),
      enabled: form.enabled,
      ...(form.community ? { community: form.community } : {}),
      ...(form.lat.trim() && form.lon.trim()
        ? { lat: Number(form.lat.replace(",", ".")), lon: Number(form.lon.replace(",", ".")) }
        : {}),
    };
    try {
      const saved = editing
        ? await api<OltSaved>(`/olts/${olt.id}`, { method: "PATCH", body })
        : await api<OltSaved>("/olts", { method: "POST", body });
      onSaved(saved);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "não foi possível salvar");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-6" aria-label={editing ? "Editar OLT" : "Nova OLT"}>
      <Section title="Identificação">
        <Field label="Nome" hint="como a OLT aparece no painel, ex.: olt-centro">
          <input className={inputClass} value={form.name} onChange={set("name")} required maxLength={80} />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
          />
          Coleta ativada
        </label>
      </Section>

      <Section title="Acesso SNMP">
        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-2">
            <Field label="Endereço (IP ou nome)">
              <input className={inputClass} value={form.host} onChange={set("host")} required placeholder="10.0.0.2" />
            </Field>
          </div>
          <Field label="Porta">
            <input className={inputClass} type="number" min={1} max={65535} value={form.snmp_port} onChange={set("snmp_port")} required />
          </Field>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Versão">
            <input className={inputClass} value="v2c" disabled />
          </Field>
          <div className="col-span-2">
            <Field
              label="Community"
              hint={editing ? "deixe em branco para manter a atual" : "fica cifrada no banco e nunca é exibida de volta"}
            >
              <input
                className={inputClass}
                type="password"
                value={form.community}
                onChange={set("community")}
                required={!editing}
                autoComplete="off"
                placeholder={editing ? "••••••" : ""}
              />
            </Field>
          </div>
        </div>
        <div className="flex items-start gap-3">
          <Button variant="secondary" onClick={testConnection} disabled={!canTest || testing}>
            {testing ? "Testando…" : "Testar conexão"}
          </Button>
          {test && <TestResult test={test} />}
        </div>
      </Section>

      <Section title="Intervalos de coleta">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Estado das ONUs (s)" hint="mínimo 30 s">
            <input className={inputClass} type="number" min={30} max={3600} value={form.status_interval_s} onChange={set("status_interval_s")} required />
          </Field>
          <Field label="Potência óptica (s)" hint="mínimo 60 s">
            <input className={inputClass} type="number" min={60} max={86400} value={form.optical_interval_s} onChange={set("optical_interval_s")} required />
          </Field>
        </div>
      </Section>

      <Section title="Localização no mapa (opcional)">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Latitude" hint="ex.: -22.2139 (clique com o botão direito no Google Maps para copiar)">
            <input className={inputClass} inputMode="decimal" value={form.lat} onChange={set("lat")} placeholder="-22.2139" />
          </Field>
          <Field label="Longitude" hint="sem coordenada, o mapa usa o centro dos clientes da OLT">
            <input className={inputClass} inputMode="decimal" value={form.lon} onChange={set("lon")} placeholder="-49.9458" />
          </Field>
        </div>
      </Section>

      {error && (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
        <Button variant="secondary" onClick={onCancel}>
          Cancelar
        </Button>
        <Button type="submit" disabled={saving}>
          {saving ? "Salvando e descobrindo ONUs…" : "Salvar"}
        </Button>
      </div>
    </form>
  );
}

function TestResult({ test }: { test: ConnectionTest }) {
  if (!test.ok) {
    return (
      <p role="status" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
        {test.error}
      </p>
    );
  }
  const vendor = test.vendor ? test.vendor[0].toUpperCase() + test.vendor.slice(1) : "";
  return (
    <p role="status" className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
      <strong>
        {vendor} {test.model}
      </strong>{" "}
      ({test.sys_name}) · {test.pon_ports?.length ?? 0} portas PON · {test.onus} ONUs
    </p>
  );
}
