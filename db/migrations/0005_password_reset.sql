-- Troca de senha e "esqueci minha senha".
--
-- session_version: vai dentro do token (JWT, claim "sv") e sobe a cada troca ou
-- redefinição de senha. Token com versão antiga deixa de valer: as outras
-- sessões abertas caem na hora (sem depender de relógio).
--
-- password_resets: um pedido de redefinição. Guarda o HASH do token (é por ele
-- que o link é conferido) e o token cifrado com a LUMIO_SECRET_KEY só até o
-- notificador mandar o e-mail; depois do envio a cópia cifrada é apagada.
-- A API (lumio_app) não lê esta tabela: tudo passa pelas duas funções abaixo.

ALTER TABLE users ADD COLUMN session_version integer NOT NULL DEFAULT 0;

-- o login passa a devolver a versão da sessão (muda o tipo de retorno: recria)
DROP FUNCTION lumio_login_lookup(text);
CREATE FUNCTION lumio_login_lookup(p_email text)
RETURNS TABLE (user_id uuid, tenant_id uuid, password_hash text, role text, session_version integer)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT id, tenant_id, password_hash, role, session_version FROM users WHERE lower(email) = lower(p_email)
$$;
REVOKE ALL ON FUNCTION lumio_login_lookup(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION lumio_login_lookup(text) TO lumio_app;

CREATE TABLE password_resets (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  text NOT NULL UNIQUE,
    token_enc   text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    sent_at     timestamptz,
    used_at     timestamptz,
    attempts    integer NOT NULL DEFAULT 0,
    last_error  text
);
CREATE INDEX password_resets_pending_idx ON password_resets (created_at) WHERE sent_at IS NULL AND token_enc IS NOT NULL;

ALTER TABLE password_resets ENABLE ROW LEVEL SECURITY;      -- sem política: lumio_app não vê nada
GRANT SELECT, UPDATE ON password_resets TO lumio_system;     -- o notificador envia os e-mails

-- ------------------------------------------------------------------ pedido
-- Devolve true se criou o pedido. A API responde igual nos dois casos, para não
-- revelar quais e-mails existem. No máximo 3 pedidos por usuário por hora; um
-- pedido novo invalida os anteriores ainda não usados.
CREATE FUNCTION lumio_password_reset_request(p_email text, p_token_hash text, p_token_enc text)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE u uuid;
BEGIN
    SELECT id INTO u FROM users WHERE lower(email) = lower(p_email);
    IF u IS NULL THEN
        RETURN false;
    END IF;
    IF (SELECT count(*) FROM password_resets WHERE user_id = u AND created_at > now() - interval '1 hour') >= 3 THEN
        RETURN false;
    END IF;
    UPDATE password_resets SET used_at = now(), token_enc = NULL WHERE user_id = u AND used_at IS NULL;
    INSERT INTO password_resets (user_id, token_hash, token_enc, expires_at)
        VALUES (u, p_token_hash, p_token_enc, now() + interval '1 hour');
    RETURN true;
END $$;

-- ------------------------------------------------------------------ uso do link
-- Troca a senha se o token existe, não foi usado e não venceu. Uso único.
CREATE FUNCTION lumio_password_reset_consume(p_token_hash text, p_password_hash text)
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
    RETURN true;
END $$;

REVOKE ALL ON FUNCTION lumio_password_reset_request(text, text, text), lumio_password_reset_consume(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION lumio_password_reset_request(text, text, text), lumio_password_reset_consume(text, text) TO lumio_app;
