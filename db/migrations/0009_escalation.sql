-- Escalonamento: alarme sem ninguém assumir depois de X minutos avisa um
-- canal a mais (supervisor, gerente). Pode haver vários níveis, por exemplo:
-- crítico sem responsável há 10 min -> supervisor; há 30 min -> gerente.
-- Quem verifica é o notificador (a cada ~30 s), com o papel lumio_system.

CREATE TABLE escalation_rules (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name           text NOT NULL CHECK (length(name) BETWEEN 2 AND 80),
    min_severity   text NOT NULL DEFAULT 'critical' CHECK (min_severity IN ('critical', 'major', 'minor', 'warning')),
    after_minutes  int  NOT NULL CHECK (after_minutes BETWEEN 1 AND 1440),
    channel_id     uuid NOT NULL REFERENCES notification_channels(id) ON DELETE CASCADE,
    enabled        boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- cada regra escala um alarme uma vez só
CREATE TABLE alarm_escalations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    alarm_id    uuid NOT NULL REFERENCES alarms(id) ON DELETE CASCADE,
    rule_id     uuid NOT NULL REFERENCES escalation_rules(id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (alarm_id, rule_id)
);

ALTER TABLE escalation_rules ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON escalation_rules
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
ALTER TABLE alarm_escalations ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON alarm_escalations
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON escalation_rules TO lumio_app;
GRANT SELECT ON escalation_rules TO lumio_system;
GRANT SELECT ON alarm_escalations TO lumio_app;
GRANT SELECT, INSERT ON alarm_escalations TO lumio_system;

-- nova entrega: "escalonado" (alarme sem responsável há muito tempo)
ALTER TABLE notifications DROP CONSTRAINT notifications_event_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_event_check
    CHECK (event IN ('opened', 'cleared', 'test', 'escalated'));
