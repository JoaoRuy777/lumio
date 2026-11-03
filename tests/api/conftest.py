"""API rodando em processo (httpx + ASGI), contra o Postgres de teste.

O pool da API assume o papel lumio_app (SET ROLE), o mesmo da produção:
sujeito ao RLS. Assim os testes provam o isolamento no banco, não só nos filtros.
"""

from __future__ import annotations

import httpx
import pytest
from cryptography.fernet import Fernet

from lumio_api.config import Settings
from lumio_api.main import create_app
from tests.conftest import Lab
from tests.db_fixtures import needs_db  # noqa: F401

SERVICE_TOKEN = "token-de-servico-dos-testes"


@pytest.fixture
def settings(test_db_url) -> Settings:
    return Settings(
        database_url=test_db_url, jwt_secret="segredo-jwt-dos-testes-com-32-bytes-ou-mais", secret_key=Fernet.generate_key().decode(),
        service_token=SERVICE_TOKEN, db_role="lumio_app", snmp_timeout=0.5, snmp_retries=0,
    )


@pytest.fixture
async def app(settings, pool):        # pool: limpa o banco antes de cada teste
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://lumio.test") as c:
        yield c


async def signup(client: httpx.AsyncClient, company: str = "Provedor A", email: str = "admin@a.com.br",
                 password: str = "senha-forte-123") -> dict:
    """Cria o provedor e devolve os headers de autenticação."""
    resp = await client.post("/api/auth/signup", json={"company": company, "name": "Admin", "email": email,
                                                       "password": password})
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def olt_body(lab: Lab, sim_olt: str = "olt-1", **extra) -> dict:
    """Formulário de cadastro apontando para uma OLT do simulador (extra sobrescreve campos)."""
    olt = lab.network.olt(sim_olt)
    return {"name": sim_olt, "host": "127.0.0.1", "snmp_port": olt.port, "community": olt.community, **extra}
