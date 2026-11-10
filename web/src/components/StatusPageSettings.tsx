import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { useToast } from "../toast";
import { Button, Card, Field, inputClass, Loading } from "./ui";

interface Settings {
  enabled: boolean;
  slug: string;
}

/** Cartão do admin: liga a página pública de status e escolhe o endereço. */
export function StatusPageSettings() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery({ queryKey: ["status-page"], queryFn: () => api<Settings>("/status-page") });
  const [form, setForm] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  const save = useMutation({
    mutationFn: (body: Settings) => api<Settings>("/status-page", { method: "PUT", body }),
    onSuccess: (saved) => {
      qc.setQueryData(["status-page"], saved);
      setError(null);
      toast(saved.enabled ? "Página pública ligada" : "Página pública desligada", "ok");
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "não foi possível salvar"),
  });

  const url = data ? `${window.location.origin}/status/${data.slug}` : "";

  function submit(e: FormEvent) {
    e.preventDefault();
    if (form) save.mutate({ ...form, slug: form.slug.trim().toLowerCase() });
  }

  return (
    <Card title="Página pública de status">
      {!form ? (
        <Loading rows={2} />
      ) : (
        <form onSubmit={submit} className="max-w-xl space-y-4 p-4" aria-label="Página pública de status">
          <p className="text-sm text-slate-600">
            Um link para seus clientes verem se há interrupção no bairro deles, sem ligar para o suporte. Mostra só bairros e horários: nada
            de nome de cliente, de OLT ou motivo interno de manutenção.
          </p>
          <label className="flex items-center gap-2 text-sm font-medium">
            <input
              type="checkbox"
              className="size-4 accent-brand-600"
              checked={form.enabled}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
            />
            Página pública ligada
          </label>
          <Field label="Endereço" hint="letras minúsculas, números e hífen">
            <input
              className={inputClass}
              value={form.slug}
              onChange={(e) => setForm({ ...form, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-") })}
              maxLength={48}
              required
            />
          </Field>
          {error && (
            <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? "Salvando…" : "Salvar"}
            </Button>
            {data?.enabled && (
              <>
                <a href={url} target="_blank" rel="noreferrer" className="text-sm font-medium text-brand-600 hover:underline">
                  {url.replace(/^https?:\/\//, "")}
                </a>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => navigator.clipboard?.writeText(url).then(() => toast("Link copiado", "ok"))}
                >
                  Copiar link
                </Button>
              </>
            )}
          </div>
        </form>
      )}
    </Card>
  );
}
