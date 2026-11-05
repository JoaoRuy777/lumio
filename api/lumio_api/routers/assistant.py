"""Assistente do NOC (IA): conversa com dados reais do provedor, sem dados pessoais saindo."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from .. import assistant
from ..audit import audit
from ..deps import TenantDb, User, settings
from ..reports import BRT

router = APIRouter(prefix="/assistant", tags=["assistente"])


class ChatMessage(BaseModel):
    role: Literal["user", "model"]
    text: str = Field(max_length=8000)


class ChatIn(BaseModel):
    messages: Annotated[list[ChatMessage], Field(min_length=1, max_length=30)]
    mapping: dict[str, str] = Field(default_factory=dict, description="marcador -> valor (devolvido pelo próprio painel)")
    alarm_id: UUID | None = None


class ChatOut(BaseModel):
    reply: str                     # com os valores reais (só para quem perguntou)
    mapping: dict[str, str]        # guarde e devolva na próxima pergunta
    tools: list[str]
    model: str
    remaining_today: int


class StatusOut(BaseModel):
    configured: bool
    provider: str
    daily_limit: int
    remaining_today: int


async def _used_today(db, user) -> int:
    start = datetime.now(BRT).replace(hour=0, minute=0, second=0, microsecond=0)
    return await db.fetchval("SELECT count(*) FROM audit_log WHERE actor_id = $1 AND action = 'assistant.ask' AND at >= $2",
                             user.user_id, start)


@router.get("/status", response_model=StatusOut, summary="O assistente está ligado? Quantas perguntas restam hoje?")
async def assistant_status(user: User, db: TenantDb, request: Request) -> StatusOut:
    cfg = settings(request)
    used = await _used_today(db, user)
    return StatusOut(configured=bool(cfg.gemini_api_key), provider="Google Gemini", daily_limit=assistant.DAILY_LIMIT,
                     remaining_today=max(0, assistant.DAILY_LIMIT - used))


@router.post("/chat", response_model=ChatOut, summary="Pergunta ao assistente (anonimiza antes de enviar ao provedor de IA)")
async def chat(body: ChatIn, user: User, db: TenantDb, request: Request) -> ChatOut:
    cfg = settings(request)
    if not cfg.gemini_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "assistente não configurado (falta GEMINI_API_KEY)")
    if body.messages[-1].role != "user":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "a última mensagem tem de ser a pergunta")
    used = await _used_today(db, user)
    if used >= assistant.DAILY_LIMIT:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"limite de {assistant.DAILY_LIMIT} perguntas por dia atingido; volta amanhã")

    vault = assistant.Vault(dict(body.mapping))
    history = [{"role": m.role, "text": vault.mask(m.text)} for m in body.messages]
    tenant = await db.fetchval("SELECT name FROM tenants WHERE id = $1", user.tenant_id)
    transport = getattr(request.app.state, "ai_transport", None)       # testes: provedor falso
    async with httpx.AsyncClient(timeout=30, transport=transport) as http:      # passou disso, tenta o próximo modelo
        async def post(url: str, payload: dict) -> httpx.Response:
            return await http.post(url, json=payload, headers={"x-goog-api-key": cfg.gemini_api_key})

        try:
            reply = await assistant.converse(db, vault, history=history, tenant=tenant, alarm_id=body.alarm_id,
                                             models=list(cfg.ai_models), post=post)
        except assistant.AssistantError as e:
            raise HTTPException(e.status, str(e))

    # o log guarda o que foi consultado, não a pergunta (pode ter dado pessoal)
    await audit(db, user.tenant_id, user.user_id, "assistant.ask", request=request, target_type="assistant",
                label=reply.model, details={"tools": reply.tools, "alarm_id": body.alarm_id})
    return ChatOut(reply=vault.unmask(reply.text), mapping=vault.mapping, tools=reply.tools, model=reply.model,
                   remaining_today=max(0, assistant.DAILY_LIMIT - used - 1))
