"""Proteção do login contra força bruta."""

from .conftest import needs_db, signup

pytestmark = needs_db

GOOD = "senha-forte-123"


async def login(client, email="admin@a.com.br", password=GOOD, ip="200.1.1.1"):
    return await client.post("/api/auth/login", json={"email": email, "password": password},
                             headers={"X-Forwarded-For": ip})


async def test_cinco_erros_travam_o_email_mesmo_com_a_senha_certa(client, pool):
    await signup(client)
    for _ in range(5):
        assert (await login(client, password="errada-123")).status_code == 401
    blocked = await login(client)                              # senha certa, mas travado
    assert blocked.status_code == 429
    assert "tente de novo em 15 min" in blocked.json()["detail"]
    assert 800 < int(blocked.headers["Retry-After"]) <= 900
    # outro IP não destrava o mesmo e-mail
    assert (await login(client, ip="201.2.2.2")).status_code == 429

    # passados os 15 min, volta a funcionar
    await pool.execute("UPDATE login_attempts SET at = at - interval '16 minutes'")
    assert (await login(client)).status_code == 200


async def test_acerto_zera_a_contagem(client):
    await signup(client)
    for _ in range(4):
        await login(client, password="errada-123")
    assert (await login(client)).status_code == 200
    for _ in range(4):
        assert (await login(client, password="errada-123")).status_code == 401
    assert (await login(client)).status_code == 200


async def test_email_que_nao_existe_trava_igual(client):
    """Mesma resposta para quem tem e quem não tem conta: o bloqueio não revela nada."""
    for _ in range(5):
        assert (await login(client, email="ninguem@x.com.br", password="qualquer-123")).status_code == 401
    assert (await login(client, email="ninguem@x.com.br", password="qualquer-123")).status_code == 429


async def test_muitos_emails_do_mesmo_ip_travam_o_ip(client):
    await signup(client)
    for i in range(20):
        await login(client, email=f"chute{i}@x.com.br", password="qualquer-123", ip="66.6.6.6")
    assert (await login(client, ip="66.6.6.6")).status_code == 429          # mesmo com a conta certa
    assert (await login(client, ip="200.1.1.1")).status_code == 200         # de outro lugar, entra


async def test_bloqueio_fica_na_auditoria(client):
    headers = await signup(client)
    for _ in range(6):
        await login(client, password="errada-123")
    log = (await client.get("/api/audit-log", headers=headers, params={"category": "auth"})).json()["items"]
    actions = [e["action"] for e in log]
    assert actions.count("auth.login_failed") == 5 and actions[0] == "auth.login_blocked"
    assert log[0]["action_label"] == "Login travado (muitas tentativas)"


async def test_api_nao_le_a_tabela_de_tentativas(pool):
    import asyncpg
    import pytest
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL ROLE lumio_app")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetch("SELECT * FROM login_attempts")
