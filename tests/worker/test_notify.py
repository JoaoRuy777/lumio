"""Notificações (sprint 5): fila no banco + envio por e-mail e webhook.

Servidores fake de verdade, em portas locais: SMTP (aiosmtpd) e HTTP (uvicorn).
"""

import asyncio
import hashlib
from email import message_from_bytes, policy
import hmac
import json
import socket
from datetime import timedelta

import pytest
import uvicorn
from aiosmtpd.controller import Controller
from cryptography.fernet import Fernet

from lumio_worker import notify
from lumio_worker.notify import Notifier, SmtpConfig

from .conftest import needs_db, rec

pytestmark = needs_db

KEY = Fernet.generate_key().decode()
SECRET = "segredo-do-webhook-de-teste"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------------ servidores fake

class Inbox:
    def __init__(self):
        self.messages = []

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(envelope)
        return "250 OK"


@pytest.fixture
def smtp():
    inbox = Inbox()
    port = free_port()
    ctl = Controller(inbox, hostname="127.0.0.1", port=port)
    ctl.start()
    yield inbox, SmtpConfig(host="127.0.0.1", port=port, security="none", sender="Lumio <alertas@lumio.test>")
    ctl.stop()


class WebhookServer:
    """Recebe POSTs; `responses` controla o status devolvido em cada chamada."""

    def __init__(self):
        self.requests: list[dict] = []
        self.responses: list[int] = []
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}/hooks/lumio"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body"):
                break
        self.requests.append({"headers": {k.decode(): v.decode() for k, v in scope["headers"]}, "body": body})
        code = self.responses.pop(0) if self.responses else 200
        await send({"type": "http.response.start", "status": code, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


@pytest.fixture
async def webhook():
    srv = WebhookServer()
    server = uvicorn.Server(uvicorn.Config(srv, host="127.0.0.1", port=srv.port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    yield srv
    server.should_exit = True
    await task


# ------------------------------------------------------------------ ajuda

async def add_channel(pool, tenant_id, name, type_, target, min_severity="minor", notify_clear=True):
    secret = Fernet(KEY.encode()).encrypt(SECRET.encode()).decode() if type_ == "webhook" else None
    return await pool.fetchval(
        "INSERT INTO notification_channels (tenant_id, name, type, target, secret_enc, min_severity, notify_clear) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id", tenant_id, name, type_, target, secret, min_severity, notify_clear)


async def queue(pool):
    return await pool.fetch(
        "SELECT n.*, c.name AS channel, a.kind FROM notifications n JOIN notification_channels c ON c.id = n.channel_id "
        "LEFT JOIN alarms a ON a.id = n.alarm_id ORDER BY n.created_at, c.name")


async def make_due(pool):
    await pool.execute("UPDATE notifications SET next_attempt_at = now() WHERE status = 'pending'")


def onus(pon="0/1/0", n=8):
    return [{"pon": pon, "onu": i, "serial": f"HWTC{i:08X}", "online": True} for i in range(n)]


# ------------------------------------------------------------------ fila (worker)

async def test_fila_respeita_a_severidade_de_cada_canal(processor, pool):
    await add_channel(pool, processor.tenant_id, "noc", "email", "noc@a.com.br", min_severity="major")
    await add_channel(pool, processor.tenant_id, "plantao", "webhook", "https://hooks.a.com.br/x", min_severity="critical")

    await processor.handle(rec("event", kind="olt_unreachable", source="poll"))                  # critical
    await processor.handle(rec("event", kind="olt_cpu_high", source="trap", cpu=95.0, olt="olt-2"))  # major
    await processor.handle(rec("event", kind="onu_rx_low", source="trap", pon="0/1/0", onu=1, rx_dbm=-28.0))  # warning
    rows = await queue(pool)
    assert sorted((r["kind"], r["channel"]) for r in rows) == [
        ("olt_cpu_high", "noc"), ("olt_unreachable", "noc"), ("olt_unreachable", "plantao")]

    # trap repetida não gera outro aviso (deduplicação)
    await processor.handle(rec("event", kind="olt_unreachable", source="poll"))
    assert len(await queue(pool)) == 3


async def test_rompimento_de_fibra_vira_um_aviso_so(processor, pool):
    await add_channel(pool, processor.tenant_id, "noc", "email", "noc@a.com.br", min_severity="minor")
    await processor.handle(rec("onu_status", onus=onus()))
    for i in range(8):
        await processor.handle(rec("event", kind="onu_offline", source="trap", pon="0/1/0", onu=i))
    rows = await queue(pool)
    pending = [r for r in rows if r["status"] == "pending"]
    assert [r["kind"] for r in pending] == ["pon_fiber_cut"]
    suppressed = [r for r in rows if r["status"] == "suppressed"]
    assert len(suppressed) == 8 and {r["last_error"] for r in suppressed} == {"agrupado no rompimento de fibra"}


async def test_onu_offline_espera_antes_de_avisar(processor, pool):
    await add_channel(pool, processor.tenant_id, "noc", "email", "noc@a.com.br", min_severity="minor")
    await processor.handle(rec("onu_status", onus=onus()))
    await processor.handle(rec("event", kind="onu_offline", source="trap", pon="0/1/0", onu=2))
    [row] = await queue(pool)
    wait = await pool.fetchval("SELECT next_attempt_at - now() FROM notifications WHERE id = $1", row["id"])
    assert timedelta(seconds=10) < wait <= timedelta(seconds=15)


async def test_normalizou_antes_de_avisar_nao_manda_nada(processor, pool):
    await add_channel(pool, processor.tenant_id, "noc", "email", "noc@a.com.br", min_severity="minor")
    await processor.handle(rec("onu_status", onus=onus()))
    await processor.handle(rec("event", kind="onu_offline", source="trap", pon="0/1/0", onu=2))
    await processor.handle(rec("event", kind="onu_online", source="trap", pon="0/1/0", onu=2))
    [row] = await queue(pool)
    assert (row["event"], row["status"]) == ("opened", "suppressed")


async def test_aviso_de_normalizacao_so_para_quem_recebeu_a_queda(processor, pool):
    tid = processor.tenant_id
    await add_channel(pool, tid, "noc", "email", "noc@a.com.br", min_severity="critical")
    await add_channel(pool, tid, "sem-volta", "email", "x@a.com.br", min_severity="critical", notify_clear=False)
    await processor.handle(rec("event", kind="olt_unreachable", source="poll"))
    await pool.execute("UPDATE notifications SET status = 'sent'")
    await processor.handle(rec("event", kind="olt_reachable", source="poll"))
    cleared = [r["channel"] for r in await queue(pool) if r["event"] == "cleared"]
    assert cleared == ["noc"]


# ------------------------------------------------------------------ envio (notificador)

async def test_envia_email(processor, pool, smtp):
    inbox, cfg = smtp
    await add_channel(pool, processor.tenant_id, "noc", "email", "noc@a.com.br", min_severity="critical")
    await processor.handle(rec("event", kind="olt_unreachable", source="poll", error="timeout"))
    notifier = Notifier(pool, KEY, cfg, public_url="https://painel.lumio.test")
    assert await notifier.run_once() == 1

    [msg] = inbox.messages
    assert msg.rcpt_tos == ["noc@a.com.br"]
    # assunto com acento vem codificado (RFC 2047): lê como o cliente de e-mail leria
    parsed = message_from_bytes(msg.content, policy=policy.default)
    assert parsed["Subject"] == "[Lumio] CRÍTICO: OLT inacessível — olt-1"
    text = parsed.get_body(preferencelist=("plain",)).get_content()
    assert "Severidade: crítico" in text and "https://painel.lumio.test/alarms" in text
    # versão HTML para os clientes de e-mail que mostram HTML: mesmo conteúdo, com botão para o painel
    html = parsed.get_body(preferencelist=("html",)).get_content()
    assert "CRÍTICO" in html and "OLT inacessível — olt-1" in html and 'href="https://painel.lumio.test/alarms"' in html
    assert "<script" not in html.lower()
    assert (await queue(pool))[0]["status"] == "sent"


async def test_envia_webhook_assinado(processor, pool, webhook):
    await add_channel(pool, processor.tenant_id, "integracao", "webhook", webhook.url, min_severity="major")
    await processor.handle(rec("event", kind="olt_cpu_high", source="trap", cpu=97.0))
    notifier = Notifier(pool, KEY, SmtpConfig(host=None), allow_private=True)
    await notifier.run_once()

    [req] = webhook.requests
    expected = "sha256=" + hmac.new(SECRET.encode(), req["body"], hashlib.sha256).hexdigest()
    assert req["headers"]["x-lumio-signature"] == expected                  # cliente confere a origem
    assert req["headers"]["x-lumio-event"] == "alarm.opened"
    payload = json.loads(req["body"])
    assert payload["alarm"]["kind"] == "olt_cpu_high" and payload["alarm"]["details"] == {"cpu": 97.0}
    assert payload["delivery_id"] == req["headers"]["x-lumio-delivery"]


async def test_webhook_com_erro_tenta_de_novo_e_depois_envia(processor, pool, webhook):
    await add_channel(pool, processor.tenant_id, "integracao", "webhook", webhook.url, min_severity="critical")
    await processor.handle(rec("event", kind="olt_unreachable", source="poll"))
    webhook.responses = [500]
    notifier = Notifier(pool, KEY, SmtpConfig(host=None), allow_private=True)
    await notifier.run_once()
    [row] = await queue(pool)
    assert (row["status"], row["attempts"], row["last_error"]) == ("pending", 1, "webhook respondeu 500")
    assert await notifier.run_once() == 0              # ainda esperando o backoff
    await make_due(pool)
    await notifier.run_once()
    [row] = await queue(pool)
    assert (row["status"], row["attempts"]) == ("sent", 2)
    assert len(webhook.requests) == 2


async def test_desiste_depois_do_limite_de_tentativas(processor, pool, webhook):
    await add_channel(pool, processor.tenant_id, "integracao", "webhook", webhook.url, min_severity="critical")
    await processor.handle(rec("event", kind="olt_unreachable", source="poll"))
    await pool.execute("UPDATE notifications SET attempts = $1", notify.MAX_ATTEMPTS - 1)
    webhook.responses = [503]
    await Notifier(pool, KEY, SmtpConfig(host=None), allow_private=True).run_once()
    [row] = await queue(pool)
    assert row["status"] == "failed" and "desistiu" in row["last_error"]


async def test_webhook_para_rede_interna_e_bloqueado(processor, pool, webhook):
    """Proteção contra SSRF: em produção, nada de 127.0.0.1, 10.x, 192.168.x..."""
    await add_channel(pool, processor.tenant_id, "malicioso", "webhook", webhook.url, min_severity="critical")
    await processor.handle(rec("event", kind="olt_unreachable", source="poll"))
    await Notifier(pool, KEY, SmtpConfig(host=None), allow_private=False).run_once()
    [row] = await queue(pool)
    assert row["status"] == "failed" and "endereço interno" in row["last_error"]
    assert webhook.requests == []


async def test_onu_agrupada_depois_de_entrar_na_fila_nao_e_enviada(processor, pool, smtp):
    inbox, cfg = smtp
    await add_channel(pool, processor.tenant_id, "noc", "email", "noc@a.com.br", min_severity="minor")
    await processor.handle(rec("onu_status", onus=onus(n=2)))
    await processor.handle(rec("event", kind="onu_offline", source="trap", pon="0/1/0", onu=0))
    # a ONU passou a fazer parte de um rompimento por outro caminho (ex.: polling)
    fake_parent = await pool.fetchval(
        "INSERT INTO alarms (tenant_id, olt_id, kind, severity, dedup_key, source, event_ts, first_seen_at, last_seen_at) "
        "SELECT tenant_id, olt_id, 'pon_fiber_cut', 'critical', 'x', 'poll', now(), now(), now() FROM alarms LIMIT 1 RETURNING id")
    await pool.execute("UPDATE alarms SET parent_id = $1 WHERE kind = 'onu_offline'", fake_parent)
    await make_due(pool)
    await Notifier(pool, KEY, cfg).run_once()
    assert inbox.messages == []
    assert (await queue(pool))[0]["status"] == "suppressed"


async def test_mensagem_de_teste_e_smtp_fora_do_ar(processor, pool):
    await processor.handle(rec("event", kind="olt_reachable", source="poll"))      # cria o tenant
    channel = await add_channel(pool, processor.tenant_id, "noc", "email", "noc@a.com.br")
    await pool.execute("INSERT INTO notifications (tenant_id, channel_id, event) VALUES ($1, $2, 'test')",
                       processor.tenant_id, channel)
    dead = SmtpConfig(host="127.0.0.1", port=free_port(), security="none")       # ninguém escutando
    await Notifier(pool, KEY, dead).run_once()
    [row] = await queue(pool)
    assert row["status"] == "pending" and row["attempts"] == 1 and row["last_error"]


def test_assinatura_e_backoff():
    assert notify.sign("k", b"{}") == "sha256=" + hmac.new(b"k", b"{}", hashlib.sha256).hexdigest()
    assert [notify.backoff(n).total_seconds() for n in (1, 2, 3, 4)] == [30, 60, 120, 240]


def test_duracao_legivel():
    assert [notify.human_duration(s) for s in (12.4, 75, 3600 + 5 * 60)] == ["12 s", "1 min", "1 h 05 min"]
