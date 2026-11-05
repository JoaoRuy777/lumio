"""Regras de escalonamento (API) e a marca no alarme e na linha do tempo."""

from lumio_worker.notify import Notifier, SmtpConfig
from tests.worker.test_notify import KEY

from .conftest import needs_db, signup
from .test_dashboard import get, net  # noqa: F401

pytestmark = needs_db


async def channel(client, headers, name="Supervisor"):
    resp = await client.post("/api/notification-channels", headers=headers,
                             json={"name": name, "type": "email", "target": "sup@a.com.br", "min_severity": "critical"})
    assert resp.status_code == 201, resp.text
    return resp.json()["channel"]["id"]


async def test_regras_e_escalonamento_aparece_no_alarme(client, net, pool):
    h = net["headers"]
    ch = await channel(client, h)
    resp = await client.post("/api/escalation-rules", headers=h,
                             json={"name": "Supervisor", "after_minutes": 10, "channel_id": ch})
    assert resp.status_code == 201, resp.text
    rule = resp.json()
    assert (rule["min_severity"], rule["channel_name"], rule["enabled"], rule["escalations_30d"]) == \
        ("critical", "Supervisor", True, 0)

    off = (await client.patch(f"/api/escalation-rules/{rule['id']}", headers=h,
                              json={"enabled": False, "after_minutes": 20})).json()
    assert (off["enabled"], off["after_minutes"]) == (False, 20)
    await client.patch(f"/api/escalation-rules/{rule['id']}", headers=h, json={"enabled": True})

    # rompimento sem ninguém assumir há 25 min: o notificador escala
    await net["fiber_cut"]()
    await pool.execute("UPDATE alarms SET created_at = now() - interval '25 minutes'")
    assert await Notifier(pool, KEY, SmtpConfig(host=None)).escalate() == 1

    [cut] = (await get(client, net, "/alarms"))["items"]
    assert cut["escalated_at"] is not None
    timeline = (await client.get(f"/api/alarms/{cut['id']}/timeline", headers=h)).json()
    [esc] = [t for t in timeline if t["kind"] == "escalated"]
    assert esc["target"] == "Supervisor" and "20 min" in esc["body"]
    assert (await get(client, net, "/escalation-rules"))[0]["escalations_30d"] == 1

    assert (await client.delete(f"/api/escalation-rules/{rule['id']}", headers=h)).status_code == 204
    assert await get(client, net, "/escalation-rules") == []


async def test_validacoes_permissao_e_isolamento(client, net):
    h = net["headers"]
    ch = await channel(client, h)
    bad = await client.post("/api/escalation-rules", headers=h, json={"name": "X1", "after_minutes": 0, "channel_id": ch})
    assert bad.status_code == 422

    other = await signup(client, company="Provedor B", email="admin@b.com.br")
    resp = await client.post("/api/escalation-rules", headers=other,
                             json={"name": "Sup", "after_minutes": 5, "channel_id": ch})
    assert resp.status_code == 422 and "canal" in resp.text           # canal de outro provedor
    rule = (await client.post("/api/escalation-rules", headers=h,
                              json={"name": "Sup", "after_minutes": 5, "channel_id": ch})).json()
    assert (await client.get("/api/escalation-rules", headers=other)).json() == []
    assert (await client.delete(f"/api/escalation-rules/{rule['id']}", headers=other)).status_code == 404

    # operador vê as regras, mas não altera
    created = await client.post("/api/users", headers=h, json={"name": "Op", "email": "op@a.com.br",
                                                               "password": "senha-forte-123", "role": "operator"})
    assert created.status_code == 201, created.text
    login = await client.post("/api/auth/login", json={"email": "op@a.com.br", "password": "senha-forte-123"})
    oh = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/api/escalation-rules", headers=oh)).status_code == 200
    denied = await client.post("/api/escalation-rules", headers=oh, json={"name": "Sup", "after_minutes": 5, "channel_id": ch})
    assert denied.status_code == 403
