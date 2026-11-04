"""API da Lumio.

    uvicorn lumio_api.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import APIRouter, FastAPI

from lumio_collector.snmp import SnmpClient

from .config import Settings
from .db import create_pool
from .routers import alarms, auth, channels, customers, events, internal, network, olts, overview, reports, users
from .security import Cipher


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg = settings or Settings.from_env()
        app.state.settings = cfg
        app.state.cipher = Cipher(cfg.secret_key)
        app.state.pool = await create_pool(cfg.database_url, cfg.db_role)
        app.state.snmp = SnmpClient()
        app.state.redis = redis.from_url(cfg.redis_url, decode_responses=True) if cfg.redis_url else None
        yield
        await app.state.pool.close()
        if app.state.redis:
            await app.state.redis.aclose()

    app = FastAPI(title="Lumio API", version="0.3.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    api = APIRouter(prefix="/api")

    @api.get("/health", tags=["saúde"])
    async def health():
        return {"status": "ok"}

    api.include_router(auth.router)
    api.include_router(overview.router)
    api.include_router(olts.router)
    api.include_router(network.router)
    api.include_router(alarms.router)
    api.include_router(events.router)
    api.include_router(channels.router)
    api.include_router(reports.router)
    api.include_router(users.router)
    api.include_router(customers.router)
    api.include_router(internal.router)
    app.include_router(api)
    return app


app = create_app()
