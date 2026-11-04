-- Atendimento de chamados pelo NOC.
--
-- Chamado = alarme principal (parent_id NULL; as ONUs de um rompimento contam
-- dentro dele). O operador ASSUME (ou transfere), ANOTA o que fez e ENCERRA
-- com a causa. O alarme de rede continua com o próprio ciclo (ativo ->
-- normalizado); o atendimento é a parte humana.
--
-- Indicadores (relatório de atendimento):
--   TME (tempo médio de espera)      = first_assigned_at - created_at
--   TMA (tempo médio de atendimento) = work_closed_at   - first_assigned_at
--   tempo com cada operador          = soma dos trechos entre os eventos
--                                      "assigned" -> próximo assigned/closed

ALTER TABLE alarms
    ADD COLUMN assigned_to        uuid REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN assigned_at        timestamptz,
    ADD COLUMN first_assigned_at  timestamptz,
    ADD COLUMN work_closed_at     timestamptz,
    ADD COLUMN work_closed_by     uuid REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN resolution_cause   text CHECK (resolution_cause IN (
        'fiber_third_party', 'fiber_natural', 'power', 'equipment', 'customer',
        'maintenance', 'configuration', 'no_fault', 'other')),
    ADD COLUMN resolution_notes   text;

CREATE INDEX alarms_assigned_open_idx ON alarms (tenant_id, assigned_to) WHERE work_closed_at IS NULL;

-- Linha do tempo do chamado (as partes automáticas, como abertura, normalização
-- e notificações, vêm das próprias tabelas na hora de mostrar)
CREATE TABLE alarm_events (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    alarm_id    uuid NOT NULL REFERENCES alarms(id) ON DELETE CASCADE,
    kind        text NOT NULL CHECK (kind IN ('assigned', 'note', 'closed', 'reopened')),
    actor_id    uuid REFERENCES users(id) ON DELETE SET NULL,     -- quem fez
    target_id   uuid REFERENCES users(id) ON DELETE SET NULL,     -- "assigned": quem ficou com o chamado
    body        text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX alarm_events_alarm_idx ON alarm_events (alarm_id, created_at);
CREATE INDEX alarm_events_tenant_idx ON alarm_events (tenant_id, created_at);

ALTER TABLE alarm_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON alarm_events
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON alarm_events TO lumio_app;          -- linha do tempo não se edita
GRANT SELECT ON alarm_events TO lumio_system;
