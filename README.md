# Lumio

Monitoramento de redes GPON (OLTs e ONUs) para provedores regionais. Este
repositório é o MVP descrito no TCC *Lumio: concepção e desenvolvimento de
uma startup de monitoramento automatizado de OLTs* (UNIMAR, 2026).

Estado atual: **sprint 1 (simulador + coletor)** de seis. Próximas: banco e
worker, API com cadastro de OLTs, alarmes, dashboard operacional, ZTE e medições.

## O que já funciona

- **Simulador de OLTs** (`simulator/`): finge ser OLTs Huawei MA5800 via
  SNMPv2c, com o sinal das ONUs variando ao longo do tempo, e tem uma API HTTP
  para provocar falhas. Cada falha manda a trap correspondente.
- **Coletor** (`collector/`): consulta as OLTs (estado a cada 60 s, potência
  óptica a cada 5 min), recebe traps e devolve tudo num formato único, que não
  depende do fabricante. Também tem o `probe`, que é a base do botão
  "Testar conexão" da tela de cadastro.
- **Testes** (`tests/`): simulador e coletor conversando por UDP de verdade,
  incluindo a medição de latência trap → evento.

## Rodando com Docker

Só precisa do Docker instalado.

```bash
docker compose up --build
```

- API do simulador, com a lista de cenários: http://localhost:8080/docs
- Leituras do coletor (JSON, uma por linha): `docker compose logs -f collector`

Provocando um rompimento de fibra:

```bash
curl -X POST localhost:8080/scenarios -H 'content-type: application/json' \
  -d '{"type":"fiber_cut","olt":"olt-centro","pon":"0/1/2"}'
```

Em menos de um segundo aparecem 16 eventos `onu_offline` no log do coletor.

## Rodando sem Docker (Python 3.12+)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# terminal 1: simulador (2 OLTs nas portas UDP 16101 e 16102)
cd simulator && python -m lumio_sim --trap-target 127.0.0.1:1162

# terminal 2: coletor
cd collector && python -m lumio_collector run --config config/coletor-exemplo.yaml

# testar conexão com uma OLT
cd collector && python -m lumio_collector probe 127.0.0.1:16101

# testes
pytest -v
```

Com o `snmpwalk` instalado (pacote `snmp` no Linux, `net-snmp` no macOS), dá
para ver a OLT simulada como se fosse real:

```bash
snmpwalk -v2c -c public 127.0.0.1:16101 1.3.6.1.4.1.2011.6.128.1.1.2.51.1.4
```

## Cenários do simulador

| `type` | Parâmetros | O que acontece |
| --- | --- | --- |
| `onu_down` | `olt`, `pon`, `onu`, `cause` | ONU fica offline e envia trap |
| `onu_up` | `olt`, `pon`, `onu` | ONU volta |
| `degrade` | `olt`, `pon`, `onu`, `rate_db_per_min`, `target_dbm` | Sinal cai aos poucos; trap ao passar de -27 dBm |
| `fiber_cut` | `olt`, `pon` | Todas as ONUs da porta caem juntas |
| `olt_down` | `olt` | OLT para de responder SNMP (sem trap) |
| `overload` | `olt`, `cpu` | CPU alta e trap |
| `reset` | `olt` (opcional) | Volta tudo ao normal |

`POST /tick` com `{"minutes": 10}` adianta o relógio da simulação, útil para
ver uma degradação sem esperar.

## Formato do que o coletor produz

```json
{"type": "onu_status",  "olt": "olt-centro", "ts": "...", "onus": [{"pon": "0/1/0", "onu": 0, "serial": "HWTC...", "online": true}]}
{"type": "onu_optical", "olt": "olt-centro", "ts": "...", "onus": [{"pon": "0/1/0", "onu": 0, "rx_dbm": -20.16, "tx_dbm": 2.2}]}
{"type": "olt_health",  "olt": "olt-centro", "ts": "...", "cpu": 21.0, "temperature": 42.0, "uptime_s": 1234.5}
{"type": "event",       "olt": "olt-centro", "ts": "...", "kind": "onu_offline", "source": "trap", "pon": "0/1/2", "onu": 0}
```

Na sprint 2 essas mensagens vão para um Redis Stream (basta definir
`REDIS_URL`), e o worker grava no TimescaleDB.

## Estrutura

```
simulator/lumio_sim/
  model.py            rede em memória, relógio e cenários
  profiles/huawei.py  modelo -> OIDs da Huawei
  snmp_agent.py       agente SNMPv2c e envio de traps
  api.py              API HTTP de cenários
collector/lumio_collector/
  snmp.py             cliente SNMP (GET, GETBULK walk)
  vendors/            um driver por fabricante, todos no mesmo formato
  poller.py           agendador de coleta e "testar conexão"
  traps.py            receptor de traps
  sink.py             saída: stdout, memória (testes) ou Redis
tests/                testes de ponta a ponta
```

## Pontos a confirmar com uma OLT real

- As OIDs de leitura seguem a HUAWEI-XPON-MIB, mas convém comparar com um
  `snmpwalk` de uma MA5800 de um provedor da região.
- As OIDs de **trap** são de laboratório (ramo `...2011.6.128.1.1.2.500`, que
  não existe na MIB). Trocar pelas oficiais em `collector/lumio_collector/vendors/huawei.py`
  e `simulator/lumio_sim/profiles/huawei.py` quando der para capturar traps reais.
- No simulador, as OLTs compartilham o mesmo IP e se diferenciam pela porta
  SNMP; o coletor separa as traps pelo `sysName`.
