-- Clientes do provedor e localização para o mapa.
--
-- O cliente é ligado à ONU pelo SERIAL (como no sistema do provedor): a
-- importação não depende de a ONU já ter sido descoberta, e a ligação se
-- refaz sozinha se a ONU trocar de porta.

CREATE TABLE customers (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    onu_serial  text NOT NULL,
    code        text,                 -- código do cliente no sistema do provedor
    name        text NOT NULL,
    phone       text,
    address     text,
    district    text,
    city        text,
    plan        text,
    lat         double precision CHECK (lat BETWEEN -90 AND 90),
    lon         double precision CHECK (lon BETWEEN -180 AND 180),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, onu_serial)
);
CREATE INDEX customers_tenant_name_idx ON customers (tenant_id, lower(name));

ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON customers
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON customers TO lumio_app;
GRANT SELECT ON customers TO lumio_system;          -- e-mails de alerta citam o cliente

-- Onde fica cada OLT (sem coordenada, o mapa usa o centro dos clientes dela)
ALTER TABLE olts ADD COLUMN lat double precision CHECK (lat BETWEEN -90 AND 90);
ALTER TABLE olts ADD COLUMN lon double precision CHECK (lon BETWEEN -180 AND 180);
