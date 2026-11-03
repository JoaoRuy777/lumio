"""Rotas internas, só para os serviços da Lumio (token de serviço, não JWT)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ..db import system_tx
from ..deps import cipher, pool, service_auth
from ..schemas import CollectorOlt

router = APIRouter(prefix="/internal", tags=["interno"], dependencies=[Depends(service_auth)])


@router.get("/collector/olts", response_model=list[CollectorOlt],
            summary="OLTs ativas de todos os provedores, com a community decifrada, para o coletor")
async def collector_olts(request: Request) -> list[CollectorOlt]:
    async with system_tx(pool(request)) as conn:
        rows = await conn.fetch("SELECT * FROM lumio_collector_olts() ORDER BY tenant_id, name")
    c = cipher(request)
    return [CollectorOlt(**{k: v for k, v in r.items() if k != "community_enc"},
                         community=c.decrypt(r["community_enc"])) for r in rows]
