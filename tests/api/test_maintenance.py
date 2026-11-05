"""Janelas de manutenção programada (API + caminho real até o alarme)."""

from datetime import datetime, timedelta, timezone

from .conftest import needs_db, signup
from .test_dashboard import get, net  # noqa: F401

pytestmark = needs_db


def iso(minutes: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


async def pon_id(client, net, name):
    pons = (await client.get(f"/api/olts/{net['olt_id']}/pons", headers=net["headers"])).json()
    return next(p["id"] for p in pons if p["name"] == name)


async def test_agenda_silencia_o_rompimento_e_encerra(client, net):
    body = {"olt_id": net["olt_id"], "pon_id": await pon_id(client, net, "0/1/1"), "reason": "Troca do splitter da rua 7",
            "starts_at": iso(-1), "ends_at": iso(120)}
    resp = await client.post("/api/maintenance", headers=net["headers"], json=body)
    assert resp.status_code == 201, resp.text
    w = resp.json()
    assert (w["state"], w["pon"], w["created_by"], w["alarms_silenced"]) == ("active", "0/1/1", "Admin", 0)
    assert (await get(client, net, "/overview"))["maintenance_active"] == 1
    assert [x["id"] for x in await get(client, net, "/maintenance", current="true")] == [w["id"]]

    await net["fiber_cut"]()
    [cut] = (await get(client, net, "/alarms"))["items"]
    assert (cut["maintenance_id"], cut["maintenance_reason"]) == (w["id"], "Troca do splitter da rua 7")
    [listed] = await get(client, net, "/maintenance")
    assert listed["alarms_silenced"] == 1

    # encerrar agora: a janela termina, o alarme continua marcado
    ended = (await client.post(f"/api/maintenance/{w['id']}/end", headers=net["headers"])).json()
    assert ended["state"] == "finished"
    assert (await get(client, net, "/overview"))["maintenance_active"] == 0
    again = await client.post(f"/api/maintenance/{w['id']}/end", headers=net["headers"])
    assert again.status_code == 409


async def test_agendada_pode_ser_cancelada(client, net):
    body = {"olt_id": net["olt_id"], "reason": "Atualização de firmware", "starts_at": iso(60), "ends_at": iso(120)}
    w = (await client.post("/api/maintenance", headers=net["headers"], json=body)).json()
    assert (w["state"], w["pon_id"]) == ("scheduled", None)
    cancelled = (await client.post(f"/api/maintenance/{w['id']}/end", headers=net["headers"])).json()
    assert cancelled["state"] == "cancelled" and cancelled["cancelled_at"] is not None


async def test_validacoes(client, net):
    base = {"olt_id": net["olt_id"], "reason": "Troca", "starts_at": iso(10), "ends_at": iso(70)}
    cases = [
        ({"ends_at": iso(5)}, "depois do início"),
        ({"starts_at": iso(-100), "ends_at": iso(-50)}, "já passou"),
        ({"ends_at": iso(60 * 24 * 8)}, "7 dias"),
        ({"starts_at": "2026-11-08T02:00:00"}, "fuso"),
    ]
    for change, msg in cases:
        resp = await client.post("/api/maintenance", headers=net["headers"], json={**base, **change})
        assert resp.status_code == 422 and msg in resp.text, (change, resp.text)
    other = await signup(client, company="Provedor B", email="admin@b.com.br")
    # OLT de outro provedor: não existe para ele
    assert (await client.post("/api/maintenance", headers=other, json=base)).status_code == 404


async def test_outro_provedor_nao_ve_as_janelas(client, net):
    body = {"olt_id": net["olt_id"], "reason": "Firmware", "starts_at": iso(-1), "ends_at": iso(30)}
    w = (await client.post("/api/maintenance", headers=net["headers"], json=body)).json()
    other = await signup(client, company="Provedor B", email="admin@b.com.br")
    assert (await client.get("/api/maintenance", headers=other)).json() == []
    assert (await client.post(f"/api/maintenance/{w['id']}/end", headers=other)).status_code == 404
