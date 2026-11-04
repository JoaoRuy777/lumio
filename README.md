# Lumio

Monitoramento de redes GPON (OLTs e ONUs) para provedores regionais. Este
repositório é o MVP descrito no TCC *Lumio: concepção e desenvolvimento de
uma startup de monitoramento automatizado de OLTs* (UNIMAR, 2026).

Estado atual: **MVP completo (sprints 1 a 6)**. O plano e as decisões estão em
[`docs/plano.md`](docs/plano.md), os testes de desempenho em
[`docs/resultados.md`](docs/resultados.md) e o passo a passo para colocar no
ar em [`docs/deploy.md`](docs/deploy.md).

```
                     painel React ◀─SSE─ API FastAPI ──▶ Postgres (RLS por provedor)
                                             ▲    ▲              ▲
                          cadastro de OLTs   │    └─ Redis Pub/Sub ◀─┐
simulador ──SNMP/traps──▶ coletor ──Redis Stream──▶ worker ──────────┘
                                                       │ fila no Postgres
                                                       ▼
                                          notificador ──▶ e-mail (SMTP) / webhook
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
  Postgres, aplica as regras de alarme abaixo (deduplicação e latência
  registrada) e, depois do commit, avisa o painel por Redis Pub/Sub. Na mesma
  transação do alarme, põe as notificações na fila.
- **Notificador** (`worker/`, `python -m lumio_worker notify`): envia a fila
  por **e-mail** (SMTP) e **webhook** (POST JSON assinado com HMAC-SHA256), com
  novas tentativas e espera crescente. Um rompimento de fibra vira **um** aviso,
  não 17.
- **API** (`api/`): FastAPI com login JWT, cadastro de provedor, CRUD de OLTs
  com limite do plano, "Testar conexão", descoberta automática de PONs e ONUs,
  rotas do painel (visão geral, PONs, ONUs, histórico de potência, alarmes com
  reconhecimento), **avisos em tempo real por SSE**, canais de notificação e
  **relatórios** de disponibilidade e de alarmes (JSON, CSV e PDF). Cada requisição roda com
  o tenant do usuário, e o **RLS do Postgres** esconde os dados dos outros.
- **Painel** (`web/`): React; visão geral, alarmes (abertos e histórico,
  rompimento de fibra agrupando as ONUs, reconhecer), OLTs (cadastro e detalhe
  por PON), ONUs (filtros e gráfico de potência). Atualiza em tempo real: um
  alarme novo aparece em ~1 s, sem recarregar. Se o tempo real cair, as telas
  continuam atualizando a cada 30 s e o topo mostra "Sem tempo real".
  Também: **Relatórios** (período, números, baixar CSV/PDF) e **Notificações**
  (canais, mensagem de teste, histórico de entregas) e **Usuários** (o administrador
  cria acessos para a equipe, como administrador ou operador).
- **Atendimento de chamados (NOC)**: o operador assume (ou transfere) o alarme,
  acompanha numa página própria com cronômetros (espera e tempo de atendimento),
  anota o que fez numa linha do tempo e encerra com a causa. Aba "Meus
  atendimentos" e relatório da equipe com TME, TMA, chamados por operador e
  causas (tela, CSV e PDF).
- **Banco** (`db/`): Postgres 17 com Row-Level Security por tenant; migrações
  em SQL puro aplicadas pelo serviço `migrate`.
- **Desempenho** (`scripts/bench/`): teste de carga com o simulador em vários
  tamanhos de rede, medindo latência de alarme, vazão do worker, duração da
  coleta, CPU e memória; gera [`docs/resultados.md`](docs/resultados.md).
- **Produção** (`docker-compose.prod.yml`, `deploy/`): HTTPS automático
  (Caddy), só as portas 80/443 expostas, segredos obrigatórios no `.env`,
  backup diário do banco.
- **Testes**: 149 no backend (`tests/`), 38 no painel (`web/src/__tests__`) e
  1 de ponta a ponta no navegador (`web/e2e`, Playwright).

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
| http://localhost:8025 | Mailpit: caixa de entrada falsa com os e-mails de alerta |

Sem `.env`, o compose usa senhas e chaves padrão que servem **só para
desenvolvimento**; para qualquer outro uso, `cp .env.example .env` e troque
tudo (o arquivo explica como gerar cada chave).

### Testando à mão

1. Abra http://localhost:3000 e clique em **Criar conta**.
2. **Cadastrar OLT** → **Nova OLT**: endereço `simulator`, porta `16101`,
   community `public`. **Testar conexão** mostra *Huawei MA5800-X7 · 4 portas
   PON · 64 ONUs*. **Salvar** descobre as PONs e ONUs. Cadastre também a porta
   `16102`; o plano mostra **2 de 2 OLTs**.
3. Em até 30 s o coletor pega o cadastro e o status vira **Coletando**.
4. Abra **Alarmes** (o topo mostra **Ao vivo**) e provoque um rompimento de fibra:

   ```bash
   curl -X POST localhost:8080/scenarios -H 'content-type: application/json' \
     -d '{"type":"fiber_cut","olt":"olt-centro","pon":"0/1/2"}'
   ```

   Em cerca de 1 s, sem recarregar, aparece **Rompimento de fibra · Crítico**
   marcado como *novo*, com "Ver 16 ONUs afetadas". **Reconhecer** marca quem
   está cuidando. A **Visão geral** mostra 48/64 ONUs online na OLT.
5. Sinal degradando aos poucos (veja na tela da ONU 5, em **ONUs**):

   ```bash
   curl -X POST localhost:8080/scenarios -H 'content-type: application/json' \
     -d '{"type":"degrade","olt":"olt-zona-norte","pon":"0/1/0","onu":5,"rate_db_per_min":3,"target_dbm":-30}'
   for i in $(seq 1 12); do curl -s -X POST localhost:8080/tick -H 'content-type: application/json' -d '{"minutes":1}' > /dev/null; done
   ```

6. Para voltar ao normal: `{"type":"reset"}`; os alarmes saem de "Abertos"
   sozinhos e vão para o **Histórico** com a duração.
7. **Notificações** → **Novo canal** (e-mail, qualquer endereço). **Enviar
   teste** e veja em http://localhost:8025. Repita a falha do passo 4: chega
   *um* e-mail "[Lumio] CRÍTICO: Rompimento de fibra", e outro "NORMALIZADO"
   depois do reset.
8. **Relatórios**: disponibilidade por OLT, piores ONUs, alarmes e MTTR do
   período; **Baixar CSV** (abre no Excel em português) ou **PDF**.

Automático, com a stack no ar:

```bash
./scripts/smoke.sh                       # API: cadastro -> coleta -> falha -> alarme (curl + node)
cd web && npx playwright install chromium && npx playwright test   # o mesmo no navegador
```

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

Ponta a ponta no navegador (com `docker compose up` no ar): `cd web && npx
playwright test`. O teste cria uma conta pela tela, cadastra a OLT, provoca um
rompimento de fibra e exige que o alarme apareça **em até 5 s sem recarregar**
(o polling de reserva é de 30 s, então só o tempo real passa). No CI ele roda
depois do `smoke.sh`.

## Desempenho

```bash
docker compose down                 # o teste usa as mesmas portas
./scripts/bench/bench.sh            # uns 20 min; LEVELS="2 10" para um teste curto
```

Roda num projeto compose separado (`lumio-bench`), com banco próprio apagado
no fim, e gera `docs/resultados.md` com a metodologia, tabelas e gráficos.

## Colocando no ar

Resumo (detalhes em [`docs/deploy.md`](docs/deploy.md)): uma VPS Linux com
Docker, um domínio apontando para ela e uma conta de SMTP.

```bash
git clone https://github.com/JoaoRuy777/lumio.git /opt/lumio && cd /opt/lumio
./deploy/gen-env.sh lumio.seudominio.com.br voce@seudominio.com.br   # gera o .env
nano .env                                                             # SMTP_*
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile demo up -d --build
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
| `GET /api/overview` | números da visão geral e alarmes abertos mais graves |
| `GET /api/olts/{id}/pons` | PONs da OLT: ONUs online, RX médio e pior, alarmes |
| `GET /api/onus` | ONUs com filtros: `olt_id`, `pon_id`, `status`, `rx_below`, `q` (serial), paginação |
| `GET /api/onus/{id}/readings?hours=24` | histórico de potência (acima de ~300 pontos, média por intervalo) |
| `GET /api/alarms` | alarmes: `status` (`open`, `cleared`, `all`...), `severity`, `olt_id`, `onu_id`, `parent_id`, `from`/`to` |
| `POST /api/alarms/{id}/ack` | reconhecer (vale também para as ONUs de um rompimento) |
| `GET /api/events` | avisos em tempo real (SSE) do provedor logado |
| `/api/notification-channels` | canais (CRUD; criar e remover exigem admin); `POST …/{id}/test`, `GET …/{id}/deliveries`, `POST …/{id}/rotate-secret` |
| `GET /api/reports/availability` | disponibilidade por OLT e piores ONUs; `from`, `to` (com fuso), `format=json|csv|pdf` |
| `GET /api/reports/alarms` | alarmes do período, por tipo e MTTR; mesmos parâmetros |
| `GET /api/internal/collector/olts` | só para o coletor (header `X-Service-Token`) |

