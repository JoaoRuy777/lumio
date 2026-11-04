"""Critério de pronto da sprint 3: um provedor nunca enxerga dados de outro.

Duas camadas são testadas:
1. API: com o token do provedor B, nenhuma rota devolve ou altera dados do A.
2. Banco: com o papel da API (lumio_app) e o tenant B, o RLS esconde as
   linhas do A em todas as tabelas e recusa escrever em nome do A, mesmo
   com SQL que "esquece" o filtro por tenant.
"""

import asyncpg
import pytest

from .conftest import needs_db, olt_body, signup

pytestmark = needs_db


@pytest.fixture
async def two_tenants(client, lab, pool):
    a = await signup(client, company="Provedor A", email="admin@a.com.br")
    b = await signup(client, company="Provedor B", email="admin@b.com.br")
    olt_a = (await client.post("/api/olts", headers=a, json=olt_body(lab, name="olt-do-A"))).json()["olt"]["id"]
    # um alarme do A, como o worker gravaria
    await pool.execute(
        "INSERT INTO alarms (tenant_id, olt_id, kind, severity, dedup_key, source, event_ts, first_seen_at, last_seen_at) "
        "SELECT tenant_id, id, 'olt_unreachable', 'critical', 'k', 'poll', now(), now(), now() FROM olts")
    tenant_a, tenant_b = [r["id"] for r in await pool.fetch("SELECT id FROM tenants ORDER BY name")]
    return {"a": a, "b": b, "olt_a": olt_a, "tenant_a": tenant_a, "tenant_b": tenant_b}


async def test_api_nao_mostra_nem_altera_olt_de_outro_provedor(client, lab, two_tenants):
    b, olt_a = two_tenants["b"], two_tenants["olt_a"]

    listing = (await client.get("/api/olts", headers=b)).json()
    assert listing == {"items": [], "usage": {"used": 0, "limit": 2}}

    # 404, não 403: nem confirma que a OLT existe
    assert (await client.get(f"/api/olts/{olt_a}", headers=b)).status_code == 404
    assert (await client.patch(f"/api/olts/{olt_a}", headers=b, json={"name": "roubada"})).status_code == 404
    assert (await client.delete(f"/api/olts/{olt_a}", headers=b)).status_code == 404
    assert (await client.post(f"/api/olts/{olt_a}/discover", headers=b)).status_code == 404
    assert (await client.post(f"/api/olts/{olt_a}/test-connection", headers=b)).status_code == 404

    me_b = (await client.get("/api/auth/me", headers=b)).json()
    assert me_b["tenant_name"] == "Provedor B" and me_b["olts"]["used"] == 0

    # e o A continua intacto
    olt = (await client.get(f"/api/olts/{olt_a}", headers=two_tenants["a"])).json()
    assert olt["name"] == "olt-do-A" and olt["onus_total"] == 16 and olt["active_alarms"] == 1


async def test_mesmo_nome_de_olt_em_provedores_diferentes(client, lab, two_tenants):
    resp = await client.post("/api/olts", headers=two_tenants["b"], json=olt_body(lab, name="olt-do-A"))
    assert resp.status_code == 201


async def as_api_role(pool, tenant_id):
    conn = await pool.acquire()
    tx = conn.transaction()
    await tx.start()
    await conn.execute("SET LOCAL ROLE lumio_app")
    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))
    return conn, tx


TENANT_TABLES = ["olts", "pon_ports", "onus", "alarms", "users", "optical_readings", "olt_health_readings"]


async def test_rls_esconde_todas_as_tabelas(pool, two_tenants):
    conn, tx = await as_api_role(pool, two_tenants["tenant_b"])
    try:
        for table in TENANT_TABLES:
            # sem WHERE nenhum: quem filtra é o banco
            rows = await conn.fetch(f"SELECT tenant_id FROM {table}")
            assert {r["tenant_id"] for r in rows} <= {two_tenants["tenant_b"]}, table
        assert [r["name"] for r in await conn.fetch("SELECT name FROM tenants")] == ["Provedor B"]
        assert await conn.execute("UPDATE olts SET name = 'x'") == "UPDATE 0"
        assert await conn.execute("DELETE FROM alarms") == "DELETE 0"
    finally:
        await tx.rollback()
        await pool.release(conn)


async def test_rls_recusa_gravar_em_nome_de_outro_tenant(pool, two_tenants):
    conn, tx = await as_api_role(pool, two_tenants["tenant_b"])
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):      # violação de política RLS
            await conn.execute("INSERT INTO olts (tenant_id, name) VALUES ($1, 'intrusa')", two_tenants["tenant_a"])
    finally:
        await tx.rollback()
        await pool.release(conn)


async def test_sem_tenant_definido_nao_enxerga_nada(pool, two_tenants):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL ROLE lumio_app")
        for table in TENANT_TABLES + ["tenants"]:
            assert await conn.fetchval(f"SELECT count(*) FROM {table}") == 0, table


async def test_toda_tabela_com_tenant_tem_rls(pool):
    """Protege o futuro: tabela nova com tenant_id sem RLS quebra este teste."""
    rows = await pool.fetch(
        "SELECT c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN information_schema.columns col ON col.table_name = c.relname AND col.table_schema = n.nspname "
        "WHERE n.nspname = 'public' AND c.relkind = 'r' AND col.column_name = 'tenant_id'")
    assert rows
    assert [r["relname"] for r in rows if not r["relrowsecurity"]] == []


async def test_rotas_do_painel_nao_vazam_dados(client, pool, two_tenants):
    """Sprint 4: visão geral, PONs, ONUs, histórico e alarmes também isolados."""
    b, olt_a = two_tenants["b"], two_tenants["olt_a"]
    onu_a = await pool.fetchval("SELECT id FROM onus LIMIT 1")
    alarm_a = await pool.fetchval("SELECT id FROM alarms LIMIT 1")

    ov = (await client.get("/api/overview", headers=b)).json()
    assert ov["olts"]["total"] == 0 and ov["onus"]["total"] == 0 and ov["alarms"]["total"] == 0
    assert (await client.get("/api/onus", headers=b)).json() == {"items": [], "total": 0}
    assert (await client.get("/api/alarms", headers=b, params={"status": "all"})).json() == {"items": [], "total": 0}
    for path in (f"/api/olts/{olt_a}/pons", f"/api/onus/{onu_a}", f"/api/onus/{onu_a}/readings",
                 f"/api/alarms/{alarm_a}"):
        assert (await client.get(path, headers=b)).status_code == 404, path
    assert (await client.post(f"/api/alarms/{alarm_a}/ack", headers=b)).status_code == 404
    # filtrar pela OLT do outro também não traz nada
    assert (await client.get("/api/onus", headers=b, params={"olt_id": str(olt_a)})).json()["total"] == 0
    assert await pool.fetchval("SELECT status FROM alarms WHERE id = $1", alarm_a) == "active"
