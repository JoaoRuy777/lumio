"""Usuários do provedor: o administrador cria, lista e remove."""

from .conftest import needs_db, olt_body, signup

pytestmark = needs_db


async def login(client, email, password="senha-avaliador-1"):
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_admin_cria_usuario_que_ve_o_mesmo_provedor(client, lab):
    admin = await signup(client)
    await client.post("/api/olts", headers=admin, json=olt_body(lab))
    resp = await client.post("/api/users", headers=admin, json={
        "name": "Prof. Avaliador", "email": "avaliador@unimar.br", "password": "senha-avaliador-1", "role": "admin"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "admin" and "password" not in resp.text

    avaliador = await login(client, "avaliador@unimar.br")
    me = (await client.get("/api/auth/me", headers=avaliador)).json()
    assert me["tenant_name"] == "Provedor A" and me["role"] == "admin"
    assert len((await client.get("/api/olts", headers=avaliador)).json()["items"]) == 1
    emails = [u["email"] for u in (await client.get("/api/users", headers=avaliador)).json()["items"]]
    assert emails == ["admin@a.com.br", "avaliador@unimar.br"]


async def test_operador_ve_tudo_mas_nao_cria_usuario_nem_altera_cadastro(client, lab):
    admin = await signup(client)
    await client.post("/api/users", headers=admin, json={
        "name": "Operadora", "email": "noc@a.com.br", "password": "senha-avaliador-1"})      # padrão: operador
    noc = await login(client, "noc@a.com.br")
    assert (await client.get("/api/olts", headers=noc)).status_code == 200
    assert (await client.post("/api/olts", headers=noc, json=olt_body(lab))).status_code == 403
    assert (await client.post("/api/users", headers=noc, json={
        "name": "Outro", "email": "outro@a.com.br", "password": "senha-avaliador-1"})).status_code == 403


async def test_email_repetido_mesmo_em_outro_provedor(client):
    a = await signup(client)
    await signup(client, company="Provedor B", email="admin@b.com.br")
    resp = await client.post("/api/users", headers=a, json={
        "name": "Copia", "email": "ADMIN@b.com.br", "password": "senha-avaliador-1"})
    assert resp.status_code == 409


async def test_isolamento_entre_provedores(client):
    a = await signup(client)
    b = await signup(client, company="Provedor B", email="admin@b.com.br")
    created = (await client.post("/api/users", headers=a, json={
        "name": "Usuario A", "email": "u@a.com.br", "password": "senha-avaliador-1"})).json()
    assert [u["email"] for u in (await client.get("/api/users", headers=b)).json()["items"]] == ["admin@b.com.br"]
    assert (await client.delete(f"/api/users/{created['id']}", headers=b)).status_code == 404


async def test_remover_usuario_corta_o_acesso_na_hora(client):
    admin = await signup(client)
    created = (await client.post("/api/users", headers=admin, json={
        "name": "Avaliador", "email": "av@a.com.br", "password": "senha-avaliador-1"})).json()
    avaliador = await login(client, "av@a.com.br")
    assert (await client.get("/api/olts", headers=avaliador)).status_code == 200
    assert (await client.delete(f"/api/users/{created['id']}", headers=admin)).status_code == 204
    assert (await client.get("/api/olts", headers=avaliador)).status_code == 401
    me = (await client.get("/api/auth/me", headers=admin)).json()
    assert (await client.delete(f"/api/users/{me['user_id']}", headers=admin)).status_code == 409
