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
from html import escape
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
    if n.get("affected_customers"):
        lines.append(f"Clientes afetados: {n['affected_customers']}")
    if n.get("customer_name"):
        phone = f" ({n['customer_phone']})" if n.get("customer_phone") else ""
        lines.append(f"Cliente: {n['customer_name']}{phone}")
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


SEVERITY_COLOR = {"critical": "#dc2626", "major": "#ea580c", "minor": "#ca8a04", "warning": "#2563eb"}
CLEARED_COLOR, TEST_COLOR = "#16a34a", "#0f766e"


def html_email(n: asyncpg.Record, subject: str, text: str, url: str) -> str:
    """Versão HTML do e-mail (o texto puro vai junto, para quem não lê HTML)."""
    if n["event"] == "test":
        color, badge = TEST_COLOR, "TESTE"
    elif n["event"] == "cleared":
        color, badge = CLEARED_COLOR, "NORMALIZADO"
    else:
        color, badge = SEVERITY_COLOR.get(n["severity"], TEST_COLOR), SEVERITY_LABEL.get(n["severity"], "ALERTA")
    title = subject.removeprefix("[Lumio] ")
    if n["event"] != "test":                  # "CRÍTICO: Rompimento…": a severidade já está no selo
        title = title.partition(": ")[2] or title
    # no texto puro, as primeiras linhas repetem o título ("Normalizado." / "<alarme> em <onde>")
    skip = {"Normalizado."} | ({text.split("\n")[1 if n["event"] == "cleared" else 0]} if n["event"] != "test" else set())
    title = escape(title)
    rows = []
    for line in text.split("\n"):
        label, sep, value = line.partition(": ")
        if not line.strip() or line.startswith("Painel: ") or line in skip:
            continue
        if sep and len(label) <= 24:          # "Severidade: crítico" vira duas colunas
            rows.append(f'<tr><td style="padding:6px 0;color:#64748b;width:40%">{escape(label)}</td>'
                        f'<td style="padding:6px 0;color:#0f172a;font-weight:600">{escape(value)}</td></tr>')
        else:
            rows.append(f'<tr><td colspan="2" style="padding:6px 0;color:#0f172a">{escape(line)}</td></tr>')
    rows = "".join(rows)
    button = (f'<p style="margin:24px 0 0"><a href="{escape(url)}" style="background:#0f766e;color:#ffffff;'
              f'text-decoration:none;padding:10px 18px;border-radius:6px;font-weight:600;display:inline-block">'
              f'Abrir no painel</a></p>') if url else ""
    return f"""<!doctype html>
<html lang="pt-BR"><body style="margin:0;padding:24px;background:#f1f5f9;font-family:Segoe UI,Helvetica,Arial,sans-serif">
<table role="presentation" width="100%" style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:10px;overflow:hidden;border:1px solid #e2e8f0">
<tr><td style="background:{color};height:6px"></td></tr>
<tr><td style="padding:24px 28px">
<p style="margin:0 0 4px;font-size:18px;font-weight:700;color:#0f766e">Lumio</p>
<p style="margin:0 0 20px;font-size:12px;color:#64748b">Monitoramento de redes GPON · {escape(n["tenant_name"])}</p>
<span style="display:inline-block;background:{color};color:#ffffff;font-size:11px;font-weight:700;letter-spacing:.04em;padding:3px 8px;border-radius:4px">{badge}</span>
<h1 style="margin:10px 0 16px;font-size:18px;line-height:1.35;color:#0f172a">{title}</h1>
<table role="presentation" width="100%" style="font-size:14px;border-collapse:collapse">{rows}</table>
{button}
</td></tr>
<tr><td style="padding:14px 28px;background:#f8fafc;font-size:12px;color:#94a3b8">
Você recebe este aviso pelo canal "{escape(n["channel_name"])}". Para mudar o que recebe, acesse Notificações no painel.
</td></tr></table></body></html>"""


def html_reset(name: str, tenant: str, url: str) -> str:
    """E-mail de redefinição de senha, no mesmo visual dos alertas."""
    return f"""<!doctype html>
<html lang="pt-BR"><body style="margin:0;padding:24px;background:#f1f5f9;font-family:Segoe UI,Helvetica,Arial,sans-serif">
<table role="presentation" width="100%" style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:10px;overflow:hidden;border:1px solid #e2e8f0">
<tr><td style="background:{TEST_COLOR};height:6px"></td></tr>
<tr><td style="padding:24px 28px;font-size:14px;color:#0f172a;line-height:1.55">
<p style="margin:0 0 4px;font-size:18px;font-weight:700;color:#0f766e">Lumio</p>
<p style="margin:0 0 20px;font-size:12px;color:#64748b">Monitoramento de redes GPON · {escape(tenant)}</p>
<h1 style="margin:0 0 12px;font-size:18px">Redefinição de senha</h1>
<p style="margin:0 0 8px">Olá, {escape(name)}. Recebemos um pedido para redefinir a sua senha.</p>
<p style="margin:0">O link vale por <strong>1 hora</strong> e só funciona uma vez.</p>
<p style="margin:24px 0"><a href="{escape(url)}" style="background:#0f766e;color:#ffffff;text-decoration:none;padding:10px 18px;border-radius:6px;font-weight:600;display:inline-block">Criar senha nova</a></p>
<p style="margin:0;font-size:12px;color:#64748b">Se o botão não abrir, copie este endereço:<br><span style="word-break:break-all">{escape(url)}</span></p>
</td></tr>
<tr><td style="padding:14px 28px;background:#f8fafc;font-size:12px;color:#94a3b8">
Se não foi você, ignore este e-mail: a sua senha continua a mesma.
</td></tr></table></body></html>"""


