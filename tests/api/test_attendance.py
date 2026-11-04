"""Atendimento de chamados: assumir, transferir, anotar, encerrar e o relatório da equipe."""

from datetime import datetime, timedelta, timezone

from .conftest import needs_db, signup
from .test_dashboard import get, net  # noqa: F401  (fixture: OLT coletada pelo caminho real)

pytestmark = needs_db


async def second_user(client, net, name="Bruno", email="bruno@a.com.br", role="operator"):
    resp = await client.post("/api/users", headers=net["headers"],
                             json={"name": name, "email": email, "password": "senha-bruno-123", "role": role})
    login = await client.post("/api/auth/login", json={"email": email, "password": "senha-bruno-123"})
    return resp.json()["id"], {"Authorization": f"Bearer {login.json()['access_token']}"}


async def post(client, headers, path, json=None):
    return await client.post(f"/api{path}", headers=headers, json=json)


async def test_ciclo_do_chamado_e_linha_do_tempo(client, net):
    await net["fiber_cut"]()
    [cut] = (await get(client, net, "/alarms"))["items"]
    bruno_id, bruno = await second_user(client, net)
    a = net["headers"]

    resp = await post(client, a, f"/alarms/{cut['id']}/assign", {})
    assert resp.status_code == 200
    taken = resp.json()
    assert (taken["assigned_to"], taken["status"]) == ("Admin", "acknowledged")
    assert taken["first_assigned_at"] and taken["work_closed_at"] is None

    assert (await post(client, a, f"/alarms/{cut['id']}/notes", {"body": "Equipe de campo enviada"})).status_code == 201
    assert (await post(client, a, f"/alarms/{cut['id']}/assign", {"user_id": bruno_id})).json()["assigned_to"] == "Bruno"

    # na fila do Bruno, não na do Admin
    mine = (await client.get("/api/alarms", headers=bruno, params={"mine": True})).json()
    assert [x["id"] for x in mine["items"]] == [cut["id"]]
    assert (await get(client, net, "/alarms", mine=True))["total"] == 0

    closed = await post(client, bruno, f"/alarms/{cut['id']}/close",
                        {"cause": "fiber_third_party", "notes": "Fibra rompida por obra; fusão refeita"})
    assert closed.status_code == 200
    c = closed.json()
    assert (c["work_closed_by"], c["resolution_cause"]) == ("Bruno", "fiber_third_party")
    assert (await client.get("/api/alarms", headers=bruno, params={"mine": True})).json()["total"] == 0

    assert (await post(client, a, f"/alarms/{cut['id']}/close", {"cause": "other", "notes": "de novo"})).status_code == 409
    assert (await post(client, a, f"/alarms/{cut['id']}/reopen")).status_code == 200

    timeline = (await client.get(f"/api/alarms/{cut['id']}/timeline", headers=a)).json()
    kinds = [t["kind"] for t in timeline]
    assert kinds[0] == "opened"
    assert [k for k in kinds if k != "notified"][1:] == ["assigned", "note", "transferred", "closed", "reopened"]
    transfer = next(t for t in timeline if t["kind"] == "transferred")
    assert (transfer["actor"], transfer["target"]) == ("Admin", "Bruno")
    assert next(t for t in timeline if t["kind"] == "note")["body"] == "Equipe de campo enviada"


