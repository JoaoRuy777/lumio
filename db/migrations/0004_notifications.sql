-- Sprint 5: notificações por e-mail e webhook.
--
-- notification_channels: para onde avisar (por provedor).
-- notifications: fila de entregas ("outbox"). O worker grava a entrega na MESMA
-- transação do alarme, então nunca existe alarme sem aviso nem aviso de alarme
-- que não foi gravado. O notificador lê a fila, envia e tenta de novo se falhar.

CREATE TABLE notification_channels (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name          text NOT NULL,
    type          text NOT NULL CHECK (type IN ('email', 'webhook')),
    target        text NOT NULL,             -- e-mail ou URL
    secret_enc    text,                      -- webhook: segredo do HMAC, cifrado (Fernet)
    min_severity  text NOT NULL DEFAULT 'major' CHECK (min_severity IN ('critical', 'major', 'minor', 'warning')),
    notify_clear  boolean NOT NULL DEFAULT true,   -- avisar também quando normalizar
    enabled       boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

CREATE TABLE notifications (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    channel_id       uuid NOT NULL REFERENCES notification_channels(id) ON DELETE CASCADE,
    alarm_id         uuid REFERENCES alarms(id) ON DELETE CASCADE,     -- NULL = mensagem de teste
    event            text NOT NULL CHECK (event IN ('opened', 'cleared', 'test')),
    status           text NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'sending', 'sent', 'failed', 'suppressed')),
    attempts         integer NOT NULL DEFAULT 0,
    last_error       text,
    next_attempt_at  timestamptz NOT NULL DEFAULT now(),
    sent_at          timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now()
);
-- uma entrega por canal, alarme e evento (reprocessar o stream não duplica e-mail)
CREATE UNIQUE INDEX notifications_once_idx ON notifications (channel_id, alarm_id, event) WHERE alarm_id IS NOT NULL;
CREATE INDEX notifications_due_idx ON notifications (next_attempt_at) WHERE status = 'pending';
CREATE INDEX notifications_channel_idx ON notifications (channel_id, created_at DESC);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['notification_channels', 'notifications'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting(''app.tenant_id'', true)::uuid) '
            'WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true)::uuid)', t);
    END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON notification_channels, notifications TO lumio_app, lumio_system;

-- Relatórios: alarmes por período
CREATE INDEX alarms_tenant_event_ts_idx ON alarms (tenant_id, event_ts);
