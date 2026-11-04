"""Trocar a própria senha e "esqueci minha senha"."""

import asyncpg
import pytest
from cryptography.fernet import Fernet

from .conftest import needs_db, signup

pytestmark = needs_db

EMAIL, OLD, NEW = "admin@a.com.br", "senha-forte-123", "senha-nova-456"


async def login(client, password, email=EMAIL):
    return await client.post("/api/auth/login", json={"email": email, "password": password})


def bearer(resp):
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def reset_token(pool, settings, email=EMAIL) -> str:
    """O link do e-mail: a API guarda o token cifrado só até o notificador enviar."""
    enc = await pool.fetchval(
        "SELECT r.token_enc FROM password_resets r JOIN users u ON u.id = r.user_id "
        "WHERE u.email = $1 AND r.used_at IS NULL ORDER BY r.created_at DESC LIMIT 1", email)
    return Fernet(settings.secret_key.encode()).decrypt(enc.encode()).decode()


async def test_trocar_senha_derruba_as_outras_sessoes(client):
    first = await signup(client)                         # sessão no computador
    other = bearer(await login(client, OLD))             # sessão no celular
    wrong = await client.post("/api/auth/password", headers=first,
                              json={"current_password": "errada", "new_password": NEW})
    assert wrong.status_code == 400 and "senha atual" in wrong.json()["detail"]

    resp = await client.post("/api/auth/password", headers=first, json={"current_password": OLD, "new_password": NEW})
    assert resp.status_code == 200
    assert (await client.get("/api/olts", headers=bearer(resp))).status_code == 200      # quem trocou continua
    assert (await client.get("/api/olts", headers=other)).status_code == 401              # o resto cai
    assert (await login(client, OLD)).status_code == 401
    assert (await login(client, NEW)).status_code == 200


async def test_esqueci_senha_link_de_uso_unico(client, pool, settings):
    session = await signup(client)
    resp = await client.post("/api/auth/forgot", json={"email": "ADMIN@a.com.br"})
    assert resp.status_code == 202
    token = await reset_token(pool, settings)

    assert (await client.post("/api/auth/reset", json={"token": token, "new_password": NEW})).status_code == 204
    assert (await login(client, NEW)).status_code == 200
    assert (await client.get("/api/olts", headers=session)).status_code == 401           # sessão antiga caiu
    again = await client.post("/api/auth/reset", json={"token": token, "new_password": "outra-senha-789"})
    assert again.status_code == 400 and "link inválido" in again.json()["detail"]


async def test_link_vencido_ou_substituido(client, pool, settings):
    await signup(client)
    await client.post("/api/auth/forgot", json={"email": EMAIL})
    old = await reset_token(pool, settings)
    await client.post("/api/auth/forgot", json={"email": EMAIL})       # pedido novo invalida o anterior
    assert (await client.post("/api/auth/reset", json={"token": old, "new_password": NEW})).status_code == 400

    new = await reset_token(pool, settings)
    await pool.execute("UPDATE password_resets SET expires_at = now() - interval '1 minute'")
    assert (await client.post("/api/auth/reset", json={"token": new, "new_password": NEW})).status_code == 400
    assert (await login(client, OLD)).status_code == 200


async def test_email_desconhecido_responde_igual_e_limite_por_hora(client, pool):
    await signup(client)
    unknown = await client.post("/api/auth/forgot", json={"email": "ninguem@x.com.br"})
    known = await client.post("/api/auth/forgot", json={"email": EMAIL})
    assert unknown.status_code == known.status_code == 202 and unknown.json() == known.json()
    for _ in range(5):
        await client.post("/api/auth/forgot", json={"email": EMAIL})
    assert await pool.fetchval("SELECT count(*) FROM password_resets") == 3      # no máximo 3 por hora


async def test_api_nao_le_a_tabela_de_links(client, pool):
    """O papel da API (lumio_app) só chega aos links pelas duas funções: ler a tabela é negado."""
    await signup(client)
    await client.post("/api/auth/forgot", json={"email": EMAIL})
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL ROLE lumio_app")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetchval("SELECT count(*) FROM password_resets")
