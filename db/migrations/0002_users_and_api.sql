-- Sprint 3: usuários, community SNMP cifrada e as funções que a API usa
-- quando ainda não sabe o tenant (login/cadastro) ou precisa de todos (coletor).
--
-- A API conecta como lumio_app, sempre sujeita a RLS. As três funções abaixo
-- são SECURITY DEFINER (rodam como o dono do esquema) e fazem só uma coisa
-- cada, com search_path fixo para não serem sequestradas.

CREATE TABLE users (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email          text NOT NULL,
    name           text NOT NULL,
    password_hash  text NOT NULL,
    role           text NOT NULL DEFAULT 'admin' CHECK (role IN ('admin', 'operator')),
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email_idx ON users (lower(email));

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON users
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

ALTER TABLE olts ADD COLUMN community_enc text;          -- Fernet, chave em LUMIO_SECRET_KEY
ALTER TABLE olts ADD COLUMN discovered_at timestamptz;

GRANT SELECT, INSERT, UPDATE, DELETE ON users TO lumio_app, lumio_system;

-- ------------------------------------------------------------------ login
CREATE FUNCTION lumio_login_lookup(p_email text)
RETURNS TABLE (user_id uuid, tenant_id uuid, password_hash text, role text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT id, tenant_id, password_hash, role FROM users WHERE lower(email) = lower(p_email)
$$;

-- ------------------------------------------------------------------ cadastro
CREATE FUNCTION lumio_signup(p_tenant_name text, p_slug text, p_email text, p_name text, p_password_hash text)
RETURNS TABLE (tenant_id uuid, user_id uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE t uuid; u uuid;
BEGIN
    INSERT INTO tenants (name, slug) VALUES (p_tenant_name, p_slug) RETURNING id INTO t;
    INSERT INTO users (tenant_id, email, name, password_hash, role)
        VALUES (t, p_email, p_name, p_password_hash, 'admin') RETURNING id INTO u;
    RETURN QUERY SELECT t, u;
END $$;

-- ------------------------------------------------------------------ coletor
CREATE FUNCTION lumio_collector_olts()
RETURNS TABLE (id uuid, tenant_id uuid, name text, host text, snmp_port integer, community_enc text,
               vendor text, sys_name text, status_interval_s integer, optical_interval_s integer)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT id, tenant_id, name, host, snmp_port, community_enc, vendor, sys_name, status_interval_s, optical_interval_s
    FROM olts WHERE enabled AND host IS NOT NULL AND community_enc IS NOT NULL
$$;

REVOKE ALL ON FUNCTION lumio_login_lookup(text), lumio_signup(text, text, text, text, text), lumio_collector_olts() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION lumio_login_lookup(text), lumio_signup(text, text, text, text, text), lumio_collector_olts() TO lumio_app;
