"""Cadastro, login e token."""

from datetime import timedelta
from uuid import uuid4

import jwt
import pytest

from lumio_api.security import create_token

from .conftest import needs_db, signup

pytestmark = needs_db


async def test_cadastro_cria_provedor_e_admin(client, pool):
    headers = await signup(client, company="Fibra Norte Telecom", email="Ana@FibraNorte.com.br")
    me = (await client.get("/api/auth/me", headers=headers)).json()
    assert me["tenant_name"] == "Fibra Norte Telecom"
    assert (me["email"], me["role"]) == ("Ana@fibranorte.com.br", "admin")   # domínio normalizado
    assert me["olts"] == {"used": 0, "limit": 2}
    slug = await pool.fetchval("SELECT slug FROM tenants")
    assert slug.startswith("fibra-norte-telecom-")


async def test_senha_guardada_com_argon2(client, pool):
    await signup(client, password="minha-senha-secreta")
    stored = await pool.fetchval("SELECT password_hash FROM users")
    assert stored.startswith("$argon2id$") and "minha-senha-secreta" not in stored


async def test_email_repetido_mesmo_com_outra_caixa(client):
    await signup(client, email="admin@a.com.br")
    resp = await client.post("/api/auth/signup", json={"company": "Outro", "name": "Xavier", "email": "ADMIN@a.com.br",
                                                       "password": "outra-senha-123"})
    assert resp.status_code == 409


@pytest.mark.parametrize("body", [
    {"company": "A", "name": "Admin", "email": "a@a.com", "password": "senha-forte-123"},       # nome curto
    {"company": "Prov", "name": "Admin", "email": "nao-e-email", "password": "senha-forte-123"},
    {"company": "Prov", "name": "Admin", "email": "a@a.com", "password": "curta"},
])
async def test_cadastro_valida_os_campos(client, body):
    assert (await client.post("/api/auth/signup", json=body)).status_code == 422


async def test_login(client):
    await signup(client, email="admin@a.com.br", password="senha-forte-123")
    ok = await client.post("/api/auth/login", json={"email": "Admin@A.com.br", "password": "senha-forte-123"})
    assert ok.status_code == 200
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"})
    assert me.status_code == 200

    wrong = await client.post("/api/auth/login", json={"email": "admin@a.com.br", "password": "errada-123"})
    unknown = await client.post("/api/auth/login", json={"email": "ninguem@a.com.br", "password": "senha-forte-123"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()           # não revela se o e-mail existe


async def test_rotas_protegidas_exigem_token_valido(client, settings):
    assert (await client.get("/api/olts")).status_code == 401
    assert (await client.get("/api/olts", headers={"Authorization": "Bearer lixo"})).status_code == 401

    claims = dict(user_id=uuid4(), tenant_id=uuid4(), role="admin")
    expired = create_token(settings.jwt_secret, **claims, ttl_minutes=-1)
    forged = create_token("outro-segredo-com-32-bytes-ou-mais!", **claims, ttl_minutes=60)
    for token in (expired, forged):
        assert (await client.get("/api/olts", headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_token_carrega_o_tenant(client, settings):
    headers = await signup(client)
    claims = jwt.decode(headers["Authorization"].split()[1], settings.jwt_secret, algorithms=["HS256"])
    assert {"sub", "tid", "role", "exp"} <= set(claims)
    assert claims["exp"] - claims["iat"] == pytest.approx(timedelta(hours=12).total_seconds())
