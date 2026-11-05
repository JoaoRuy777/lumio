"""Processa cada registro do coletor: guarda leituras/estado e abre ou fecha alarmes.

Cada registro é tratado numa transação. O worker conecta como lumio_system
(BYPASSRLS) porque processa todos os tenants, mas sempre grava o tenant_id
correto em cada linha.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

import asyncpg

from . import rules
from .rules import AlarmRef

log = logging.getLogger("lumio_worker.processor")


@dataclass
class Ctx:
    conn: asyncpg.Connection
    tenant_id: UUID
    olt_id: UUID
    ts: datetime          # quando o coletor leu/recebeu (base da latência)
    source: str           # trap | poll
    events: list[dict] = field(default_factory=list)   # avisos para o painel, enviados após o commit


class Processor:
    def __init__(self, pool: asyncpg.Pool, default_tenant: str = "demo", redis=None):
        self.pool = pool
        self.redis = redis            # redis.asyncio.Redis: avisa o painel em tempo real (opcional)
        self.default_tenant = default_tenant
        self.tenant_id: UUID | None = None
        self._olts: dict[str, UUID] = {}                 # modo YAML: nome -> id
        self._olt_tenant: dict[UUID, UUID] = {}          # modo API: olt_id -> tenant_id
        self._pons: dict[tuple[UUID, str], UUID] = {}
        self._onus: dict[tuple[UUID, int], UUID] = {}
        self.alarms_opened = 0

    # ------------------------------------------------------------ setup

    async def setup(self) -> None:
        """Modo YAML (sem olt_id nos registros): tudo cai no tenant padrão, criado se faltar."""
        async with self.pool.acquire() as conn:
            self.tenant_id = await conn.fetchval(
                "INSERT INTO tenants (name, slug) VALUES ($1, $1) "
                "ON CONFLICT (slug) DO UPDATE SET slug = EXCLUDED.slug RETURNING id",
                self.default_tenant,
            )

    def _forget_cache(self) -> None:
        self._olts.clear()
        self._olt_tenant.clear()
        self._pons.clear()
        self._onus.clear()

    # ------------------------------------------------------------ entrada

    async def handle(self, record: dict) -> None:
        handler = getattr(self, f"_on_{record.get('type')}", None)
        if handler is None:
            log.debug("tipo ignorado: %s", record.get("type"))
            return
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                if record.get("olt_id"):
                    olt_id = UUID(record["olt_id"])
                    tenant_id = await self._tenant_of(conn, olt_id)
                    if tenant_id is None:
                        log.info("OLT %s não está mais cadastrada; registro ignorado", record["olt_id"])
                        return
                else:
                    if self.tenant_id is None:
                        await self.setup()
                    olt_id, tenant_id = await self._olt(conn, record["olt"]), self.tenant_id
                ctx = Ctx(conn, tenant_id, olt_id, datetime.fromisoformat(record["ts"]), record.get("source", "poll"))
                await handler(ctx, record)
        except asyncpg.ForeignKeyViolationError:
            self._forget_cache()
            # A OLT foi excluída com leituras dela ainda na fila (o coletor só
            # relê o cadastro a cada 30 s): descarta. Outro motivo é erro de verdade.
            if record.get("olt_id"):
                async with self.pool.acquire() as conn:
                    if not await conn.fetchval("SELECT EXISTS (SELECT 1 FROM olts WHERE id = $1)",
                                               UUID(record["olt_id"])):
                        log.info("OLT %s excluída durante o processamento; registro ignorado", record["olt_id"])
                        return
            raise
        except BaseException:
            # ids em cache podem ter vindo da transação desfeita
            self._forget_cache()
            raise
        # Só depois do COMMIT: o painel nunca recebe aviso de algo que não foi gravado
        await self._publish(ctx)

    async def _publish(self, ctx: Ctx) -> None:
        if not (self.redis and ctx.events):
            return
        channel = f"lumio:events:{ctx.tenant_id}"
        try:
            for ev in ctx.events:
                await self.redis.publish(channel, json.dumps(ev, default=str))
        except Exception as e:      # aviso em tempo real é melhor-esforço; o dado já está no banco
            log.warning("não consegui avisar o painel (%s)", e)

    # ------------------------------------------------------------ inventário

    async def _tenant_of(self, conn, olt_id: UUID) -> UUID | None:
        if olt_id not in self._olt_tenant:
            tenant_id = await conn.fetchval("SELECT tenant_id FROM olts WHERE id = $1", olt_id)
            if tenant_id is None:
                return None
            self._olt_tenant[olt_id] = tenant_id
        return self._olt_tenant[olt_id]

    async def _olt(self, conn, name: str) -> UUID:
        if name not in self._olts:
            # Sprint 2: OLT do YAML do coletor é registrada na primeira leitura.
            # Sprint 3: o coletor passa a mandar o olt_id cadastrado na API.
            self._olts[name] = await conn.fetchval(
                "INSERT INTO olts (tenant_id, name) VALUES ($1, $2) "
                "ON CONFLICT (tenant_id, name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
                self.tenant_id, name,
            )
        return self._olts[name]

    async def _pon(self, ctx: Ctx, name: str) -> UUID:
        key = (ctx.olt_id, name)
        if key not in self._pons:
            self._pons[key] = await ctx.conn.fetchval(
                "INSERT INTO pon_ports (tenant_id, olt_id, name) VALUES ($1, $2, $3) "
                "ON CONFLICT (olt_id, name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
                ctx.tenant_id, ctx.olt_id, name,
            )
        return self._pons[key]

    async def _onu(self, ctx: Ctx, pon: str, index: int) -> tuple[UUID, UUID]:
        pon_id = await self._pon(ctx, pon)
        key = (pon_id, index)
        if key not in self._onus:
            self._onus[key] = await ctx.conn.fetchval(
                "INSERT INTO onus (tenant_id, olt_id, pon_id, onu_index) VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (pon_id, onu_index) DO UPDATE SET onu_index = EXCLUDED.onu_index RETURNING id",
                ctx.tenant_id, ctx.olt_id, pon_id, index,
            )
        return pon_id, self._onus[key]

    # ------------------------------------------------------------ alarmes

    async def open_alarm(self, ctx: Ctx, ref: AlarmRef, *, pon_id: UUID | None = None, onu_id: UUID | None = None,
                         parent_id: UUID | None = None, details: dict | None = None) -> UUID:
        """Abre o alarme ou, se já houver um aberto com a mesma chave, só conta mais uma ocorrência."""
        row = await ctx.conn.fetchrow(
            """
            INSERT INTO alarms (tenant_id, olt_id, pon_id, onu_id, kind, severity, dedup_key, source,
                                parent_id, details, event_ts, latency_ms, first_seen_at, last_seen_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11,
                    extract(epoch FROM clock_timestamp() - $11) * 1000, $11, $11)
            ON CONFLICT (tenant_id, dedup_key) WHERE status <> 'cleared' DO UPDATE SET
                occurrences = alarms.occurrences + 1,
                last_seen_at = greatest(alarms.last_seen_at, EXCLUDED.last_seen_at),
                details = alarms.details || EXCLUDED.details
            RETURNING id, (xmax = 0) AS inserted, latency_ms
            """,
            ctx.tenant_id, ctx.olt_id, pon_id, onu_id, ref.kind, ref.severity, ref.dedup_key, ctx.source,
            parent_id, json.dumps(details or {}), ctx.ts,
        )
        if row["inserted"]:
            self.alarms_opened += 1
            ctx.events.append({"type": "alarm.opened", "alarm_id": row["id"], "kind": ref.kind,
                               "severity": ref.severity, "olt_id": ctx.olt_id})
            log.info("alarme %s (%s) aberto em %.0f ms", ref.kind, ref.severity, row["latency_ms"])
            maintenance = await self._maintenance_window(ctx, pon_id)
            if maintenance:                  # manutenção programada: aparece no painel, mas sem aviso
                await ctx.conn.execute("UPDATE alarms SET maintenance_id = $2 WHERE id = $1", row["id"], maintenance)
                log.info("alarme %s em janela de manutenção: sem notificação", ref.kind)
            elif parent_id is None:          # ONU dentro de um rompimento já avisado: não avisa de novo
                await self._enqueue_opened(ctx, row["id"], ref)
        return row["id"]

    async def _maintenance_window(self, ctx: Ctx, pon_id: UUID | None) -> UUID | None:
        """Janela de manutenção ativa no instante do evento: da OLT inteira ou da PON do alarme."""
        return await ctx.conn.fetchval(
            "SELECT id FROM maintenance_windows WHERE tenant_id = $1 AND olt_id = $2 AND cancelled_at IS NULL "
            "AND starts_at <= $4 AND ends_at > $4 AND (pon_id IS NULL OR pon_id = $3) "
            "ORDER BY pon_id NULLS LAST LIMIT 1",
            ctx.tenant_id, ctx.olt_id, pon_id, ctx.ts,
        )

    async def _enqueue_opened(self, ctx: Ctx, alarm_id: UUID, ref: AlarmRef) -> None:
        """Entrega para cada canal ativo que aceita a severidade (mesma transação do alarme)."""
        await ctx.conn.execute(
            """
            INSERT INTO notifications (tenant_id, channel_id, alarm_id, event, next_attempt_at)
            SELECT $1, c.id, $2, 'opened', now() + make_interval(secs => $4)
            FROM notification_channels c
            WHERE c.tenant_id = $1 AND c.enabled
              AND (CASE c.min_severity WHEN 'critical' THEN 0 WHEN 'major' THEN 1 WHEN 'minor' THEN 2 ELSE 3 END) >= $3
            ON CONFLICT DO NOTHING
            """,
            ctx.tenant_id, alarm_id, rules.SEVERITY_RANK[ref.severity], rules.NOTIFY_GRACE_S.get(ref.kind, 0.0),
        )

    async def _enqueue_cleared(self, ctx: Ctx, alarm_id: UUID) -> None:
        # normalizou antes de o aviso sair (oscilação): não avisa nem a queda nem a volta
        await ctx.conn.execute(
            "UPDATE notifications SET status = 'suppressed', last_error = 'normalizou antes do envio' "
            "WHERE alarm_id = $1 AND event = 'opened' AND status = 'pending'", alarm_id)
        # avisa a volta só para quem recebeu (ou está recebendo) a queda
        await ctx.conn.execute(
            """
            INSERT INTO notifications (tenant_id, channel_id, alarm_id, event)
            SELECT n.tenant_id, n.channel_id, n.alarm_id, 'cleared'
            FROM notifications n JOIN notification_channels c ON c.id = n.channel_id
            WHERE n.alarm_id = $1 AND n.event = 'opened' AND n.status IN ('sending', 'sent')
              AND c.enabled AND c.notify_clear
            ON CONFLICT DO NOTHING
            """, alarm_id)

    async def clear_alarm(self, ctx: Ctx, ref: AlarmRef) -> UUID | None:
        alarm_id = await ctx.conn.fetchval(
            "UPDATE alarms SET status = 'cleared', cleared_at = $3 "
            "WHERE tenant_id = $1 AND dedup_key = $2 AND status <> 'cleared' RETURNING id",
            ctx.tenant_id, ref.dedup_key, ctx.ts,
        )
        if alarm_id:
            log.info("alarme %s encerrado", ref.kind)
            ctx.events.append({"type": "alarm.cleared", "alarm_id": alarm_id, "kind": ref.kind,
                               "olt_id": ctx.olt_id})
            await self._enqueue_cleared(ctx, alarm_id)
        return alarm_id

    async def _open_alarm_id(self, ctx: Ctx, ref: AlarmRef) -> UUID | None:
        return await ctx.conn.fetchval(
            "SELECT id FROM alarms WHERE tenant_id = $1 AND dedup_key = $2 AND status <> 'cleared'",
            ctx.tenant_id, ref.dedup_key,
        )

    async def _onu_went_offline(self, ctx: Ctx, pon_id: UUID, onu_id: UUID, details: dict) -> None:
        fiber = AlarmRef("pon_fiber_cut", pon_id)
        parent = await self._open_alarm_id(ctx, fiber)
        await self.open_alarm(ctx, AlarmRef("onu_offline", onu_id), pon_id=pon_id, onu_id=onu_id,
                              parent_id=parent, details=details)
        if parent:
            return
        total, offline, recent = await ctx.conn.fetchrow(
            "SELECT count(*), count(*) FILTER (WHERE online IS FALSE), "
            "       count(*) FILTER (WHERE online IS FALSE AND last_change_at >= $2) "
            "FROM onus WHERE pon_id = $1",
            pon_id, ctx.ts - timedelta(seconds=rules.FIBER_CUT_WINDOW_S),
        )
        if rules.is_fiber_cut(total, offline, recent):
            parent = await self.open_alarm(ctx, fiber, pon_id=pon_id, details={"onus_offline": offline})
            # os alarmes das ONUs da PON viram filhos do rompimento
            await ctx.conn.execute(
                "UPDATE alarms SET parent_id = $1 WHERE pon_id = $2 AND kind = 'onu_offline' "
                "AND status <> 'cleared' AND id <> $1",
                parent, pon_id,
            )
            # os avisos dessas ONUs ainda na espera viram um só: o do rompimento
            await ctx.conn.execute(
                "UPDATE notifications SET status = 'suppressed', last_error = 'agrupado no rompimento de fibra' "
                "WHERE status = 'pending' AND alarm_id IN (SELECT id FROM alarms WHERE parent_id = $1)",
                parent,
            )

    async def _onu_came_online(self, ctx: Ctx, pon_id: UUID, onu_id: UUID) -> None:
        await self.clear_alarm(ctx, AlarmRef("onu_offline", onu_id))
        fiber = AlarmRef("pon_fiber_cut", pon_id)
        if await self._open_alarm_id(ctx, fiber):
            total, online = await ctx.conn.fetchrow(
                "SELECT count(*), count(*) FILTER (WHERE online) FROM onus WHERE pon_id = $1", pon_id)
            if rules.fiber_cut_recovered(total, online):
                await self.clear_alarm(ctx, fiber)

    async def _set_onu_online(self, ctx: Ctx, onu_id: UUID, online: bool) -> bool | None:
        """Atualiza o estado e devolve o anterior (None = ainda não conhecido)."""
        return await ctx.conn.fetchval(
            """
            WITH prev AS (SELECT online FROM onus WHERE id = $1)
            UPDATE onus SET online = $2, last_seen_at = $3,
                last_change_at = CASE WHEN onus.online IS DISTINCT FROM $2 THEN $3 ELSE onus.last_change_at END
            FROM prev WHERE onus.id = $1
            RETURNING prev.online
            """,
            onu_id, online, ctx.ts,
        )

    # ------------------------------------------------------------ registros do coletor

    async def _on_olt_info(self, ctx: Ctx, r: dict) -> None:
        await ctx.conn.execute(
            "UPDATE olts SET vendor = $2, model = $3, sys_name = $4 WHERE id = $1",
            ctx.olt_id, r.get("vendor"), r.get("model"), r.get("sys_name"),
        )
        for pon in r.get("pon_ports", []):
            await self._pon(ctx, pon)

    async def _on_onu_status(self, ctx: Ctx, r: dict) -> None:
        await ctx.conn.execute(
            "UPDATE olts SET last_poll_at = $2, reachable = true, last_error = NULL WHERE id = $1",
            ctx.olt_id, ctx.ts,
        )
        # Sprint 6: um UPDATE para a OLT inteira (antes era um por ONU). Devolve
        # só as ONUs que mudaram de estado, que são as únicas que podem alarmar.
        ids, onlines, serials, pons = [], [], [], {}
        for o in r["onus"]:
            pon_id, onu_id = await self._onu(ctx, o["pon"], o["onu"])        # em cache depois da 1ª vez
            ids.append(onu_id)
            onlines.append(o["online"])
            serials.append(o.get("serial"))
            pons[onu_id] = (pon_id, o.get("serial"))
        changed = await ctx.conn.fetch(
            """
            WITH new AS (SELECT * FROM unnest($1::uuid[], $2::bool[], $3::text[]) AS t(id, online, serial)),
                 prev AS (SELECT n.id, n.online FROM onus n JOIN new USING (id))
            UPDATE onus n SET online = new.online, last_seen_at = $4,
                   serial = coalesce(new.serial, n.serial),
                   last_change_at = CASE WHEN n.online IS DISTINCT FROM new.online THEN $4 ELSE n.last_change_at END
            FROM new JOIN prev USING (id)
            WHERE n.id = new.id
            RETURNING n.id, prev.online AS prev, new.online AS online
            """,
            ids, onlines, serials, ctx.ts,
        )
        order = {onu_id: i for i, onu_id in enumerate(ids)}          # mantém a ordem da OLT (PON, ONU)
        for row in sorted(changed, key=lambda x: order[x["id"]]):
            pon_id, serial = pons[row["id"]]
            if row["prev"] is not False and not row["online"]:
                # caiu sem trap (ou é a primeira leitura e já estava offline)
                await self._onu_went_offline(ctx, pon_id, row["id"], {"serial": serial})
            elif row["prev"] is False and row["online"]:
                await self._onu_came_online(ctx, pon_id, row["id"])

    async def _on_onu_optical(self, ctx: Ctx, r: dict) -> None:
        # Sprint 6: leituras, potência atual e encerramento de "sinal baixo" em
        # lote (3 comandos por OLT em vez de ~3 por ONU).
        ids, rxs, txs, pons = [], [], [], {}
        for o in r["onus"]:
            pon_id, onu_id = await self._onu(ctx, o["pon"], o["onu"])
            rx, tx = o.get("rx_dbm"), o.get("tx_dbm")
            if rx is None and tx is None:
                continue          # ONU offline: sem leitura
            ids.append(onu_id)
            rxs.append(rx)
            txs.append(tx)
            pons[onu_id] = pon_id
        if not ids:
            return
        await ctx.conn.execute(
            "INSERT INTO optical_readings (ts, tenant_id, onu_id, rx_dbm, tx_dbm) "
            "SELECT $1, $2, * FROM unnest($3::uuid[], $4::real[], $5::real[])",
            ctx.ts, ctx.tenant_id, ids, rxs, txs)
        await ctx.conn.execute(
            "UPDATE onus n SET rx_dbm = t.rx, tx_dbm = t.tx FROM unnest($1::uuid[], $2::real[], $3::real[]) AS t(id, rx, tx) "
            "WHERE n.id = t.id", ids, rxs, txs)
        to_clear = []
        for onu_id, rx in zip(ids, rxs):
            action = rules.rx_low_action(rx)
            if action == "open":
                await self.open_alarm(ctx, AlarmRef("onu_rx_low", onu_id), pon_id=pons[onu_id], onu_id=onu_id,
                                      details={"rx_dbm": rx})
            elif action == "clear":
                to_clear.append(AlarmRef("onu_rx_low", onu_id).dedup_key)
        if to_clear:
            await self._clear_many(ctx, "onu_rx_low", to_clear)

    async def _clear_many(self, ctx: Ctx, kind: str, dedup_keys: list[str]) -> None:
        """Encerra de uma vez os alarmes abertos dessas chaves (normalmente nenhum)."""
        rows = await ctx.conn.fetch(
            "UPDATE alarms SET status = 'cleared', cleared_at = $3 "
            "WHERE tenant_id = $1 AND dedup_key = ANY($2::text[]) AND status <> 'cleared' RETURNING id",
            ctx.tenant_id, dedup_keys, ctx.ts)
        for row in rows:
            log.info("alarme %s encerrado", kind)
            ctx.events.append({"type": "alarm.cleared", "alarm_id": row["id"], "kind": kind, "olt_id": ctx.olt_id})
            await self._enqueue_cleared(ctx, row["id"])

    async def _apply_rx_rule(self, ctx: Ctx, pon_id: UUID, onu_id: UUID, rx: float | None) -> None:
        action = rules.rx_low_action(rx)
        ref = AlarmRef("onu_rx_low", onu_id)
        if action == "open":
            await self.open_alarm(ctx, ref, pon_id=pon_id, onu_id=onu_id, details={"rx_dbm": rx})
        elif action == "clear":
            await self.clear_alarm(ctx, ref)

    async def _on_olt_health(self, ctx: Ctx, r: dict) -> None:
        await ctx.conn.execute(
            "INSERT INTO olt_health_readings (ts, tenant_id, olt_id, cpu, temperature, uptime_s) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            ctx.ts, ctx.tenant_id, ctx.olt_id, r.get("cpu"), r.get("temperature"), r.get("uptime_s"),
        )
        await self._apply_cpu_rule(ctx, r.get("cpu"))

    async def _apply_cpu_rule(self, ctx: Ctx, cpu: float | None) -> None:
        action = rules.cpu_high_action(cpu)
        ref = AlarmRef("olt_cpu_high", ctx.olt_id)
        if action == "open":
            await self.open_alarm(ctx, ref, details={"cpu": cpu})
        elif action == "clear":
            await self.clear_alarm(ctx, ref)

    async def _on_event(self, ctx: Ctx, r: dict) -> None:
        kind = r["kind"]
        if kind in ("onu_offline", "onu_online", "onu_rx_low"):
            pon_id, onu_id = await self._onu(ctx, r["pon"], r["onu"])
            if r.get("serial"):
                await ctx.conn.execute("UPDATE onus SET serial = $2 WHERE id = $1 AND serial IS NULL",
                                       onu_id, r["serial"])
            if kind == "onu_offline":
                await self._set_onu_online(ctx, onu_id, False)
                await self._onu_went_offline(ctx, pon_id, onu_id, {"serial": r.get("serial")})
            elif kind == "onu_online":
                await self._set_onu_online(ctx, onu_id, True)
                await self._onu_came_online(ctx, pon_id, onu_id)
            else:
                await ctx.conn.execute("UPDATE onus SET rx_dbm = $2 WHERE id = $1", onu_id, r.get("rx_dbm"))
                await self._apply_rx_rule(ctx, pon_id, onu_id, r.get("rx_dbm"))
        elif kind == "olt_cpu_high":
            await self._apply_cpu_rule(ctx, r.get("cpu"))
        elif kind == "olt_unreachable":
            await ctx.conn.execute("UPDATE olts SET reachable = false, last_error = $2 WHERE id = $1",
                                   ctx.olt_id, r.get("error"))
            await self.open_alarm(ctx, AlarmRef("olt_unreachable", ctx.olt_id), details={"error": r.get("error")})
        elif kind == "olt_reachable":
            await ctx.conn.execute("UPDATE olts SET reachable = true, last_error = NULL WHERE id = $1", ctx.olt_id)
            await self.clear_alarm(ctx, AlarmRef("olt_unreachable", ctx.olt_id))
        else:
            log.info("evento sem regra: %s", kind)
