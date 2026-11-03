-- Esquema inicial: tenants, inventário de OLTs/PONs/ONUs, séries temporais e alarmes.
-- Toda tabela com tenant_id tem RLS: o papel da API (lumio_app) só enxerga as
-- linhas do tenant definido em app.tenant_id. O worker (lumio_system) tem BYPASSRLS.

CREATE TABLE tenants (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    slug        text NOT NULL UNIQUE,
    olt_limit   integer NOT NULL DEFAULT 2,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE olts (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                text NOT NULL,
    host                text,
    snmp_port           integer NOT NULL DEFAULT 161,
    vendor              text,
    model               text,
    sys_name            text,
    status_interval_s   integer NOT NULL DEFAULT 60,
    optical_interval_s  integer NOT NULL DEFAULT 300,
    enabled             boolean NOT NULL DEFAULT true,
    reachable           boolean,
    last_poll_at        timestamptz,
    last_error          text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

CREATE TABLE pon_ports (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    olt_id      uuid NOT NULL REFERENCES olts(id) ON DELETE CASCADE,
    name        text NOT NULL,              -- "0/1/2"
    UNIQUE (olt_id, name)
);

CREATE TABLE onus (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    olt_id          uuid NOT NULL REFERENCES olts(id) ON DELETE CASCADE,
    pon_id          uuid NOT NULL REFERENCES pon_ports(id) ON DELETE CASCADE,
    onu_index       integer NOT NULL,
    serial          text,
    online          boolean,
    rx_dbm          real,
    tx_dbm          real,
    last_change_at  timestamptz,            -- última troca online/offline
    last_seen_at    timestamptz,
    UNIQUE (pon_id, onu_index)
);
CREATE INDEX onus_olt_idx ON onus (olt_id);

CREATE TABLE optical_readings (
    ts          timestamptz NOT NULL,
    tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    onu_id      uuid NOT NULL REFERENCES onus(id) ON DELETE CASCADE,
    rx_dbm      real,
    tx_dbm      real
);
CREATE INDEX optical_readings_onu_ts_idx ON optical_readings (onu_id, ts DESC);

CREATE TABLE olt_health_readings (
    ts           timestamptz NOT NULL,
    tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    olt_id       uuid NOT NULL REFERENCES olts(id) ON DELETE CASCADE,
    cpu          real,
    temperature  real,
    uptime_s     double precision
);
CREATE INDEX olt_health_readings_olt_ts_idx ON olt_health_readings (olt_id, ts DESC);

CREATE TABLE alarms (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    olt_id         uuid NOT NULL REFERENCES olts(id) ON DELETE CASCADE,
    pon_id         uuid REFERENCES pon_ports(id) ON DELETE CASCADE,
    onu_id         uuid REFERENCES onus(id) ON DELETE CASCADE,
    kind           text NOT NULL,          -- onu_offline, onu_rx_low, pon_fiber_cut, olt_unreachable, olt_cpu_high
    severity       text NOT NULL CHECK (severity IN ('critical', 'major', 'minor', 'warning')),
    dedup_key      text NOT NULL,
    status         text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'acknowledged', 'cleared')),
    parent_id      uuid REFERENCES alarms(id) ON DELETE SET NULL,
    source         text NOT NULL,          -- trap | poll
    occurrences    integer NOT NULL DEFAULT 1,
    details        jsonb NOT NULL DEFAULT '{}',
    event_ts       timestamptz NOT NULL,   -- quando o coletor recebeu o evento
    created_at     timestamptz NOT NULL DEFAULT clock_timestamp(),
    latency_ms     real,                   -- created_at - event_ts
    first_seen_at  timestamptz NOT NULL,
    last_seen_at   timestamptz NOT NULL,
    cleared_at     timestamptz
);
-- Deduplicação: no máximo um alarme não encerrado por chave e tenant
CREATE UNIQUE INDEX alarms_open_dedup_idx ON alarms (tenant_id, dedup_key) WHERE status <> 'cleared';
CREATE INDEX alarms_tenant_created_idx ON alarms (tenant_id, created_at DESC);
CREATE INDEX alarms_parent_idx ON alarms (parent_id) WHERE parent_id IS NOT NULL;

-- ------------------------------------------------------------------ RLS
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['olts', 'pon_ports', 'onus', 'optical_readings', 'olt_health_readings', 'alarms'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting(''app.tenant_id'', true)::uuid) '
            'WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true)::uuid)', t);
    END LOOP;
END $$;

-- tenants: cada tenant só vê a si mesmo
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_self ON tenants USING (id = current_setting('app.tenant_id', true)::uuid);

-- ------------------------------------------------------------------ permissões
GRANT USAGE ON SCHEMA public TO lumio_app, lumio_system;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO lumio_app, lumio_system;
REVOKE ALL ON schema_migrations FROM lumio_app, lumio_system;
