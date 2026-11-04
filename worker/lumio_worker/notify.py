"""Notificador: envia por e-mail e webhook as entregas da fila `notifications`.

    python -m lumio_worker notify

- Lê as entregas vencidas com FOR UPDATE SKIP LOCKED (dá para rodar mais de um).
- Falhou? Tenta de novo com espera crescente (30 s, 1 min, 2 min, 4 min...);
  depois de MAX_ATTEMPTS, marca como "failed" e guarda o erro.
- Webhook vai assinado: header X-Lumio-Signature = "sha256=" + HMAC-SHA256 do
  corpo com o segredo do canal (o cliente confere que veio da Lumio).
- Webhook para endereço interno (127.0.0.1, 10.x, 192.168.x, 169.254.x...) é
  recusado, a não ser com LUMIO_WEBHOOK_ALLOW_PRIVATE=true (desenvolvimento):
  sem isso, um cliente poderia usar a Lumio para acessar a rede interna dela (SSRF).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
from dataclasses import dataclass
from datetime import timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlsplit
from uuid import UUID

import aiosmtplib
import asyncpg
import httpx
from cryptography.fernet import Fernet

log = logging.getLogger("lumio_worker.notify")

MAX_ATTEMPTS = 6
BASE_BACKOFF_S = 30.0
BATCH = 20

KIND_LABEL = {
    "pon_fiber_cut": "Rompimento de fibra",
    "onu_offline": "ONU offline",
    "onu_rx_low": "Sinal baixo",
    "olt_unreachable": "OLT inacessível",
    "olt_cpu_high": "CPU alta",
}
SEVERITY_LABEL = {"critical": "CRÍTICO", "major": "GRAVE", "minor": "MENOR", "warning": "AVISO"}


class DeliveryError(Exception):
    """Falha que vale tentar de novo (rede, SMTP fora, webhook respondeu erro)."""


class PermanentError(Exception):
    """Não adianta repetir (destino proibido, URL inválida)."""


@dataclass
class SmtpConfig:
    host: str | None
    port: int = 587
    username: str | None = None
    password: str | None = None
    sender: str = "Lumio <alertas@lumio.local>"
    security: str = "starttls"          # starttls | tls | none

    @property
    def configured(self) -> bool:
        return bool(self.host)


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=BASE_BACKOFF_S * 2 ** max(0, attempts - 1))


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def check_webhook_url(url: str, allow_private: bool) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise PermanentError(f"URL inválida: {url}")
    if allow_private:
        return
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise DeliveryError(f"não resolvi {parts.hostname}: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise PermanentError(f"destino {ip} é endereço interno; webhook só para endereços públicos")


def human_duration(seconds: float) -> str:
    """"45 s", "12 min", "3 h 05 min"."""
    s = max(0, round(seconds))
    if s < 60:
        return f"{s} s"
    m = s // 60
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def describe(n: asyncpg.Record) -> tuple[str, str, dict]:
    """Assunto, texto e payload JSON de uma entrega."""
    if n["event"] == "test":
        text = (f"Mensagem de teste do canal \"{n['channel_name']}\" da Lumio ({n['tenant_name']}).\n"
                "Se chegou, os alertas de alarme vão chegar por aqui também.")
        return "[Lumio] Teste de notificação", text, {"event": "test", "channel": n["channel_name"], "message": text}

    kind = KIND_LABEL.get(n["kind"], n["kind"])
    where = " · ".join(x for x in (n["olt_name"], n["pon"] and f"PON {n['pon']}",
                                   n["onu_index"] is not None and f"ONU {n['onu_index']}") if x)
    details = json.loads(n["details"]) if isinstance(n["details"], str) else (n["details"] or {})
    started = n["event_ts"].astimezone(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M:%S")
    lines = [f"{kind} em {where}", f"Severidade: {SEVERITY_LABEL[n['severity']].lower()}", f"Início: {started} (horário de Brasília)"]
    if n["children"]:
        lines.append(f"ONUs afetadas: {n['children']}")
    if n["onu_serial"]:
        lines.append(f"Serial da ONU: {n['onu_serial']}")
    if "rx_dbm" in details:
        lines.append(f"Potência recebida: {details['rx_dbm']} dBm")
    if "cpu" in details:
        lines.append(f"CPU: {details['cpu']}%")
    if n["event"] == "cleared":
        subject = f"[Lumio] NORMALIZADO: {kind} — {where}"
        lines.insert(0, "Normalizado.")
        if n["cleared_at"]:
            lines.append(f"Duração: {human_duration((n['cleared_at'] - n['event_ts']).total_seconds())}")
    else:
        subject = f"[Lumio] {SEVERITY_LABEL[n['severity']]}: {kind} — {where}"
    payload = {
        "event": f"alarm.{n['event']}",
        "alarm": {
            "id": str(n["alarm_id"]), "kind": n["kind"], "kind_label": kind, "severity": n["severity"],
            "status": n["status_alarm"], "olt": n["olt_name"], "pon": n["pon"], "onu": n["onu_index"],
            "onu_serial": n["onu_serial"], "affected_onus": n["children"], "details": details,
            "started_at": n["event_ts"].isoformat(), "cleared_at": n["cleared_at"] and n["cleared_at"].isoformat(),
        },
        "provider": n["tenant_name"],
    }
    return subject, "\n".join(lines), payload


DUE_SQL = """
    UPDATE notifications SET status = 'sending', attempts = attempts + 1
    WHERE id IN (SELECT id FROM notifications WHERE status = 'pending' AND next_attempt_at <= now()
                 ORDER BY next_attempt_at LIMIT $1 FOR UPDATE SKIP LOCKED)
    RETURNING id
