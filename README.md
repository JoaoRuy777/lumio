# Lumio

Monitoramento de redes GPON (OLTs e ONUs) para provedores regionais. Este
repositório é o MVP descrito no TCC *Lumio: concepção e desenvolvimento de
uma startup de monitoramento automatizado de OLTs* (UNIMAR, 2026).

Estado atual: **sprint 3 (API, multi-tenant e cadastro de OLTs)** de seis.
Próximas: dashboard (4), notificações e relatórios (5), desempenho e
resultados (6). O plano completo e as decisões estão em
[`docs/plano.md`](docs/plano.md).

```
                         painel React ──▶ API FastAPI ──▶ Postgres (RLS por provedor)
                                              ▲                ▲
                              cadastro de OLTs │                │
simulador ──SNMP/traps──▶ coletor ──Redis Stream──▶ worker ─────┘
```

## O que já funciona

- **Simulador de OLTs** (`simulator/`): finge ser OLTs Huawei MA5800 via
  SNMPv2c, com o sinal das ONUs variando ao longo do tempo, e tem uma API HTTP
  para provocar falhas. Cada falha manda a trap correspondente.
- **Coletor** (`collector/`): consulta as OLTs (estado a cada 60 s, potência
  óptica a cada 5 min), recebe traps e devolve tudo num formato único, que não
  depende do fabricante. No compose, lê as OLTs **do cadastro na API** a cada
  30 s (`run-api`); o modo com YAML (`run`) continua para uso avulso.
  Publica tudo no Redis Stream `lumio:readings`.
- **Worker de alarmes** (`worker/`): consome o stream (consumer group, com
  confirmação só depois de gravar), guarda leituras e o estado das ONUs no
  Postgres e aplica as regras de alarme abaixo, com deduplicação e latência
  registrada em cada alarme.
- **API** (`api/`): FastAPI com login JWT, cadastro de provedor, CRUD de OLTs
  com limite do plano, "Testar conexão" (detecta fabricante e modelo) e
  descoberta automática de portas PON e ONUs ao salvar. Cada requisição roda
  com o tenant do usuário, e o **RLS do Postgres** esconde os dados dos outros.
- **Painel** (`web/`): React; login/cadastro e a tela de OLTs (lista com
  status da coleta e uso do plano, formulário com "Testar conexão").
- **Banco** (`db/`): Postgres 17 com Row-Level Security por tenant; migrações
  em SQL puro aplicadas pelo serviço `migrate`.
- **Testes**: 76 no backend (`tests/`) e 11 no painel (`web/src/__tests__`).

## Rodando com Docker

Só precisa do Docker instalado.

```bash
docker compose up --build
```

| Endereço | O quê |
| --- | --- |
| http://localhost:3000 | painel (crie a conta do provedor e cadastre as OLTs) |
| http://localhost:8000/api/docs | API da Lumio (Swagger) |
| http://localhost:8080/docs | API de cenários do simulador (provocar falhas) |

Sem `.env`, o compose usa senhas e chaves padrão que servem **só para
desenvolvimento**; para qualquer outro uso, `cp .env.example .env` e troque
tudo (o arquivo explica como gerar cada chave).

### Testando à mão

1. Abra http://localhost:3000 e clique em **Criar conta**.
2. **Nova OLT**: endereço `simulator`, porta `16101`, community `public`.
   Clique em **Testar conexão**: aparece *Huawei MA5800-X7 · 4 portas PON · 64 ONUs*.
3. **Salvar**: a descoberta grava as 4 PONs e as 64 ONUs. Cadastre a segunda
   (porta `16102`). O plano mostra **2 de 2 OLTs** e o botão de nova OLT trava.
4. Em até 30 s o coletor pega o cadastro e o status vira **Coletando**.
5. Provoque um rompimento de fibra:

   ```bash
   curl -X POST localhost:8080/scenarios -H 'content-type: application/json' \
     -d '{"type":"fiber_cut","olt":"olt-centro","pon":"0/1/2"}'
   ```

   A OLT da porta 16101 passa a mostrar 48/64 ONUs online e 17 alarmes
   (1 `pon_fiber_cut` crítico + 16 `onu_offline` ligados a ele). A tela se
   atualiza sozinha a cada 10 s. Para voltar ao normal: `{"type":"reset"}`.

O mesmo roteiro, automático: `./scripts/smoke.sh` (com a stack no ar; precisa
de `curl` e `node`).

## Regras de alarme

