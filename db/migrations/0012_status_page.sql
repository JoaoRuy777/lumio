-- Página pública de status do provedor (/status/<slug>).
--
-- O cliente final abre o link e vê se há interrupção no bairro dele, sem
-- precisar ligar para o suporte. A página começa DESLIGADA: o administrador
-- liga e escolhe o endereço (slug) na tela da conta.
--
-- O que é público, e só isso: o nome do provedor, as interrupções em aberto
-- (rompimento de fibra ou equipamento fora do ar), as manutenções programadas
-- e o histórico de 7 dias, sempre por BAIRRO. Nada de nome de cliente,
-- contagem de clientes, nome de OLT/PON ou motivo interno da manutenção.

ALTER TABLE tenants ADD COLUMN status_page_enabled boolean NOT NULL DEFAULT false;

-- Bairros atendidos por uma OLT inteira (p_pon nulo) ou por uma PON.
CREATE FUNCTION lumio_status_districts(p_tenant uuid, p_olt uuid, p_pon uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT coalesce(jsonb_agg(DISTINCT c.district ORDER BY c.district), '[]'::jsonb)
    FROM customers c
    JOIN onus n ON n.tenant_id = c.tenant_id AND n.serial = c.onu_serial
    WHERE c.tenant_id = p_tenant AND nullif(trim(c.district), '') IS NOT NULL
      AND n.olt_id = p_olt AND (p_pon IS NULL OR n.pon_id = p_pon)
$$;

-- Tudo o que a página mostra, num JSON. NULL = endereço inexistente ou página desligada.
CREATE FUNCTION lumio_public_status(p_slug text) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT jsonb_build_object(
        'name', t.name,
        'updated_at', now(),
        'incidents', (
            SELECT coalesce(jsonb_agg(jsonb_build_object(
                       'kind', a.kind, 'since', a.created_at,
                       'districts', lumio_status_districts(t.id, a.olt_id, a.pon_id))
                   ORDER BY a.created_at), '[]'::jsonb)
            FROM alarms a
            WHERE a.tenant_id = t.id AND a.status <> 'cleared' AND a.parent_id IS NULL
              AND a.kind IN ('pon_fiber_cut', 'olt_unreachable') AND a.maintenance_id IS NULL),
        'maintenance', (
            SELECT coalesce(jsonb_agg(jsonb_build_object(
                       'starts_at', m.starts_at, 'ends_at', m.ends_at, 'in_progress', m.starts_at <= now(),
                       'districts', lumio_status_districts(t.id, m.olt_id, m.pon_id))
                   ORDER BY m.starts_at), '[]'::jsonb)
            FROM maintenance_windows m
            WHERE m.tenant_id = t.id AND m.cancelled_at IS NULL AND m.ends_at > now()
              AND m.starts_at < now() + interval '7 days'),
        'history', (
            SELECT coalesce(jsonb_agg(jsonb_build_object(
                       'kind', a.kind, 'since', a.created_at, 'until', a.cleared_at,
                       'districts', lumio_status_districts(t.id, a.olt_id, a.pon_id))
                   ORDER BY a.created_at DESC), '[]'::jsonb)
            FROM alarms a
            WHERE a.tenant_id = t.id AND a.status = 'cleared' AND a.parent_id IS NULL
              AND a.kind IN ('pon_fiber_cut', 'olt_unreachable') AND a.maintenance_id IS NULL
              AND a.cleared_at > now() - interval '7 days')
    )
    FROM tenants t
    WHERE t.slug = lower(p_slug) AND t.status_page_enabled
$$;

REVOKE ALL ON FUNCTION lumio_status_districts(uuid, uuid, uuid), lumio_public_status(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION lumio_public_status(text) TO lumio_app;
