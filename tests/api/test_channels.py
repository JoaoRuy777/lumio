"""Canais de notificação pela API (sprint 5)."""

import pytest

from .conftest import needs_db, signup

pytestmark = needs_db

EMAIL = {"name": "NOC", "type": "email", "target": "noc@provedor-a.com.br", "min_severity": "major"}
HOOK = {"name": "Integração", "type": "webhook", "target": "https://hooks.provedor-a.com.br/lumio", "min_severity": "critical"}


async def test_criar_listar_e_segredo_do_webhook(client, pool):
    h = await signup(client)
    email = await client.post("/api/notification-channels", headers=h, json=EMAIL)
    assert email.status_code == 201 and email.json()["secret"] is None
    hook = (await client.post("/api/notification-channels", headers=h, json=HOOK)).json()
    assert len(hook["secret"]) >= 40                         # aparece só agora

    listed = (await client.get("/api/notification-channels", headers=h)).json()
    assert [c["name"] for c in listed] == ["Integração", "NOC"]
    assert all("secret" not in c and "secret_enc" not in c for c in listed)
    stored = await pool.fetchval("SELECT secret_enc FROM notification_channels WHERE type = 'webhook'")
    assert stored and hook["secret"] not in stored           # cifrado no banco

    rotated = (await client.post(f"/api/notification-channels/{hook['channel']['id']}/rotate-secret", headers=h)).json()
    assert rotated["secret"] != hook["secret"]


@pytest.mark.parametrize("body", [
    {**EMAIL, "target": "nao-e-email"},
    {**HOOK, "target": "ftp://hooks.a.com.br"},
    {**HOOK, "target": "hooks.a.com.br/sem-esquema"},
    {**EMAIL, "type": "sms"},
    {**EMAIL, "min_severity": "altissima"},
])
async def test_validacao(client, body):
    h = await signup(client)
    assert (await client.post("/api/notification-channels", headers=h, json=body)).status_code == 422


async def test_alterar_testar_e_ver_entregas(client):
    h = await signup(client)
    ch = (await client.post("/api/notification-channels", headers=h, json=EMAIL)).json()["channel"]
    upd = await client.patch(f"/api/notification-channels/{ch['id']}", headers=h,
                             json={"min_severity": "warning", "enabled": False})
    assert (upd.json()["min_severity"], upd.json()["enabled"]) == ("warning", False)
    bad = await client.patch(f"/api/notification-channels/{ch['id']}", headers=h, json={"target": "x"})
    assert bad.status_code == 422

    test = await client.post(f"/api/notification-channels/{ch['id']}/test", headers=h)
    assert test.status_code == 202 and test.json()["status"] == "pending"
    [d] = (await client.get(f"/api/notification-channels/{ch['id']}/deliveries", headers=h)).json()
    assert (d["event"], d["status"]) == ("test", "pending")
    assert (await client.get("/api/notification-channels", headers=h)).json()[0]["last_delivery"]["event"] == "test"

    assert (await client.delete(f"/api/notification-channels/{ch['id']}", headers=h)).status_code == 204


async def test_operador_testa_mas_nao_cria(client, pool):
    h = await signup(client)
    ch = (await client.post("/api/notification-channels", headers=h, json=EMAIL)).json()["channel"]
    await pool.execute("UPDATE users SET role = 'operator'")
    token = (await client.post("/api/auth/login", json={"email": "admin@a.com.br", "password": "senha-forte-123"})).json()
    op = {"Authorization": f"Bearer {token['access_token']}"}
    assert (await client.post("/api/notification-channels", headers=op, json=HOOK)).status_code == 403
    assert (await client.post(f"/api/notification-channels/{ch['id']}/test", headers=op)).status_code == 202


async def test_canais_isolados_entre_provedores(client):
    a = await signup(client, company="Provedor A", email="admin@a.com.br")
    b = await signup(client, company="Provedor B", email="admin@b.com.br")
    ch = (await client.post("/api/notification-channels", headers=a, json=EMAIL)).json()["channel"]
    assert (await client.get("/api/notification-channels", headers=b)).json() == []
    for method, path in [("PATCH", ""), ("DELETE", ""), ("POST", "/test"), ("POST", "/rotate-secret"), ("GET", "/deliveries")]:
        resp = await client.request(method, f"/api/notification-channels/{ch['id']}{path}", headers=b,
                                    json={"name": "x"} if method == "PATCH" else None)
        assert resp.status_code == 404, (method, path)
    # o mesmo nome em outro provedor pode
    assert (await client.post("/api/notification-channels", headers=b, json=EMAIL)).status_code == 201
