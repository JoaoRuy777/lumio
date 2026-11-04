-- Sprint 4: reconhecimento de alarmes pelo operador (o alarme continua aberto
-- até a falha passar; "reconhecido" só diz que alguém já está cuidando).
ALTER TABLE alarms ADD COLUMN acknowledged_at timestamptz;
ALTER TABLE alarms ADD COLUMN acknowledged_by uuid REFERENCES users(id) ON DELETE SET NULL;

-- Listagens do painel: abertos por tenant e histórico por OLT
CREATE INDEX alarms_tenant_open_idx ON alarms (tenant_id, created_at DESC) WHERE status <> 'cleared';
CREATE INDEX alarms_olt_created_idx ON alarms (olt_id, created_at DESC);
CREATE INDEX onus_tenant_serial_idx ON onus (tenant_id, serial);
