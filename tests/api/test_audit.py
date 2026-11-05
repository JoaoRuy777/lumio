"""Log de auditoria: as ações ficam registradas, só o admin consulta, só cresce."""

import asyncpg
import pytest

from .conftest import needs_db, signup
from .test_dashboard import get, net  # noqa: F401

pytestmark = needs_db


async def entries(client, headers, **params):
    resp = await client.get("/api/audit-log", headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_registra_acesso_e_cadastros(client, net):
    h = net["headers"]
    # login certo e errado (o errado fica no provedor do e-mail)
    assert (await client.post("/api/auth/login", json={"email": "admin@a.com.br", "password": "errada-123"})).status_code == 401
    await client.post("/api/auth/login", json={"email": "admin@a.com.br", "password": "senha-forte-123"},
                      headers={"X-Forwarded-For": "200.150.10.20, 10.0.0.1"})

    ch = (await client.post("/api/notification-channels", headers=h,
                            json={"name": "NOC", "type": "email", "target": "noc@a.com.br"})).json()["channel"]
    await client.patch(f"/api/notification-channels/{ch['id']}", headers=h, json={"min_severity": "critical"})
    await client.patch(f"/api/olts/{net['olt_id']}", headers=h, json={"community": "nova-secreta", "lat": -22.2, "lon": -49.9})
    user = (await client.post("/api/users", headers=h, json={"name": "Bruno", "email": "bruno@a.com.br",
                                                             "password": "senha-forte-123", "role": "operator"})).json()
    await client.delete(f"/api/users/{user['id']}", headers=h)

    log = await entries(client, h)
    actions = [e["action"] for e in log["items"]]
    for a in ("auth.signup", "olt.create", "auth.login_failed", "auth.login", "channel.create", "channel.update",
              "olt.update", "user.create", "user.delete"):
        assert a in actions, a
    assert actions[0] == "user.delete"                                   # mais recente primeiro
    by = {e["action"]: e for e in log["items"]}
    assert by["auth.login"]["ip"] == "200.150.10.20"
    assert by["auth.login_failed"]["action_label"] == "Errou a senha ao entrar"
    assert by["user.delete"]["target_label"] == "Bruno <bruno@a.com.br>" and by["user.delete"]["actor_name"] == "Admin"
    # o segredo da OLT nunca vai para o log
    assert by["olt.update"]["details"]["community"] == "(alterada)"
    assert "nova-secreta" not in str(log)

    # filtros: categoria, busca e CSV
    assert {e["action"] for e in (await entries(client, h, category="user"))["items"]} == {"user.create", "user.delete"}
    assert [e["action"] for e in (await entries(client, h, q="noc@a.com.br"))["items"]] == ["channel.create"]
    csv = await client.get("/api/audit-log/export.csv", headers=h, params={"category": "auth"})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert "Errou a senha ao entrar" in csv.text and "Criou usuário" not in csv.text


async def test_so_admin_le_e_cada_provedor_ve_o_seu(client, net):
    h = net["headers"]
    await client.post("/api/users", headers=h, json={"name": "Op", "email": "op@a.com.br",
                                                     "password": "senha-forte-123", "role": "operator"})
    login = await client.post("/api/auth/login", json={"email": "op@a.com.br", "password": "senha-forte-123"})
    op = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/api/audit-log", headers=op)).status_code == 403
    other = await signup(client, company="Provedor B", email="admin@b.com.br")
    assert [e["action"] for e in (await entries(client, other))["items"]] == ["auth.signup"]


async def test_log_so_cresce(pool, net):
    """O papel da API (lumio_app) pode inserir e ler, mas não alterar nem apagar."""
    async with pool.acquire() as conn:
        for sql in ("DELETE FROM audit_log", "UPDATE audit_log SET action = 'x'", "TRUNCATE audit_log"):
            async with conn.transaction():
                await conn.execute("SET LOCAL ROLE lumio_app")
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await conn.execute(sql)
    assert await pool.fetchval("SELECT count(*) FROM audit_log") > 0


async def test_redefinicao_pelo_email_fica_no_log(client, net, pool):
    import hashlib
    uid = await pool.fetchval("SELECT id FROM users WHERE email = 'admin@a.com.br'")
    await pool.execute("INSERT INTO password_resets (user_id, token_hash, expires_at) VALUES ($1, $2, now() + interval '1 hour')",
                       uid, hashlib.sha256(("t" * 43).encode()).hexdigest())
    assert (await client.post("/api/auth/reset", json={"token": "t" * 43, "new_password": "outra-senha-123"})).status_code == 204
    login = await client.post("/api/auth/login", json={"email": "admin@a.com.br", "password": "outra-senha-123"})
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    actions = [e["action"] for e in (await entries(client, h, category="auth"))["items"]]
    assert "auth.password_reset" in actions