"""

DETAIL_SQL = """
    SELECT n.id, n.event, n.attempts, n.alarm_id, c.name AS channel_name, c.type, c.target, c.secret_enc,
           t.name AS tenant_name, a.kind, a.severity, a.status AS status_alarm, a.parent_id, a.details,
           a.event_ts, a.cleared_at, o.name AS olt_name, p.name AS pon, u.onu_index, u.serial AS onu_serial,
           (SELECT count(*) FROM alarms k WHERE k.parent_id = a.id) AS children
    FROM notifications n
    JOIN notification_channels c ON c.id = n.channel_id
    JOIN tenants t ON t.id = n.tenant_id
    LEFT JOIN alarms a ON a.id = n.alarm_id
    LEFT JOIN olts o ON o.id = a.olt_id
    LEFT JOIN pon_ports p ON p.id = a.pon_id
    LEFT JOIN onus u ON u.id = a.onu_id
    WHERE n.id = $1
"""


class Notifier:
    def __init__(self, pool: asyncpg.Pool, secret_key: str, smtp: SmtpConfig, *, public_url: str = "",
                 allow_private: bool = False, http: httpx.AsyncClient | None = None, poll_s: float = 2.0):
        self.pool = pool
        self.fernet = Fernet(secret_key.encode())
        self.smtp = smtp
        self.public_url = public_url.rstrip("/")
        self.allow_private = allow_private
        self.http = http or httpx.AsyncClient(timeout=10, follow_redirects=False)
        self.poll_s = poll_s
        self.sent = 0
        self.failed = 0

    async def recover(self) -> None:
        """Entregas que ficaram 'sending' (o processo caiu no meio) voltam para a fila."""
        n = await self.pool.execute("UPDATE notifications SET status = 'pending' WHERE status = 'sending'")
        if n != "UPDATE 0":
            log.info("recuperadas: %s", n)

    async def run_once(self) -> int:
        """Envia o que estiver vencido. Devolve quantas entregas tentou."""
        ids = [r["id"] for r in await self.pool.fetch(DUE_SQL, BATCH)]
        await asyncio.gather(*(self._deliver(i) for i in ids))
        return len(ids)

    async def run(self) -> None:
        await self.recover()
        while True:
            try:
                if await self.run_once() == 0:
                    await asyncio.sleep(self.poll_s)
            except (OSError, asyncpg.PostgresConnectionError, asyncpg.InterfaceError) as e:
                log.warning("banco indisponível (%s); tentando de novo", e)
                await asyncio.sleep(self.poll_s)

    async def _deliver(self, notification_id: UUID) -> None:
        n = await self.pool.fetchrow(DETAIL_SQL, notification_id)
        # ONU que virou parte de um rompimento depois de entrar na fila: o aviso é o do rompimento
        if n["event"] == "opened" and n["parent_id"] is not None:
            await self._finish(n["id"], "suppressed", "agrupado no rompimento de fibra")
            return
        subject, text, payload = describe(n)
        if self.public_url:
            text += f"\n\nPainel: {self.public_url}/alarms"
            payload["url"] = f"{self.public_url}/alarms"
        payload["delivery_id"] = str(n["id"])
        try:
            if n["type"] == "email":
                await self._email(n["target"], subject, text)
            else:
                secret = self.fernet.decrypt(n["secret_enc"].encode()).decode()
                await self._webhook(n["target"], secret, payload, str(n["id"]))
        except PermanentError as e:
            await self._finish(n["id"], "failed", str(e))
        except Exception as e:  # noqa: BLE001 (qualquer falha de envio entra no retry)
            if n["attempts"] >= MAX_ATTEMPTS:
                await self._finish(n["id"], "failed", f"{e} (desistiu após {n['attempts']} tentativas)")
            else:
                await self.pool.execute(
                    "UPDATE notifications SET status = 'pending', last_error = $2, next_attempt_at = now() + $3::interval "
                    "WHERE id = $1", n["id"], str(e)[:500], backoff(n["attempts"]))
                log.warning("entrega %s falhou (tentativa %d): %s", n["id"], n["attempts"], e)
        else:
            await self.pool.execute(
                "UPDATE notifications SET status = 'sent', sent_at = now(), last_error = NULL WHERE id = $1", n["id"])
            self.sent += 1
            log.info("enviado %s por %s: %s", n["event"], n["type"], subject)

    async def _finish(self, notification_id: UUID, status: str, error: str) -> None:
        if status == "failed":
            self.failed += 1
            log.warning("entrega %s: %s", notification_id, error)
        await self.pool.execute("UPDATE notifications SET status = $2, last_error = $3 WHERE id = $1",
                                notification_id, status, error[:500])

    async def _email(self, to: str, subject: str, text: str) -> None:
        if not self.smtp.configured:
            raise DeliveryError("SMTP não configurado (SMTP_HOST)")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.smtp.sender, to, subject
        msg.set_content(text)
        try:
            await aiosmtplib.send(
                msg, hostname=self.smtp.host, port=self.smtp.port, username=self.smtp.username,
                password=self.smtp.password, start_tls=self.smtp.security == "starttls",
                use_tls=self.smtp.security == "tls", timeout=15)
        except aiosmtplib.SMTPException as e:
            raise DeliveryError(f"SMTP: {e}") from e

    async def _webhook(self, url: str, secret: str, payload: dict, delivery_id: str) -> None:
        await check_webhook_url(url, self.allow_private)
        body = json.dumps(payload, ensure_ascii=False).encode()
        resp = await self.http.post(url, content=body, headers={
            "Content-Type": "application/json",
            "User-Agent": "Lumio-Webhook/1.0",
            "X-Lumio-Event": payload["event"],
            "X-Lumio-Delivery": delivery_id,
            "X-Lumio-Signature": sign(secret, body),
        })
        if resp.status_code >= 300:
            raise DeliveryError(f"webhook respondeu {resp.status_code}")
