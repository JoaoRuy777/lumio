-- Proteção do login contra força bruta.
--
-- Cada tentativa (certa ou errada) fica registrada por e-mail e por IP. Com
-- muitas falhas seguidas numa janela de 15 min, o login daquele e-mail (ou IP)
-- fica travado por 15 min a partir da última falha; nesse tempo a senha nem é
-- conferida. Vale também para e-mails que não existem: a resposta é a mesma,
-- então ninguém descobre quem tem conta.
--
-- A tabela não pertence a um provedor (o e-mail pode nem existir), então a API
-- só mexe nela pelas duas funções abaixo (SECURITY DEFINER).

CREATE TABLE login_attempts (
    id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email   text NOT NULL,
    ip      text,
    ok      boolean NOT NULL,
    at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX login_attempts_email_idx ON login_attempts (email, at DESC);
CREATE INDEX login_attempts_ip_idx ON login_attempts (ip, at DESC) WHERE NOT ok;
ALTER TABLE login_attempts ENABLE ROW LEVEL SECURITY;           -- sem política: lumio_app não lê nem escreve

-- Segundos que faltam para liberar (0 = pode tentar).
--   e-mail: 5 falhas desde o último acerto, dentro de 15 min
--   IP:     20 falhas dentro de 15 min (vários e-mails a partir do mesmo lugar)
CREATE FUNCTION lumio_login_wait(p_email text, p_ip text) RETURNS integer
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    WITH by_email AS (
        SELECT count(*) AS n, max(at) AS last FROM login_attempts
        WHERE email = lower(p_email) AND NOT ok AND at > now() - interval '15 minutes'
          AND at > coalesce((SELECT max(at) FROM login_attempts WHERE email = lower(p_email) AND ok), '-infinity')
    ), by_ip AS (
        SELECT count(*) AS n, max(at) AS last FROM login_attempts
        WHERE p_ip IS NOT NULL AND ip = p_ip AND NOT ok AND at > now() - interval '15 minutes'
    )
    SELECT greatest(
        CASE WHEN e.n >= 5 THEN ceil(extract(epoch FROM e.last + interval '15 minutes' - now())) ELSE 0 END,
        CASE WHEN i.n >= 20 THEN ceil(extract(epoch FROM i.last + interval '15 minutes' - now())) ELSE 0 END,
        0)::integer
    FROM by_email e, by_ip i
$$;

CREATE FUNCTION lumio_login_record(p_email text, p_ip text, p_ok boolean) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    INSERT INTO login_attempts (email, ip, ok) VALUES (lower(p_email), p_ip, p_ok);
    DELETE FROM login_attempts WHERE at < now() - interval '1 day';      -- não guarda histórico (LGPD)
$$;

REVOKE ALL ON FUNCTION lumio_login_wait(text, text), lumio_login_record(text, text, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION lumio_login_wait(text, text), lumio_login_record(text, text, boolean) TO lumio_app;