OLT, ONU ou alarme de outro provedor responde **404** (não 403), para nem
confirmar que existe. Usuários `operator` leem e reconhecem alarmes; alterar o
cadastro exige `admin`.

Por padrão, `/api/alarms` lista só os alarmes "de cima": as ONUs de um
rompimento de fibra ficam dentro dele (`children`) e saem com `parent_id`.

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
  notify.py           notificador: e-mail, webhook assinado, retry, proteção SSRF
api/lumio_api/
  db.py               pool e transação com app.tenant_id (RLS)
  security.py         argon2, JWT e cifra da community (Fernet)
  snmp.py             testar conexão e descoberta (drivers do coletor)
  reports.py          cálculo da disponibilidade e geração de CSV/PDF
  routers/            auth, olts, overview, network, alarms, events (SSE), channels, reports, internal
web/src/
  pages/              visão geral, alarmes, OLTs, ONUs, login/cadastro
  components/         tabela de alarmes, gráfico de potência, formulário de OLT
  live.tsx            tempo real (SSE por fetch, reconexão, recarrega as telas)
web/e2e/              teste no navegador (Playwright)
db/
  migrations/         esquema em SQL (tabelas, RLS, permissões, funções)
  migrate.py          aplica as migrações e cria os papéis do banco
tests/                ponta a ponta (sprint 1), worker/ (sprint 2) e api/ (sprints 3 a 5)
scripts/smoke.sh      teste de fumaça da stack no ar
scripts/bench/        teste de carga e gerador do relatório de resultados
deploy/               Caddyfile, gerador do .env e backup (produção)
docker-compose.prod.yml  ajustes de produção (HTTPS, sem portas internas, restart)
docs/plano.md         plano das sprints e decisões
docs/resultados.md    resultados dos testes de desempenho
docs/deploy.md        como colocar no ar
```

## Decisões

A lista completa está em [`docs/plano.md`](docs/plano.md#decisões).

### Sprint 6

- **Teste de carga com o próprio simulador**, num projeto compose separado e
  descartável: mede do pedido de falha ao alarme gravado (relógio do host,
  comum a todos os contêineres), mais uma rajada direto na fila para medir o
  worker sozinho. Metodologia completa em `docs/resultados.md`.
- **Worker em lote**: o teste mostrou que o worker fazia uma consulta por ONU.
  Agora grava estado e potência de uma OLT inteira com uma consulta
  (`UPDATE ... FROM unnest`); o comparativo antes/depois está nos resultados.
- **Produção com Caddy**: certificado HTTPS automático, sem configurar nginx
  nem certbot; banco, Redis e API ficam só na rede interna do Docker.
- **Segredos obrigatórios em produção**: o `docker-compose.prod.yml` não sobe
  se faltar alguma senha no `.env` (nada de valor padrão de desenvolvimento);
  `deploy/gen-env.sh` gera todas aleatórias.
- **OLTs reais por VPN (WireGuard)**: o SNMP das OLTs nunca fica exposto na
  internet.

### Sprint 5

- **Fila de notificações no Postgres (outbox)**: o worker grava a entrega na
  mesma transação do alarme; um processo separado (`notifier`) envia. Nada se
  perde se o SMTP cair, e reprocessar o stream não duplica e-mail (índice único
  por canal + alarme + evento).
- **Sem spam**: "ONU offline" espera 15 s antes de sair; se virar parte de um
  rompimento, o aviso dela é cancelado e sai só o do rompimento. Alarme que
  normaliza antes de o aviso sair não gera aviso nenhum.
- **Retry**: até 6 tentativas, esperando 30 s, 1, 2, 4, 8 min; depois fica
  "Falhou" com o erro visível na tela de Notificações.
- **Webhook assinado** (`X-Lumio-Signature: sha256=HMAC(corpo)`), segredo
  gerado pela Lumio, mostrado uma vez e guardado cifrado.
- **Proteção contra SSRF**: webhook para IP interno é recusado
  (`LUMIO_WEBHOOK_ALLOW_PRIVATE=false` em produção).
- **Disponibilidade calculada pelos alarmes**: soma dos períodos de "ONU
  offline" dentro do intervalo; tempo com a OLT inacessível aparece separado
  (não dá para saber o estado das ONUs). Valores **truncados**: com qualquer
  falha, nunca aparece 100 %.
- **CSV para o Excel brasileiro**: separador `;`, vírgula decimal, UTF-8 com
  BOM, horários de Brasília. PDF com reportlab (sem dependências de sistema).
- **Mailpit** no compose para ver os e-mails em desenvolvimento; em produção,
  qualquer SMTP (variáveis `SMTP_*` no `.env`).

### Sprint 4

- **Tempo real por SSE + Redis Pub/Sub**: o worker publica no canal do
  provedor (`lumio:events:<tenant>`) **depois do commit**; cada conexão SSE
  assina só o canal do próprio tenant. O aviso só diz "algo mudou"; o painel
  recarrega pelas rotas normais, que passam pelo RLS. Assim o isolamento não
  depende do canal.
- **SSE por `fetch`, não `EventSource`**: o token vai no cabeçalho
  `Authorization`, não na URL (onde vazaria em logs do nginx).
- **Polling de reserva de 30 s**: se o SSE cair, as telas seguem atualizando
  e o topo mostra "Sem tempo real"; a reconexão espera 1, 2, 4… até 30 s.
- **Reconhecer ≠ encerrar**: o alarme reconhecido continua aberto até a falha
  passar; reconhecer um rompimento reconhece as ONUs dele. Operador pode reconhecer.
- **Rompimento agrupa as ONUs**: listas e contadores mostram 1 alarme
  crítico, não 17; as ONUs aparecem ao abrir o rompimento.
- **Gráfico**: uma série (sem legenda), linha de referência no limite de
  −27 dBm, tooltip e alternativa em tabela; acima de ~300 pontos, a API devolve
  médias por intervalo. Cores de severidade são as de status, sempre com forma
  e texto (não só cor). O painel ainda não tem modo escuro.
- **Recharts carregado só na tela da ONU** (código dividido): a tela inicial
  baixa 337 kB em vez de 710 kB.

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
