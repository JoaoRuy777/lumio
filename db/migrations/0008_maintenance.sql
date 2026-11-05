-- Janelas de manutenção programada.
--
-- Durante a janela, os alarmes da OLT inteira (pon_id nulo) ou de uma PON
-- continuam aparecendo no painel, mas ficam marcados como "em manutenção" e
-- não geram e-mail/webhook. Quem decide é o worker, no momento em que abre o
-- alarme (alarms.maintenance_id).

CREATE TABLE maintenance_windows (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    olt_id        uuid NOT NULL REFERENCES olts(id) ON DELETE CASCADE,
    pon_id        uuid REFERENCES pon_ports(id) ON DELETE CASCADE,   -- nulo: a OLT inteira
    reason        text NOT NULL CHECK (length(reason) BETWEEN 3 AND 300),
    starts_at     timestamptz NOT NULL,
    ends_at       timestamptz NOT NULL,
    created_by    uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    cancelled_at  timestamptz,                                      -- cancelada antes de começar
    CHECK (ends_at > starts_at)
);
CREATE INDEX maintenance_windows_active_idx ON maintenance_windows (olt_id, starts_at, ends_at)
    WHERE cancelled_at IS NULL;

ALTER TABLE maintenance_windows ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON maintenance_windows
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON maintenance_windows TO lumio_app;
GRANT SELECT ON maintenance_windows TO lumio_system;               -- o worker consulta ao abrir alarme

ALTER TABLE alarms ADD COLUMN maintenance_id uuid REFERENCES maintenance_windows(id) ON DELETE SET NULL;
