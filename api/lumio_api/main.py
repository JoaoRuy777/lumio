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
from .routers import alarms, assistant, audit_log, auth, channels, customers, escalation, events, internal, maintenance, network, olts, overview, reports, users
from .security import Cipher


class SecurityHeaders:
    """Respostas da API: nunca em cache (dados do provedor), sem "farejar" o tipo e sem
    abrir em iframe. ASGI puro, para não atrapalhar o SSE (/api/events)."""

    HEADERS = [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
               (b"referrer-policy", b"strict-origin-when-cross-origin")]

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                names = {k.lower() for k, _ in headers}
                headers += [h for h in self.HEADERS if h[0] not in names]
                if b"cache-control" not in names:
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


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
    app.add_middleware(SecurityHeaders)
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
    api.include_router(maintenance.router)
    api.include_router(escalation.router)
    api.include_router(audit_log.router)
    api.include_router(assistant.router)
    api.include_router(internal.router)
    app.include_router(api)
    return app


app = create_app()