# Pedidos de redefinição ainda não enviados. "attempts" sobe ao pegar o pedido,
# então dois notificadores não mandam o mesmo e-mail.
RESET_DUE_SQL = """
    UPDATE password_resets r SET attempts = r.attempts + 1
    FROM users u JOIN tenants t ON t.id = u.tenant_id
    WHERE u.id = r.user_id AND r.id IN (
        SELECT id FROM password_resets
        WHERE sent_at IS NULL AND token_enc IS NOT NULL AND used_at IS NULL AND expires_at > now()
          AND (attempts = 0 OR last_error IS NOT NULL)
        ORDER BY created_at LIMIT $1 FOR UPDATE SKIP LOCKED)
    RETURNING r.id, r.token_enc, r.attempts, u.email, u.name, t.name AS tenant_name
"""


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
           (SELECT count(*) FROM alarms k WHERE k.parent_id = a.id) AS children,
           cu.name AS customer_name, cu.phone AS customer_phone,
           (SELECT count(*) FROM alarms k JOIN onus kn ON kn.id = k.onu_id
              JOIN customers kc ON kc.tenant_id = kn.tenant_id AND kc.onu_serial = kn.serial
             WHERE k.parent_id = a.id) AS affected_customers
    FROM notifications n
    JOIN notification_channels c ON c.id = n.channel_id
    JOIN tenants t ON t.id = n.tenant_id
    LEFT JOIN alarms a ON a.id = n.alarm_id
    LEFT JOIN olts o ON o.id = a.olt_id
    LEFT JOIN pon_ports p ON p.id = a.pon_id
    LEFT JOIN onus u ON u.id = a.onu_id
    LEFT JOIN customers cu ON cu.tenant_id = u.tenant_id AND cu.onu_serial = u.serial
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
        resets = await self.pool.fetch(RESET_DUE_SQL, BATCH)
        await asyncio.gather(*(self._send_reset(r) for r in resets))
        return len(ids) + len(resets)

    async def _send_reset(self, r: asyncpg.Record) -> None:
        """E-mail de "esqueci minha senha". Enviado, a cópia cifrada do token é apagada."""
        try:
            if not self.public_url:
                raise PermanentError("LUMIO_PUBLIC_URL não definida: não há endereço para o link")
            token = self.fernet.decrypt(r["token_enc"].encode()).decode()
            url = f"{self.public_url}/redefinir-senha?token={token}"
            subject = "[Lumio] Redefinição de senha"
            text = (f"Olá, {r['name']}.\n"
                    f"Recebemos um pedido para redefinir a sua senha na Lumio ({r['tenant_name']}).\n"
                    f"Para criar uma senha nova, abra o link abaixo. Ele vale por 1 hora e só funciona uma vez.\n\n"
                    f"{url}\n\n"
                    "Se não foi você, ignore este e-mail: a sua senha continua a mesma.")
            await self._email(r["email"], subject, text, html_reset(r["name"], r["tenant_name"], url))
        except Exception as e:  # noqa: BLE001
            permanent = isinstance(e, PermanentError) or r["attempts"] >= 5
            await self.pool.execute(
                "UPDATE password_resets SET last_error = $2, token_enc = CASE WHEN $3 THEN NULL ELSE token_enc END "
                "WHERE id = $1", r["id"], str(e)[:500], permanent)
            log.warning("e-mail de redefinição de senha falhou (tentativa %d): %s", r["attempts"], e)
        else:
            await self.pool.execute(
                "UPDATE password_resets SET sent_at = now(), token_enc = NULL, last_error = NULL WHERE id = $1", r["id"])
            self.sent += 1
            log.info("enviado link de redefinição de senha")

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
                await self._email(n["target"], subject, text, html_email(n, subject, text, payload.get("url", "")))
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

    async def _email(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        if not self.smtp.configured:
            raise DeliveryError("SMTP não configurado (SMTP_HOST)")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.smtp.sender, to, subject
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")
        client = aiosmtplib.SMTP(hostname=self.smtp.host, port=self.smtp.port, timeout=15,
                                 start_tls=self.smtp.security == "starttls", use_tls=self.smtp.security == "tls")
        try:
            await client.connect()
            if self.smtp.username:
                # Um método só (PLAIN, senão LOGIN). O login() padrão tenta o próximo método
                # depois de uma recusa, e o servidor fecha ou trava: a causa real (usuário/senha)
                # sumia atrás de "conexão fechada" ou "timeout".
                if not client.server_auth_methods:
                    await client.ehlo()           # depois do STARTTLS a lista de métodos só vem num novo EHLO
                auth = client.auth_plain if "plain" in client.server_auth_methods else client.auth_login
                try:
                    await auth(self.smtp.username, self.smtp.password or "")
                except aiosmtplib.SMTPAuthenticationError as e:
                    raise DeliveryError(
                        f"o servidor SMTP recusou o usuário/senha de {self.smtp.username} "
                        f"(no Gmail, use uma senha de app): {e.message}") from e
            await client.send_message(msg)
        except aiosmtplib.SMTPException as e:
            raise DeliveryError(f"SMTP: {e}") from e
        finally:
            if client.is_connected:
                client.close()

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