| Alarme | Severidade | Abre quando | Fecha quando |
| --- | --- | --- | --- |
| `onu_offline` | minor | trap de queda, ou o polling vê a ONU offline | trap de volta, ou o polling a vê online |
| `pon_fiber_cut` | critical | todas as ONUs da PON offline, ≥ 2 delas caindo em 5 s | ≥ 50 % da PON volta |
| `onu_rx_low` | warning | sinal < −27 dBm (trap ou leitura) | sinal ≥ −26 dBm (histerese) |
| `olt_cpu_high` | major | CPU ≥ 85 % (trap ou leitura) | CPU < 80 % |
| `olt_unreachable` | critical | OLT não responde ao SNMP | volta a responder |

- **Deduplicação**: no máximo um alarme aberto por tipo e objeto (OLT, PON ou
  ONU). Evento repetido só incrementa `occurrences`. Depois de encerrado, uma
  nova falha abre um alarme novo.
- **Rompimento de fibra**: as ONUs da PON ficam ligadas ao alarme de
  rompimento por `parent_id`, para o dashboard mostrar um problema só.
- Os limites ficam em `worker/lumio_worker/rules.py`.
- OLT fora do ar não manda trap; é percebida no próximo polling (até 60 s).
- Sinal baixo e CPU alta são encerrados pelo polling (o equipamento não manda
  trap de normalização): CPU em até 60 s, sinal em até 5 min.

## Testes

Sem Python instalado, tudo pelo Docker (sobe Postgres e Redis sozinho):

```bash
docker compose run --rm tests
```

Com Python 3.12+ local, suba só o banco e a fila e rode o pytest:

```bash
docker compose up -d postgres redis
export LUMIO_TEST_DATABASE_URL=postgresql://lumio:lumio-dev@localhost:5432/postgres
export LUMIO_TEST_REDIS_URL=redis://localhost:6379/15
pytest -v
```

Os testes do worker e da API criam um banco descartável (`lumio_test_xxxx`) e
o apagam no fim. Sem essas variáveis eles são pulados; no CI rodam sempre. A API
nos testes conecta com o papel `lumio_app`, o mesmo da produção, então os
testes de isolamento (`tests/api/test_isolation.py`) passam pelo RLS de verdade.

Painel (Node 22+):

```bash
cd web && npm ci && npm test        # Vitest + Testing Library
npm run dev                         # http://localhost:5173, usando a API em :8000
```

## API

Documentação interativa em http://localhost:8000/api/docs. Principais rotas:

| Rota | O quê |
| --- | --- |
| `POST /api/auth/signup` | cria o provedor (tenant) e o primeiro usuário, admin |
| `POST /api/auth/login` | devolve o token JWT (12 h) |
| `GET /api/auth/me` | usuário, provedor e uso do plano |
| `GET /api/olts` | OLTs com status da coleta, ONUs online e alarmes ativos |
| `POST /api/olts` | cadastra e já descobre PONs e ONUs (respeita o limite do plano) |
| `PATCH /api/olts/{id}`, `DELETE /api/olts/{id}` | altera (refaz a descoberta se o acesso SNMP mudar) ou remove |
| `POST /api/olts/test-connection` | testar conexão sem salvar |
| `POST /api/olts/{id}/test-connection`, `POST /api/olts/{id}/discover` | idem para OLT salva (usa a community guardada) |
| `GET /api/internal/collector/olts` | só para o coletor (header `X-Service-Token`) |

OLT de outro provedor responde **404** (não 403), para nem confirmar que ela existe.
Usuários `operator` só leem; alterar o cadastro exige `admin`.

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

`POST /tick` adianta o relógio da simulação, útil para ver uma degradação sem
esperar. Cada tick só aproxima o sinal *uma fração* do alvo, então chame várias
vezes (ex.: 10 ticks de `{"minutes": 1}`) em vez de um tick longo.

## Formato do que o coletor produz

```json
{"type": "onu_status",  "olt": "olt-centro", "ts": "...", "onus": [{"pon": "0/1/0", "onu": 0, "serial": "HWTC...", "online": true}]}
{"type": "onu_optical", "olt": "olt-centro", "ts": "...", "onus": [{"pon": "0/1/0", "onu": 0, "rx_dbm": -20.16, "tx_dbm": 2.2}]}
{"type": "olt_health",  "olt": "olt-centro", "ts": "...", "cpu": 21.0, "temperature": 42.0, "uptime_s": 1234.5}
{"type": "event",       "olt": "olt-centro", "ts": "...", "kind": "onu_offline", "source": "trap", "pon": "0/1/2", "onu": 0}
```

No modo `run-api`, todo registro leva também `olt_id` e `tenant_id` do cadastro;
é por eles que o worker grava cada leitura e alarme no provedor certo.