async def test_regras_do_chamado(client, net, pool):
    await net["fiber_cut"]()
    [cut] = (await get(client, net, "/alarms"))["items"]
    a = net["headers"]
    # encerrar sem ninguém ter assumido
    resp = await post(client, a, f"/alarms/{cut['id']}/close", {"cause": "power", "notes": "sem energia"})
    assert resp.status_code == 409 and "assuma" in resp.json()["detail"]
    # ONU dentro do rompimento não é um chamado à parte
    [child] = (await get(client, net, "/alarms", parent_id=cut["id"], limit=1))["items"]
    assert (await post(client, a, f"/alarms/{child['id']}/assign", {})).status_code == 409
    # causa fora da lista e transferência para usuário de outro provedor
    assert (await post(client, a, f"/alarms/{cut['id']}/assign", {})).status_code == 200
    assert (await post(client, a, f"/alarms/{cut['id']}/close", {"cause": "aliens", "notes": "xx"})).status_code == 422
    await signup(client, company="Provedor B", email="admin@b.com.br")
    other = await pool.fetchval("SELECT id FROM users WHERE email = 'admin@b.com.br'")
    assert (await post(client, a, f"/alarms/{cut['id']}/assign", {"user_id": str(other)})).status_code == 404
    # outro provedor não vê o chamado
    b = await client.post("/api/auth/login", json={"email": "admin@b.com.br", "password": "senha-forte-123"})
    hb = {"Authorization": f"Bearer {b.json()['access_token']}"}
    assert (await client.get(f"/api/alarms/{cut['id']}/timeline", headers=hb)).status_code == 404


async def test_relatorio_de_atendimento(client, net, pool):
    await net["fiber_cut"]()
    [cut] = (await get(client, net, "/alarms"))["items"]
    bruno_id, bruno = await second_user(client, net)
    a = net["headers"]
    await post(client, a, f"/alarms/{cut['id']}/assign", {})
    await post(client, a, f"/alarms/{cut['id']}/notes", {"body": "Liguei para o cliente"})
    await post(client, a, f"/alarms/{cut['id']}/assign", {"user_id": bruno_id})
    await post(client, bruno, f"/alarms/{cut['id']}/close", {"cause": "fiber_third_party", "notes": "Fusão refeita"})

    # horários controlados: aberto em T0, assumido +10 min, transferido +30, encerrado +70
    t0 = datetime.now(timezone.utc) - timedelta(hours=2)
    m = lambda minutes: t0 + timedelta(minutes=minutes)  # noqa: E731
    await pool.execute("UPDATE alarms SET created_at = $2, first_assigned_at = $3, work_closed_at = $4 WHERE id = $1",
                       cut["id"], m(0), m(10), m(70))
    events = await pool.fetch("SELECT id, kind FROM alarm_events WHERE alarm_id = $1 ORDER BY created_at", cut["id"])
    for e, minutes in zip(events, (10, 20, 30, 70)):          # assigned, note, assigned, closed
        await pool.execute("UPDATE alarm_events SET created_at = $2 WHERE id = $1", e["id"], m(minutes))

    rep = (await client.get("/api/reports/attendance", headers=a)).json()
    s = rep["summary"]
    assert (s["tickets"], s["assumed"], s["closed"], s["unattended"]) == (1, 1, 1, 0)
    assert (s["tme_min"], s["tma_min"], s["assumed_within_sla_pct"]) == (10.0, 60.0, 100.0)
    ops = {o["name"]: o for o in rep["operators"]}
    assert ops["Admin"] == {"name": "Admin", "taken": 1, "closed": 0, "open": 0, "tme_min": 10.0, "tma_min": None,
                            "time_in_attendance_min": 20.0, "notes": 1}
    assert (ops["Bruno"]["taken"], ops["Bruno"]["closed"], ops["Bruno"]["tma_min"],
            ops["Bruno"]["time_in_attendance_min"]) == (1, 1, 60.0, 40.0)
    assert rep["causes"] == [{"cause": "fiber_third_party", "label": "Rompimento por terceiros (obra, veículo)",
                              "count": 1, "pct": 100.0, "tma_min": 60.0}]
    [item] = rep["items"]
    assert (item["owner"], item["closed_by"], item["tme_min"], item["tma_min"]) == ("Bruno", "Bruno", 10.0, 60.0)

    csv = await client.get("/api/reports/attendance", headers=a, params={"format": "csv"})
    assert csv.headers["content-type"].startswith("text/csv")
    text = csv.content.decode("utf-8-sig")
    assert "TMA (min)" in text and "60,0" in text and "Fusão refeita" in text
    pdf = await client.get("/api/reports/attendance", headers=a, params={"format": "pdf"})
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
