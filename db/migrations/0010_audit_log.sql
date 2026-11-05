-- Log de auditoria: quem fez o quê, quando e de onde.
--
-- Só cresce: a API (lumio_app) pode inserir e ler, nunca alterar nem apagar.
-- O nome de quem fez fica copiado na linha, para o registro continuar legível
-- mesmo depois de o usuário ser removido.

CREATE TABLE audit_log (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    at            timestamptz NOT NULL DEFAULT clock_timestamp(),
    actor_id      uuid REFERENCES users(id) ON DELETE SET NULL,
    actor_name    text,
    action        text NOT NULL,                 -- "olt.create", "auth.login_failed", ...
    target_type   text,                          -- "olt", "user", "channel", ...
    target_id     uuid,
    target_label  text,                          -- nome legível do alvo no momento da ação
    details       jsonb NOT NULL DEFAULT '{}',
    ip            text
);
CREATE INDEX audit_log_tenant_at_idx ON audit_log (tenant_id, at DESC);

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON audit_log
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT ON audit_log TO lumio_app;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM lumio_app, lumio_system;

-- A troca de senha pelo link do e-mail acontece fora da sessão (sem tenant):
-- a própria função registra no log.
CREATE OR REPLACE FUNCTION lumio_password_reset_consume(p_token_hash text, p_password_hash text)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE r_id uuid; r_user uuid;
BEGIN
    SELECT id, user_id INTO r_id, r_user FROM password_resets
     WHERE token_hash = p_token_hash AND used_at IS NULL AND expires_at > now()
     FOR UPDATE;
    IF r_id IS NULL THEN
        RETURN false;
    END IF;
    UPDATE password_resets SET used_at = now(), token_enc = NULL WHERE id = r_id;
    UPDATE users SET password_hash = p_password_hash, session_version = session_version + 1 WHERE id = r_user;
    INSERT INTO audit_log (tenant_id, actor_id, actor_name, action, target_type, target_id, target_label)
    SELECT tenant_id, id, name, 'auth.password_reset', 'user', id, email FROM users WHERE id = r_user;
    RETURN true;
END $$;
