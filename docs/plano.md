# Plano de implementação (sprints 2 a 6)

Lumio: SaaS multi-tenant de monitoramento de OLTs. A sprint 1 (simulador +
coletor) está pronta. Este documento registra o plano combinado para as
próximas sprints e as decisões de arquitetura.

## Arquitetura alvo

```
simulador ──SNMP/traps──▶ coletor ──Redis Stream──▶ worker ──▶ Postgres (RLS)
                                                                   ▲
                                         dashboard React ◀── API FastAPI
```

Serviços no `docker-compose.yml`: simulator, collector, redis, postgres,
migrate (one-shot), worker, api (:8000), web (:3000).

## Stack

| Camada | Escolha |
|---|---|
| Backend | Python 3.12, FastAPI, asyncpg, Pydantic 2 |
| Auth | JWT (PyJWT), senha com argon2 |
| Fila | Redis 7: Streams com consumer group; Pub/Sub para tempo real |
| Banco | Postgres 17 com Row-Level Security |
| Front | Node 22, React 19, Vite, TypeScript, TanStack Query, Recharts, Tailwind |
| Testes | pytest + pytest-asyncio; Vitest + Testing Library |
| Infra | docker compose, GitHub Actions |

## Modelo de dados

Toda tabela, exceto `tenants`, tem `tenant_id` e política RLS
`tenant_id = current_setting('app.tenant_id')::uuid`.

- `tenants`: name, slug, `olt_limit`
- `users` (sprint 3): email, `password_hash`, role
- `olts`: name, host, `snmp_port`, community (cifrada a partir da sprint 3),
  vendor, model, `sys_name`, intervalos, `last_poll_at`, `last_poll_ok`, `last_error`
- `pon_ports`, `onus` (estado atual, potência mais recente)
- `optical_readings`, `olt_health_readings` (séries temporais)
- `alarms`: kind, severity, `dedup_key`, status, `parent_id`, `occurrences`,
  `first_seen_at`, `last_seen_at`, `cleared_at`, `event_ts`, `created_at`,
  `latency_ms`, `details`
- `notification_channels`, `notifications` (sprint 5)

## Endpoints principais (`/api`)

- `POST /auth/signup`, `POST /auth/login`, `GET /auth/me`
- CRUD `/olts`, `POST /olts/test-connection`, `POST /olts/{id}/discover`
- `GET /olts/{id}/pons`, `GET /onus`, `GET /onus/{id}/readings`, `GET /overview`
- `GET /alarms`, `POST /alarms/{id}/ack`, `GET /events` (SSE)
- `/notification-channels`, `/reports/availability`, `/reports/alarms` (sprint 5)
- `GET /internal/collector/olts` (token de serviço), `GET /health`

## Sprints

2. **Worker de alarmes**: coletor publica no Redis; worker consome, guarda
   leituras e estado, aplica as regras (ONU offline, sinal < -27 dBm,
   rompimento de fibra, OLT inacessível, CPU alta), deduplica e grava alarmes
   com latência. Pronto: falha no simulador vira alarme no banco.
3. **API e cadastro**: JWT, RLS, CRUD de OLTs, testar conexão, descoberta;
   coletor busca as OLTs na API; tela de cadastro. Pronto: teste prova
   isolamento entre tenants.
4. **Dashboard**: visão geral, OLTs, ONUs, alarmes, SSE. Pronto: falha no
   simulador aparece no dashboard (teste e2e).
5. **Notificações e relatórios**: e-mail (Mailpit), webhook com HMAC,
   relatórios CSV/PDF. Pronto: testes com servidores fake.
6. **Desempenho**: carga com N OLTs, latência p50/p95/p99, ONUs/s, CPU/RAM;
   `docs/resultados.md` com metodologia, tabelas e gráficos.

## Decisões

1. Postgres puro em vez de TimescaleDB; leituras antigas (> 90 dias) apagadas
   por rotina.
2. Papéis: a API usa `lumio_app` (sem BYPASSRLS, `SET LOCAL app.tenant_id`
   por transação); worker usa `lumio_system` (BYPASSRLS), pois processa
   todos os tenants.
3. Community SNMP cifrada no banco (Fernet, `LUMIO_SECRET_KEY` do `.env`).
4. Na sprint 2 ainda não há API: o worker cria o tenant `demo` e registra
   automaticamente as OLTs que o coletor do YAML relata. Na sprint 3 o
   coletor passa a buscar as OLTs na API.
5. SSE em vez de WebSocket (fluxo é só servidor → navegador).
6. Testes de banco rodam contra Postgres e Redis reais (compose local,
   `services` no CI): RLS só se prova num Postgres de verdade.
7. Limites de alarme fixos no código por enquanto.
8. Driver ZTE fora do escopo.
9. Migrações em SQL puro (`db/migrations/NNNN_*.sql`) aplicadas por um
   script pequeno com asyncpg, em vez de Alembic: o esquema fica legível
   no próprio SQL e não precisa de ORM (decidido na sprint 2).
10. Senhas do compose têm valores padrão só para desenvolvimento local;
    qualquer ambiente real define tudo no `.env` (ver `.env.example`).
11. A API nunca usa BYPASSRLS: login, cadastro e a lista do coletor passam por
    três funções `SECURITY DEFINER` no banco (sprint 3).
12. Coletor lê o cadastro pela API (`/api/internal/collector/olts`, token de
    serviço) a cada 30 s, em vez de acessar o banco (sprint 3).
13. Descoberta grava só inventário; o estado online/offline é sempre do worker
    (sprint 3).
14. Token JWT no `localStorage`, painel e API no mesmo endereço via nginx (sem
    CORS); cookie `httpOnly` fica para depois do MVP (sprint 3).
15. Sem react-router na sprint 3 (duas telas); entra na sprint 4.
