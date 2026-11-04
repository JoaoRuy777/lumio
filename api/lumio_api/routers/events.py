"""Tempo real: Server-Sent Events com os avisos do worker (alarme aberto,
encerrado, reconhecido), só do tenant do usuário.

O worker publica em Redis Pub/Sub no canal lumio:events:<tenant>; cada conexão
SSE assina apenas o canal do próprio tenant. O painel usa o aviso para
recarregar o que mudou: o dado em si sempre vem das rotas normais (com RLS).
"""

from __future__ import annotations

import logging
from typing import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from ..deps import User

log = logging.getLogger("lumio_api.events")
router = APIRouter(tags=["tempo real"])

HEARTBEAT_S = 15.0       # comentário ": ping" mantém proxies e o navegador com a conexão aberta


async def event_stream(request: Request, redis, tenant_id: UUID, heartbeat: float = HEARTBEAT_S) -> AsyncIterator[str]:
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"lumio:events:{tenant_id}")
    try:
        yield "retry: 3000\nevent: ready\ndata: {}\n\n"
        while not await request.is_disconnected():
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=heartbeat)
            if msg is None:
                yield ": ping\n\n"
            else:
                yield f"data: {msg['data']}\n\n"
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()


@router.get("/events", summary="Avisos em tempo real (SSE) do provedor logado",
            response_class=StreamingResponse)
async def events(user: User, request: Request) -> StreamingResponse:
    redis = request.app.state.redis
    if redis is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "tempo real desativado (REDIS_URL não definido)")
    return StreamingResponse(
        event_stream(request, redis, user.tenant_id),
        media_type="text/event-stream",
        # X-Accel-Buffering: o nginx entrega cada evento na hora, sem juntar em buffer
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