Com `REDIS_URL` definido, cada mensagem vai para o Redis Stream `lumio:readings`
(campo `data`, JSON) e o worker grava no Postgres. Mensagens que o worker não
consegue processar vão para `lumio:readings:dead`.

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
  registry.py         lista de OLTs vinda da API, sincronizada a cada 30 s
worker/lumio_worker/
  rules.py            limites, severidades e chaves de deduplicação (puro)
  processor.py        grava leituras/estado e abre ou encerra alarmes
  consumer.py         consumer group do Redis Stream, dead letter
api/lumio_api/
  db.py               pool e transação com app.tenant_id (RLS)
  security.py         argon2, JWT e cifra da community (Fernet)
  snmp.py             testar conexão e descoberta (drivers do coletor)
  routers/            auth, olts, internal (coletor)
web/src/
  pages/              login/cadastro e OLTs
  components/         formulário de OLT e componentes de tela
db/
  migrations/         esquema em SQL (tabelas, RLS, permissões, funções)
  migrate.py          aplica as migrações e cria os papéis do banco
tests/                ponta a ponta (sprint 1), worker/ (sprint 2) e api/ (sprint 3)
scripts/smoke.sh      teste de fumaça da stack no ar
docs/plano.md         plano das sprints e decisões
```

## Decisões

A lista completa está em [`docs/plano.md`](docs/plano.md#decisões).

### Sprint 3

- **A API nunca ignora o RLS**: conecta como `lumio_app` e define
  `app.tenant_id` em toda transação. Login, cadastro e a lista do coletor
  (que acontecem antes de saber o tenant, ou valem para todos) usam três
  funções `SECURITY DEFINER` pequenas no banco, em vez de um papel com BYPASSRLS na API.
- **Community SNMP cifrada** com Fernet (`LUMIO_SECRET_KEY`); a API nunca a
  devolve (só `has_community`). Trocar a chave invalida as communities salvas.
- **Coletor lê o cadastro pela API** a cada 30 s, com token de serviço, em vez
  de acessar o banco. Se a API cair, ele continua coletando a última lista.
- **Descoberta grava só o inventário** (PONs, ONUs, seriais); o estado
  online/offline é do worker. Assim uma ONU já offline no cadastro gera alarme
  na primeira coleta (havia um bug aqui, coberto por teste de regressão).
- **Token no `localStorage`** e API no mesmo endereço do painel (nginx faz o
  proxy de `/api`), sem CORS. Risco conhecido: XSS leria o token; o painel não
  renderiza HTML vindo de usuário. Cookie `httpOnly` fica para depois do MVP.
- **Sem react-router** por enquanto: são duas telas; entra na sprint 4.
- **Segredo JWT com no mínimo 32 caracteres**: a API não sobe com menos.
- **Plano**: limite de OLTs por provedor em `tenants.olt_limit` (padrão 2);
  ainda não há tela para mudar de plano.

### Sprint 2

- **Postgres puro, sem TimescaleDB**: o volume do MVP cabe numa tabela
  indexada; o worker apaga leituras com mais de `LUMIO_RETENTION_DAYS` (90).
- **Migrações em SQL puro** com um script curto (`db/migrate.py`), sem Alembic/ORM.
- **Papéis do banco**: o worker usa `lumio_system` (BYPASSRLS, processa todos
  os tenants); a API da sprint 3 vai usar `lumio_app`, sujeito ao RLS. Um teste
  já comprova que `lumio_app` não enxerga alarmes de outro tenant.
- **Tenant `demo`** (só no modo YAML do coletor): registro sem `olt_id` cai no
  tenant `demo`, criado na hora. No compose (modo `run-api`) ele não é usado.
- **Entrega "pelo menos uma vez"**: o XACK só acontece depois do commit;
  reprocessar é seguro graças à deduplicação. Falha de infraestrutura (banco ou
  Redis fora) não confirma a mensagem; erro de dado vai para o dead letter.
- **Latência**: `latency_ms` = gravação do alarme − recepção do evento no
  coletor (mesmo relógio do host). A latência desde o simulador é medida no
  teste `tests/worker/test_pipeline.py`.

## Pontos a confirmar com uma OLT real

- As OIDs de leitura seguem a HUAWEI-XPON-MIB, mas convém comparar com um
  `snmpwalk` de uma MA5800 de um provedor da região.
- As OIDs de **trap** são de laboratório (ramo `...2011.6.128.1.1.2.500`, que
  não existe na MIB). Trocar pelas oficiais em `collector/lumio_collector/vendors/huawei.py`
  e `simulator/lumio_sim/profiles/huawei.py` quando der para capturar traps reais.
- No simulador, as OLTs compartilham o mesmo IP e se diferenciam pela porta
  SNMP; o coletor separa as traps pelo `sysName`.
