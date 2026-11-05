"""Assistente de IA: laço de ferramentas, anonimização (LGPD), limites e falhas do provedor.

O Gemini é simulado (httpx.MockTransport): os testes leem exatamente o que
sairia para o Google.
"""

import dataclasses
import json

import httpx
import pytest

from .conftest import needs_db, signup
from .test_dashboard import get, net  # noqa: F401

pytestmark = needs_db


class FakeGemini:
    """Responde em sequência; guarda cada pedido recebido."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append({"url": str(request.url), "key": request.headers.get("x-goog-api-key"),
                              "body": json.loads(request.content)})
        status, body = self.replies.pop(0)
        return httpx.Response(status, json=body)

    @property
    def sent(self) -> str:
        return json.dumps([r["body"] for r in self.requests], ensure_ascii=False)


def call(name, **args):
    return 200, {"candidates": [{"content": {"role": "model", "parts": [{"functionCall": {"name": name, "args": args}}]}}]}


def text(t):
    return 200, {"candidates": [{"content": {"role": "model", "parts": [{"text": t}]}, "finishReason": "STOP"}]}


@pytest.fixture
def ai(app):
    def install(*replies, key="chave-teste"):
        fake = FakeGemini(*replies)
        app.state.settings = dataclasses.replace(app.state.settings, gemini_api_key=key)
        app.state.ai_transport = httpx.MockTransport(fake.handler)
        return fake
    return install


async def with_customers(client, net):
    onus = (await get(client, net, "/onus", limit=200))["items"]
    lines = [f"{o['serial']};Cliente Secreto {o['pon']} {o['onu_index']};(14) 99999-{o['onu_index']:04d};Rua Sigilosa {o['onu_index']}"
             for o in onus]
    await client.post("/api/customers/import", headers=net["headers"],
                      json={"csv": "serial;nome;telefone;endereco\n" + "\n".join(lines)})
    return onus


async def ask(client, headers, question, mapping=None, history=None, alarm_id=None):
    messages = (history or []) + [{"role": "user", "text": question}]
    return await client.post("/api/assistant/chat", headers=headers,
                             json={"messages": messages, "mapping": mapping or {}, "alarm_id": alarm_id})


async def test_consulta_os_dados_reais_sem_mandar_dado_pessoal(client, net, ai):
    await with_customers(client, net)
    await net["fiber_cut"]()
    [cut] = (await get(client, net, "/alarms"))["items"]
    fake = ai(call("listar_alarmes", severidades=["critico"]),
              call("detalhar_chamado", alarme_id=cut["id"]),
              text("Rompimento na olt-2 PON 0/1/1: 8 clientes, entre eles [CLIENTE_1]. Ninguém assumiu ainda."))
    resp = await ask(client, net["headers"], "o que está crítico agora?")
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["tools"] == ["listar_alarmes", "detalhar_chamado"]
    # na tela, o nome real; para o Google, só o marcador
    assert "Cliente Secreto 0/1/1" in out["reply"] and "[CLIENTE_1]" not in out["reply"]
    assert out["mapping"]["[CLIENTE_1]"].startswith("Cliente Secreto 0/1/1")
    for secret in ("Cliente Secreto", "99999-", "Rua Sigilosa"):
        assert secret not in fake.sent, secret
    # o modelo recebeu os dados de verdade: o rompimento e as ONUs, com marcadores
    tool_results = fake.requests[2]["body"]["contents"]
    detail = tool_results[-1]["parts"][0]["functionResponse"]["response"]
    assert detail["tipo"] == "Rompimento de fibra" and detail["onus_afetadas"] == 8
    assert all(o["cliente"].startswith("[CLIENTE_") for o in detail["onus"])
    assert fake.requests[0]["key"] == "chave-teste" and "gemini-3.5-flash" in fake.requests[0]["url"]

    # a pergunta seguinte usa o nome real: volta a virar marcador antes de sair
    name = out["mapping"]["[CLIENTE_1]"]
    fake2 = ai(text("Sem dados novos de [CLIENTE_1]."))
    history = [{"role": "user", "text": "o que está crítico agora?"}, {"role": "model", "text": out["reply"]}]
    resp = await ask(client, net["headers"], f"e o {name}?", mapping=out["mapping"], history=history)
    assert resp.json()["reply"] == f"Sem dados novos de {name}."
    assert "Cliente Secreto" not in fake2.sent and "[CLIENTE_1]" in fake2.sent

    # a auditoria registra que perguntou e o que foi consultado, nunca a pergunta
    log = (await client.get("/api/audit-log", headers=net["headers"], params={"category": "assistant"})).json()["items"]
    assert log[-1]["details"]["tools"] == ["listar_alarmes", "detalhar_chamado"]
    assert "crítico" not in json.dumps(log)


async def test_busca_de_cliente_pelo_marcador(client, net, ai):
    onus = await with_customers(client, net)
    serial = onus[0]["serial"]
    fake = ai(call("buscar_clientes", termo="Cliente Secreto 0/1/0 0"),
              call("sinal_onu", serial=serial), text("O sinal de [CLIENTE_1] está normal."))
    resp = await ask(client, net["headers"], "como está o sinal do cliente?")
    assert resp.status_code == 200, resp.text
    found = fake.requests[1]["body"]["contents"][-1]["parts"][0]["functionResponse"]["response"]["clientes"]
    assert found and found[0]["serial_onu"] == serial and found[0]["telefone"].startswith("[TELEFONE_")
    signal = fake.requests[2]["body"]["contents"][-1]["parts"][0]["functionResponse"]["response"]
    assert signal["serial"] == serial and signal["online"] is True


async def test_outro_provedor_nao_aparece_nas_ferramentas(client, net, ai):
    await with_customers(client, net)
    await net["fiber_cut"]()
    other = await signup(client, company="Provedor B", email="admin@b.com.br")
    fake = ai(call("listar_alarmes"), call("buscar_clientes", termo="Cliente"), text("Nada."))
    assert (await ask(client, other, "tem alarme?")).status_code == 200
    assert fake.requests[1]["body"]["contents"][-1]["parts"][0]["functionResponse"]["response"]["total"] == 0
    assert fake.requests[2]["body"]["contents"][-1]["parts"][0]["functionResponse"]["response"]["clientes"] == []


async def test_modelo_sobrecarregado_tenta_o_proximo_e_cota_esgotada_avisa(client, net, ai):
    fake = ai((503, {"error": {"message": "high demand"}}), text("ok"))
    resp = await ask(client, net["headers"], "oi")
    assert resp.status_code == 200 and resp.json()["model"] == "gemini-3.1-flash-lite"
    assert "gemini-3.5-flash" in fake.requests[0]["url"] and "gemini-3.1-flash-lite" in fake.requests[1]["url"]

    # cota esgotada num modelo: tenta o próximo (cada um tem a sua); em todos, avisa
    fake = ai((429, {}), text("ok"))
    assert (await ask(client, net["headers"], "oi")).status_code == 200 and len(fake.requests) == 2
    ai((429, {}), (429, {}), (503, {}))
    resp = await ask(client, net["headers"], "oi")
    assert resp.status_code == 429 and "limite gratuito" in resp.json()["detail"]

    ai(*[(503, {})] * 3)
    resp = await ask(client, net["headers"], "oi")
    assert resp.status_code == 503 and "sobrecarregado" in resp.json()["detail"]


async def test_sem_chave_fica_desligado_e_limite_diario(client, net, ai, pool):
    st = (await client.get("/api/assistant/status", headers=net["headers"])).json()
    assert st["configured"] is False
    assert (await ask(client, net["headers"], "oi")).status_code == 503

    ai(text("ok"))
    st = (await client.get("/api/assistant/status", headers=net["headers"])).json()
    assert st["configured"] is True and st["remaining_today"] == st["daily_limit"]
    # simula o limite gasto hoje
    uid = await pool.fetchval("SELECT id FROM users WHERE email = 'admin@a.com.br'")
    tid = await pool.fetchval("SELECT tenant_id FROM users WHERE id = $1", uid)
    await pool.execute("INSERT INTO audit_log (tenant_id, actor_id, action) SELECT $1, $2, 'assistant.ask' "
                       "FROM generate_series(1, $3)", tid, uid, st["daily_limit"])
    resp = await ask(client, net["headers"], "oi")
    assert resp.status_code == 429 and "por dia" in resp.json()["detail"]
