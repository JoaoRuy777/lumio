"""Escalonamento pelo notificador: alarme sem ninguém assumir avisa outro canal."""

from email import message_from_bytes, policy

from lumio_worker.notify import Notifier, SmtpConfig

from .conftest import needs_db, rec
from .test_notify import KEY, add_channel, onus, smtp  # noqa: F401  (fixture smtp)

pytestmark = needs_db


async def add_rule(pool, tenant_id, channel_id, after=10, min_severity="critical", name="Supervisor"):
    return await pool.fetchval(
        "INSERT INTO escalation_rules (tenant_id, name, min_severity, after_minutes, channel_id) "
        "VALUES ($1, $2, $3, $4, $5) RETURNING id", tenant_id, name, min_severity, after, channel_id)


async def age(pool, kind, minutes):
    """Envelhece o alarme (como se tivesse aberto há N minutos)."""
    await pool.execute("UPDATE alarms SET created_at = now() - make_interval(mins => $2) WHERE kind = $1", kind, minutes)


async def test_escala_critico_sem_responsavel_uma_vez_por_regra(processor, pool, smtp):
    inbox, cfg = smtp
    tid = processor.tenant_id
    supervisor = await add_channel(pool, tid, "supervisor", "email", "supervisor@a.com.br", min_severity="critical")
    gerente = await add_channel(pool, tid, "gerente", "email", "gerente@a.com.br", min_severity="critical")
    await add_rule(pool, tid, supervisor, after=10)
    await add_rule(pool, tid, gerente, after=30, name="Gerente")
    await processor.handle(rec("event", kind="olt_unreachable", source="poll"))
    await pool.execute("UPDATE notifications SET status = 'sent'")          # o aviso normal já saiu
    notifier = Notifier(pool, KEY, cfg, public_url="https://painel.lumio.test")

    assert await notifier.escalate() == 0                                     # ainda no prazo
    await age(pool, "olt_unreachable", 12)
    assert await notifier.escalate() == 1                                     # 10 min: supervisor
    assert await notifier.escalate() == 0                                     # não repete
    await age(pool, "olt_unreachable", 31)
    assert await notifier.escalate() == 1                                     # 30 min: gerente

    notifier._next_escalation = float("inf")
    await notifier.run_once()
    assert sorted(m.rcpt_tos[0] for m in inbox.messages) == ["gerente@a.com.br", "supervisor@a.com.br"]
    parsed = message_from_bytes(inbox.messages[0].content, policy=policy.default)
    assert parsed["Subject"].startswith("[Lumio] ESCALONADO: OLT inacessível — olt-1 sem responsável há ")
    text = parsed.get_body(preferencelist=("plain",)).get_content()
    assert text.startswith("Ninguém assumiu este alarme há ")
    assert "ESCALONADO" in parsed.get_body(preferencelist=("html",)).get_content()
    assert await pool.fetchval("SELECT count(*) FROM alarm_escalations") == 2


async def test_nao_escala_assumido_em_manutencao_ou_abaixo_do_nivel(processor, pool):
    tid = processor.tenant_id
    supervisor = await add_channel(pool, tid, "supervisor", "email", "supervisor@a.com.br", min_severity="critical")
    await add_rule(pool, tid, supervisor, after=5, min_severity="major")
    user = await pool.fetchval(
        "INSERT INTO users (tenant_id, email, name, password_hash, role) "
        "VALUES ($1, 'op@a.com.br', 'Op', 'x', 'operator') RETURNING id", tid)
    await processor.handle(rec("onu_status", onus=onus()))
    await processor.handle(rec("event", kind="olt_unreachable", source="poll"))                       # crítico
    await processor.handle(rec("event", kind="olt_cpu_high", source="trap", cpu=95.0, olt="olt-2"))    # grave
    await processor.handle(rec("event", kind="onu_rx_low", source="trap", pon="0/1/0", onu=1, rx_dbm=-28.0))  # aviso
    await pool.execute("UPDATE alarms SET assigned_to = $1 WHERE kind = 'olt_unreachable'", user)
    olt2 = await pool.fetchval("SELECT olt_id FROM alarms WHERE kind = 'olt_cpu_high'")
    mid = await pool.fetchval(
        "INSERT INTO maintenance_windows (tenant_id, olt_id, reason, starts_at, ends_at) "
        "VALUES ($1, $2, 'firmware', now() - interval '1 hour', now() + interval '1 hour') RETURNING id", tid, olt2)
    await pool.execute("UPDATE alarms SET maintenance_id = $1 WHERE kind = 'olt_cpu_high'", mid)
    await pool.execute("UPDATE alarms SET created_at = now() - interval '1 hour'")

    notifier = Notifier(pool, KEY, SmtpConfig(host=None))
    assert await notifier.escalate() == 0       # assumido, em manutenção e abaixo do nível da regra

    await pool.execute("UPDATE alarms SET maintenance_id = NULL")
    await pool.execute("UPDATE escalation_rules SET enabled = false")
    assert await notifier.escalate() == 0       # regra desligada
    await pool.execute("UPDATE escalation_rules SET enabled = true")
    assert await notifier.escalate() == 1       # o grave, fora da manutenção e sem responsável
    assert await pool.fetchval(
        "SELECT a.kind FROM alarm_escalations e JOIN alarms a ON a.id = e.alarm_id") == "olt_cpu_high"
