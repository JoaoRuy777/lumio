"""Assistente do NOC: conversa com um modelo de IA (Google Gemini) que consulta a
Lumio por "ferramentas" só de leitura.

Privacidade (LGPD): nenhum dado pessoal sai para o provedor de IA. Nome,
telefone e endereço de cliente, e nome/e-mail de pessoa, viram marcadores
([CLIENTE_1], [TELEFONE_1], [PESSOA_1]...) antes de sair; a resposta volta com
os marcadores e a API troca pelos valores reais só para quem perguntou. O mapa
marcador -> valor fica com o navegador do usuário, que o devolve a cada
pergunta para a numeração continuar a mesma na conversa.

Segurança: as ferramentas rodam na conexão do usuário (RLS): o modelo só vê os
dados do provedor de quem pergunta, e não altera nada.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from uuid import UUID

import asyncpg
import httpx

from . import reports, trend
from .reports import BRT, KIND_LABEL, SEVERITY_LABEL

log = logging.getLogger("lumio.assistant")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_ROUNDS = 6                   # rodadas de ferramenta por pergunta
DEADLINE_S = 55                  # tempo máximo por pergunta (a função da Vercel tem limite)
DAILY_LIMIT = 40                 # perguntas por usuário por dia (cota gratuita do Gemini)


class AssistantError(Exception):
    """Falha mostrável ao usuário (fora do ar, cota esgotada...)."""

    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ anonimização

@dataclass
class Vault:
    """Marcadores para dados pessoais. `mapping`: marcador -> valor real."""

    mapping: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._reverse = {v: k for k, v in self.mapping.items()}

    def token(self, kind: str, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        value = str(value).strip()
        if value in self._reverse:
            return self._reverse[value]
        n = 1 + sum(1 for k in self.mapping if k.startswith(f"[{kind}_"))
        tok = f"[{kind}_{n}]"
        self.mapping[tok] = value
        self._reverse[value] = tok
        return tok

    def mask(self, text: str) -> str:
        """Troca no texto livre (pergunta do usuário) os valores já conhecidos pelos marcadores."""
        for value in sorted(self._reverse, key=len, reverse=True):
            if len(value) >= 3:
                text = re.sub(re.escape(value), self._reverse[value], text, flags=re.IGNORECASE)
        return text

    def unmask(self, value: Any) -> Any:
        if isinstance(value, str):
            return re.sub(r"\[[A-Z]+_\d+\]", lambda m: self.mapping.get(m.group(0), m.group(0)), value)
        if isinstance(value, dict):
            return {k: self.unmask(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.unmask(v) for v in value]
        return value


# ------------------------------------------------------------------ ferramentas

def _where(olt: str | None, pon: str | None, onu: int | None) -> str:
    return " · ".join(x for x in (olt, pon and f"PON {pon}", onu is not None and f"ONU {onu}") if x)


def _minutes(since: datetime | None, until: datetime | None = None) -> int | None:
    if since is None:
        return None
    return round(((until or datetime.now(timezone.utc)) - since).total_seconds() / 60)


def _alarm(a, vault: Vault) -> dict:
    return {
        "id": str(a.id),
        "tipo": KIND_LABEL.get(a.kind, a.kind),
        "severidade": SEVERITY_LABEL[a.severity],
        "situacao": {"active": "ativo", "acknowledged": "reconhecido", "cleared": "normalizado"}[a.status],
        "local": _where(a.olt_name, a.pon, a.onu_index),
        "aberto_ha_min": _minutes(a.created_at, a.cleared_at),
        "onus_afetadas": a.children,
        "clientes_afetados": a.affected_customers,
        "cliente": vault.token("CLIENTE", a.customer_name),
        "responsavel": vault.token("PESSOA", a.assigned_to),
        "espera_ate_assumir_min": _minutes(a.created_at, a.first_assigned_at) if a.first_assigned_at else None,
        "atendimento_encerrado": a.work_closed_at is not None,
        "em_manutencao": a.maintenance_reason,
        "escalonado": a.escalated_at is not None,
        "detalhes": {k: v for k, v in a.details.items() if k in ("rx_dbm", "cpu", "onus_offline")},
    }


async def tool_resumo_rede(db, vault, args) -> dict:
    onus = await db.fetchrow("SELECT count(*) AS total, count(*) FILTER (WHERE online) AS online, "
                             "count(*) FILTER (WHERE online IS FALSE) AS offline, "
                             "count(*) FILTER (WHERE online AND rx_dbm < -27) AS sinal_baixo FROM onus")
    sev = {r["severity"]: r["count"] for r in await db.fetch(
        "SELECT severity, count(*) FROM alarms WHERE status <> 'cleared' AND parent_id IS NULL GROUP BY severity")}
    return {
        "onus": dict(onus),
        "alarmes_abertos": {SEVERITY_LABEL[k]: sev.get(k, 0) for k in SEVERITY_LABEL},
        "sem_responsavel": await db.fetchval(
            "SELECT count(*) FROM alarms WHERE status <> 'cleared' AND parent_id IS NULL AND assigned_to IS NULL"),
        "clientes_cadastrados": await db.fetchval("SELECT count(*) FROM customers"),
        "clientes_sem_servico": await db.fetchval(
            "SELECT count(*) FROM customers c JOIN onus n ON n.tenant_id = c.tenant_id AND n.serial = c.onu_serial "
            "WHERE n.online IS FALSE"),
        "onus_com_sinal_piorando": await db.fetchval(f"SELECT count(*) FROM ({trend.TREND_SQL}) t"),
        "manutencoes_em_andamento": await db.fetchval(
            "SELECT count(*) FROM maintenance_windows WHERE cancelled_at IS NULL AND starts_at <= now() AND ends_at > now()"),
    }


async def tool_listar_alarmes(db, vault, args) -> dict:
    from .routers.alarms import fetch_alarms
    sev_map = {"critico": "critical", "grave": "major", "menor": "minor", "aviso": "warning"}
    severity = [sev_map[s] for s in args.get("severidades") or [] if s in sev_map] or None
    status_ = "cleared" if args.get("encerrados") else "open"
    since = datetime.now(timezone.utc) - timedelta(hours=int(args.get("ultimas_horas") or 24)) if status_ == "cleared" else None
    page = await fetch_alarms(db, status_=status_, severity=severity, since=since,
                              limit=min(int(args.get("limite") or 15), 30))
    return {"total": page.total, "alarmes": [_alarm(a, vault) for a in page.items]}


async def tool_detalhar_chamado(db, vault, args) -> dict:
    from .routers.alarms import ALARM_SELECT, fetch_alarms, to_alarm
    try:
        alarm_id = UUID(str(args.get("alarme_id")))
    except ValueError:
        return {"erro": "id de alarme inválido; use listar_alarmes para achar o id"}
    row = await db.fetchrow(ALARM_SELECT + " WHERE a.id = $1", alarm_id)
    if row is None:
        return {"erro": "alarme não encontrado"}
    a = to_alarm(row)
    out = _alarm(a, vault)
    out["resolucao"] = {"causa": a.resolution_cause, "o_que_foi_feito": a.resolution_notes} if a.work_closed_at else None
    events = await db.fetch(
        "SELECT e.kind, e.body, e.created_at, ua.name AS actor, ut.name AS target FROM alarm_events e "
        "LEFT JOIN users ua ON ua.id = e.actor_id LEFT JOIN users ut ON ut.id = e.target_id "
        "WHERE e.alarm_id = $1 ORDER BY e.created_at", alarm_id)
    out["linha_do_tempo"] = [
        {"quando": e["created_at"].astimezone(BRT).strftime("%d/%m %H:%M"),
         "evento": {"assigned": "assumiu", "note": "anotação", "closed": "encerrou", "reopened": "reabriu"}[e["kind"]],
         "quem": vault.token("PESSOA", e["actor"]), "para": vault.token("PESSOA", e["target"]),
         "texto": vault.mask(e["body"]) if e["body"] else None}
        for e in events]
    if a.children:
        kids = await fetch_alarms(db, status_="all", parent_id=alarm_id, limit=40)
        out["onus"] = [{"onu": k.onu_index, "serial": k.onu_serial, "cliente": vault.token("CLIENTE", k.customer_name),
                        "voltou": k.status == "cleared"} for k in kids.items]
    return out


async def tool_buscar_clientes(db, vault, args) -> dict:
    termo = str(vault.unmask(args.get("termo") or "")).strip().lower()
    if len(termo) < 2:
        return {"erro": "informe ao menos 2 letras (nome, código, serial, rua ou bairro)"}
    rows = await db.fetch(
        "SELECT c.name, c.code, c.phone, c.address, c.district, c.plan, c.onu_serial, n.online, n.rx_dbm, "
        "       n.onu_index, o.name AS olt, p.name AS pon "
        "FROM customers c LEFT JOIN onus n ON n.tenant_id = c.tenant_id AND n.serial = c.onu_serial "
        "LEFT JOIN olts o ON o.id = n.olt_id LEFT JOIN pon_ports p ON p.id = n.pon_id "
        "WHERE lower(c.name) LIKE $1 OR lower(coalesce(c.code, '')) LIKE $1 OR lower(c.onu_serial) LIKE $1 "
        "   OR lower(coalesce(c.address, '')) LIKE $1 OR lower(coalesce(c.district, '')) LIKE $1 "
        "ORDER BY c.name LIMIT 15", f"%{termo}%")
    return {"clientes": [{
        "cliente": vault.token("CLIENTE", r["name"]), "codigo": r["code"], "telefone": vault.token("TELEFONE", r["phone"]),
        "endereco": vault.token("ENDERECO", r["address"]), "bairro": r["district"], "plano": r["plan"],
        "serial_onu": r["onu_serial"], "onde": _where(r["olt"], r["pon"], r["onu_index"]) or "ONU não encontrada",
        "situacao": "sem dados" if r["online"] is None else "online" if r["online"] else "offline",
        "sinal_dbm": r["rx_dbm"]} for r in rows]}


async def tool_sinal_onu(db, vault, args) -> dict:
    serial = str(vault.unmask(args.get("serial") or "")).strip().upper()
    onu = await db.fetchrow(
        "SELECT n.id, n.serial, n.online, n.rx_dbm, n.onu_index, o.name AS olt, p.name AS pon, cu.name AS cliente "
        "FROM onus n JOIN olts o ON o.id = n.olt_id JOIN pon_ports p ON p.id = n.pon_id "
        "LEFT JOIN customers cu ON cu.tenant_id = n.tenant_id AND cu.onu_serial = n.serial WHERE upper(n.serial) = $1",
        serial)
    if onu is None:
        return {"erro": "ONU não encontrada com esse serial (use buscar_clientes para achar o serial)"}
    hours = min(int(args.get("horas") or 24), 168)
    stats = await db.fetchrow(
        "SELECT count(*) AS leituras, min(rx_dbm) AS minimo, max(rx_dbm) AS maximo, "
        "       regr_slope(rx_dbm, extract(epoch FROM ts)) * 86400 AS tendencia_db_dia "
        "FROM optical_readings WHERE onu_id = $1 AND ts > now() - make_interval(hours => $2) AND rx_dbm IS NOT NULL",
        onu["id"], hours)
    risk = next((r for r in await trend.at_risk(db) if r["onu_id"] == onu["id"]), None)
    return {
        "onu": _where(onu["olt"], onu["pon"], onu["onu_index"]), "serial": onu["serial"],
        "cliente": vault.token("CLIENTE", onu["cliente"]), "online": onu["online"], "sinal_atual_dbm": onu["rx_dbm"],
        "limite_alarme_dbm": -27, f"ultimas_{hours}h": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in stats.items()},
        "previsao": {"dias_ate_o_limite": risk["days_to_limit"]} if risk else None,
    }


async def tool_status_olts(db, vault, args) -> dict:
    from .routers.olts import OLT_SELECT, collection_status
    rows = await db.fetch(OLT_SELECT + " ORDER BY o.name")
    label = {"ok": "coletando", "pending": "aguardando 1ª coleta", "late": "coleta atrasada",
             "error": "sem resposta", "disabled": "desativada"}
    return {"olts": [{"nome": r["name"], "situacao": label[collection_status(r)], "onus_online": r["onus_online"],
                      "onus_total": r["onus_total"], "alarmes_abertos": r["active_alarms"],
                      "ultima_coleta": r["last_poll_at"] and r["last_poll_at"].astimezone(BRT).strftime("%d/%m %H:%M")}
                     for r in rows]}


async def tool_relatorio_atendimento(db, vault, args) -> dict:
    now = datetime.now(timezone.utc)
    days = {"hoje": 0, "7dias": 7, "30dias": 30}.get(str(args.get("periodo") or "hoje"), 0)
    start = now.astimezone(BRT).replace(hour=0, minute=0, second=0, microsecond=0) if days == 0 else now - timedelta(days=days)
    rep = await reports.attendance_report(db, reports.Period(start, now))
    return {
        "periodo": reports.Period(start, now).label(),
        "resumo": rep["summary"],
        "operadores": [{**{k: v for k, v in o.items() if k not in ("user_id", "name")},
                        "operador": vault.token("PESSOA", o.get("name"))} for o in rep["operators"]],
        "causas": [{"causa": c["label"], "quantidade": c["count"]} for c in rep["causes"]],
    }


async def tool_manutencoes(db, vault, args) -> dict:
    rows = await db.fetch(
        "SELECT m.reason, m.starts_at, m.ends_at, o.name AS olt, p.name AS pon, "
        "       CASE WHEN m.starts_at <= now() THEN 'em andamento' ELSE 'agendada' END AS situacao "
        "FROM maintenance_windows m JOIN olts o ON o.id = m.olt_id LEFT JOIN pon_ports p ON p.id = m.pon_id "
        "WHERE m.cancelled_at IS NULL AND m.ends_at > now() ORDER BY m.starts_at")
    f = "%d/%m %H:%M"
    return {"manutencoes": [{"onde": _where(r["olt"], r["pon"], None) or r["olt"], "motivo": r["reason"],
                             "situacao": r["situacao"], "inicio": r["starts_at"].astimezone(BRT).strftime(f),
                             "fim": r["ends_at"].astimezone(BRT).strftime(f)} for r in rows]}


Tool = Callable[[asyncpg.Connection, Vault, dict], Awaitable[dict]]
TOOLS: dict[str, tuple[Tool, str, dict]] = {
    "resumo_rede": (tool_resumo_rede, "Números gerais da rede agora: ONUs online/offline, alarmes abertos por "
                    "severidade, chamados sem responsável, clientes sem serviço, sinal piorando, manutenções.", {}),
    "listar_alarmes": (tool_listar_alarmes, "Lista alarmes (os mais graves primeiro), com local, tempo aberto, "
                       "responsável e clientes afetados. Use encerrados=true para o histórico recente.", {
        "severidades": {"type": "array", "items": {"type": "string", "enum": ["critico", "grave", "menor", "aviso"]}},
        "encerrados": {"type": "boolean"}, "ultimas_horas": {"type": "integer"}, "limite": {"type": "integer"}}),
    "detalhar_chamado": (tool_detalhar_chamado, "Tudo sobre um alarme/chamado: situação, tempos, responsável, "
                         "linha do tempo com anotações, ONUs e clientes afetados.", {
        "alarme_id": {"type": "string", "description": "id do alarme (vem de listar_alarmes)"}}),
    "buscar_clientes": (tool_buscar_clientes, "Procura clientes por nome, código, serial da ONU, rua ou bairro; "
                        "traz a situação da ONU e o sinal.", {"termo": {"type": "string"}}),
    "sinal_onu": (tool_sinal_onu, "Histórico do sinal óptico (dBm) de uma ONU pelo serial: mínimo, máximo, "
                  "tendência por dia e previsão de quando passa do limite.", {
        "serial": {"type": "string"}, "horas": {"type": "integer", "description": "janela, padrão 24"}}),
    "status_olts": (tool_status_olts, "Situação de cada OLT: coletando ou sem resposta, ONUs online e alarmes.", {}),
    "relatorio_atendimento": (tool_relatorio_atendimento, "Indicadores de atendimento: chamados, TME, TMA, SLA, "
                              "desempenho por operador e causas.", {
        "periodo": {"type": "string", "enum": ["hoje", "7dias", "30dias"]}}),
    "manutencoes": (tool_manutencoes, "Manutenções programadas em andamento e agendadas.", {}),
}


def tool_declarations() -> list[dict]:
    decls = []
    for name, (_, desc, props) in TOOLS.items():
        d: dict[str, Any] = {"name": name, "description": desc}
        if props:
            d["parameters"] = {"type": "object", "properties": props}
        decls.append(d)
    return [{"functionDeclarations": decls}]


# ------------------------------------------------------------------ conversa

def system_prompt(tenant: str, alarm_id: UUID | None) -> str:
    now = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")
    text = (
        f"Você é o assistente do NOC na Lumio, sistema de monitoramento de redes GPON do provedor {tenant}. "
        f"Agora são {now} (horário de Brasília).\n"
        "- Responda em português do Brasil, direto e curto, como um colega experiente de NOC. Use listas e **negrito** "
        "quando ajudar; nada de tabelas largas.\n"
        "- Use as ferramentas para buscar os dados reais antes de responder; nunca invente números, nomes ou estados. "
        "Se a informação não existir nas ferramentas, diga que não tem.\n"
        "- Marcadores como [CLIENTE_1], [PESSOA_2], [TELEFONE_1] e [ENDERECO_1] representam dados pessoais protegidos. "
        "Escreva-os exatamente como recebeu (o sistema troca pelo valor real na tela); nunca tente adivinhar o valor.\n"
        "- Você só consulta; não executa ações. Para assumir, anotar ou encerrar um chamado, diga ao operador onde "
        "clicar (Central de alarmes, botão Assumir / Anotar / Encerrar).\n"
        "- Ao priorizar, considere severidade, clientes afetados, tempo sem responsável e SLA de 15 min para assumir.\n"
        "- Ao escrever mensagem para clientes, seja cordial, não prometa prazo que os dados não sustentam e use os "
        "marcadores no lugar dos nomes."
    )
    if alarm_id:
        text += f"\n- O operador está com o chamado {alarm_id} aberto na tela; \"este chamado\" se refere a ele."
    return text


@dataclass
class Reply:
    text: str
    tools: list[str]
    model: str


Post = Callable[[str, dict], Awaitable[httpx.Response]]


async def converse(db: asyncpg.Connection, vault: Vault, *, history: list[dict], tenant: str, alarm_id: UUID | None,
                   models: list[str], post: Post) -> Reply:
    """history: [{"role": "user"|"model", "text": ...}] já anonimizado. Roda o laço de ferramentas."""
    contents = [{"role": m["role"], "parts": [{"text": m["text"]}]} for m in history]
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt(tenant, alarm_id)}]},
        "tools": tool_declarations(),
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048},
    }
    used: list[str] = []
    model_used = models[0]
    started = time.monotonic()
    for _ in range(MAX_ROUNDS):
        if time.monotonic() - started > DEADLINE_S:
            raise AssistantError("o provedor de IA está lento agora; tente de novo em instantes", 504)
        data, model_used = await _generate(post, models, {**body, "contents": contents})
        candidate = (data.get("candidates") or [{}])[0]
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        calls = [p["functionCall"] for p in parts if "functionCall" in p]
        if not calls:
            text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
            if not text:
                reason = candidate.get("finishReason")
                text = ("Não consegui responder a isso." if reason in ("SAFETY", "PROHIBITED_CONTENT")
                        else "Não recebi resposta do modelo; tente perguntar de outro jeito.")
            return Reply(text, used, model_used)
        contents.append(content)                 # devolve como veio (inclui assinaturas de raciocínio)
        responses = []
        for call in calls:
            name, args = call.get("name", ""), call.get("args") or {}
            used.append(name)
            if name not in TOOLS:
                result = {"erro": f"ferramenta {name} não existe"}
            else:
                try:
                    async with db.transaction():          # savepoint: erro numa ferramenta não derruba a conversa
                        result = await TOOLS[name][0](db, vault, args)
                except Exception:                          # noqa: BLE001 - o modelo recebe o erro e segue
                    log.exception("ferramenta %s falhou", name)
                    result = {"erro": "falha ao consultar; tente de outro jeito"}
            responses.append({"functionResponse": {"name": name, "response": json.loads(json.dumps(result, default=str))}})
        contents.append({"role": "user", "parts": responses})
    return Reply("Precisei de consultas demais para essa pergunta; tente algo mais específico.", used, model_used)


async def _generate(post: Post, models: list[str], body: dict) -> tuple[dict, str]:
    """Tenta cada modelo da lista: sobrecarregado (503) ou com a cota gratuita esgotada (429; cada
    modelo tem a sua), vai para o próximo."""
    last = None
    quota = False
    for model in models:
        t0 = time.monotonic()
        try:
            resp = await post(GEMINI_URL.format(model=model), body)
        except httpx.HTTPError as e:
            last = e
            log.warning("Gemini %s: %s em %.1f s", model, type(e).__name__, time.monotonic() - t0)
            continue
        log.info("Gemini %s: %s em %.1f s", model, resp.status_code, time.monotonic() - t0)
        if resp.status_code == 200:
            return resp.json(), model
        if resp.status_code == 429:
            quota, last = True, 429
            continue
        if resp.status_code in (500, 503, 504, 404):
            last = resp.status_code
            continue
        log.warning("Gemini %s: %s %s", model, resp.status_code, resp.text[:300])
        raise AssistantError("o assistente não conseguiu responder (erro do provedor de IA)", 502)
    log.warning("Gemini indisponível em todos os modelos: %s", last)
    if quota:
        raise AssistantError("o limite gratuito do assistente foi atingido agora; tente de novo em 1 minuto", 429)
    raise AssistantError("o provedor de IA está sobrecarregado agora; tente de novo em instantes", 503)
