"""Relatórios por período: disponibilidade e alarmes, em JSON, CSV e PDF.

Método da disponibilidade (vai para o TCC):
- O período P = [de, até). Para cada ONU, o tempo fora do ar é a soma dos
  alarmes "ONU offline" que se sobrepõem a P, cortados nas bordas de P. Alarme
  ainda aberto conta até agora (ou até o fim de P).
- Disponibilidade da ONU = 1 - tempo fora / duração de P.
- Da OLT (rede de acesso) = 1 - soma do tempo fora das ONUs / (nº de ONUs x P),
  ou seja, a média das ONUs ponderada pelo tempo.
- Da OLT (gerência) = 1 - tempo com alarme "OLT inacessível" / P. Enquanto a
  OLT não responde, não dá para saber o estado das ONUs: esse tempo aparece
  separado, não como ONUs fora do ar.
- Considera as ONUs do inventário atual (ONU removida some do relatório).
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import asyncpg

BRT = timezone(timedelta(hours=-3))      # horário de Brasília (sem horário de verão desde 2019)

KIND_LABEL = {
    "pon_fiber_cut": "Rompimento de fibra",
    "onu_offline": "ONU offline",
    "onu_rx_low": "Sinal baixo",
    "olt_unreachable": "OLT inacessível",
    "olt_cpu_high": "CPU alta",
}
SEVERITY_LABEL = {"critical": "Crítico", "major": "Grave", "minor": "Menor", "warning": "Aviso"}


@dataclass
class Period:
    start: datetime
    end: datetime

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    def label(self) -> str:
        f = "%d/%m/%Y %H:%M"
        return f"{self.start.astimezone(BRT).strftime(f)} a {self.end.astimezone(BRT).strftime(f)}"

    def slug(self) -> str:
        return f"{self.start.astimezone(BRT):%Y-%m-%d}_{self.end.astimezone(BRT):%Y-%m-%d}"


def pct(down_s: float, total_s: float) -> float:
    """Disponibilidade em % com 3 casas, truncada: com qualquer falha, nunca mostra 100 %."""
    value = 100 * (1 - down_s / total_s)
    return math.floor(round(value * 1000, 6)) / 1000


# tempo de sobreposição de um alarme com o período, em segundos
OVERLAP = ("extract(epoch FROM least(coalesce(a.cleared_at, now()), $2) - greatest(a.event_ts, $1))")
IN_PERIOD = "a.event_ts < $2 AND coalesce(a.cleared_at, now()) > $1"


async def availability(db: asyncpg.Connection, p: Period) -> dict:
    olts = await db.fetch(
        f"""
        SELECT o.id, o.name,
               (SELECT count(*) FROM onus n WHERE n.olt_id = o.id) AS onus,
               coalesce((SELECT sum({OVERLAP}) FROM alarms a
                         WHERE a.olt_id = o.id AND a.kind = 'onu_offline' AND {IN_PERIOD}), 0) AS onu_down_s,
               (SELECT count(*) FROM alarms a WHERE a.olt_id = o.id AND a.kind = 'onu_offline' AND {IN_PERIOD}) AS onu_outages,
               (SELECT count(*) FROM alarms a WHERE a.olt_id = o.id AND a.kind = 'pon_fiber_cut' AND {IN_PERIOD}) AS fiber_cuts,
               coalesce((SELECT sum({OVERLAP}) FROM alarms a
                         WHERE a.olt_id = o.id AND a.kind = 'olt_unreachable' AND {IN_PERIOD}), 0) AS olt_down_s
        FROM olts o ORDER BY o.name
        """, p.start, p.end)
    worst = await db.fetch(
        f"""
        SELECT o.name AS olt, pp.name AS pon, n.onu_index, n.serial,
               sum({OVERLAP}) AS down_s, count(*) AS outages
        FROM alarms a JOIN onus n ON n.id = a.onu_id JOIN olts o ON o.id = n.olt_id JOIN pon_ports pp ON pp.id = n.pon_id
        WHERE a.kind = 'onu_offline' AND {IN_PERIOD}
        GROUP BY o.name, pp.name, n.onu_index, n.serial ORDER BY down_s DESC, o.name, pp.name, n.onu_index LIMIT 10
        """, p.start, p.end)

    rows, total_onus, total_down = [], 0, 0.0
    for o in olts:
        onu_time = o["onus"] * p.seconds
        down = float(o["onu_down_s"])
        rows.append({
            "olt": o["name"], "onus": o["onus"],
            "availability_pct": pct(down, onu_time) if onu_time else None,
            "onu_downtime_min": round(down / 60, 1),
            "onu_outages": o["onu_outages"], "fiber_cuts": o["fiber_cuts"],
            "olt_management_pct": pct(float(o["olt_down_s"]), p.seconds),
            "olt_unreachable_min": round(float(o["olt_down_s"]) / 60, 1),
        })
        total_onus += o["onus"]
        total_down += down
    overall = pct(total_down, total_onus * p.seconds) if total_onus else None
    return {
        "period": {"from": p.start.isoformat(), "to": p.end.isoformat()},
        "overall_availability_pct": overall,
        "olts": rows,
        "worst_onus": [{
            "olt": w["olt"], "pon": w["pon"], "onu": w["onu_index"], "serial": w["serial"],
            "availability_pct": pct(float(w["down_s"]), p.seconds),
            "downtime_min": round(float(w["down_s"]) / 60, 1), "outages": w["outages"],
        } for w in worst],
    }


async def alarms_report(db: asyncpg.Connection, p: Period) -> dict:
    rows = await db.fetch(
        """
        SELECT a.kind, a.severity, a.status, a.event_ts, a.cleared_at, a.occurrences, a.source,
               o.name AS olt, pp.name AS pon, n.onu_index, n.serial,
               (SELECT count(*) FROM alarms c WHERE c.parent_id = a.id) AS affected,
               u.name AS acknowledged_by
        FROM alarms a JOIN olts o ON o.id = a.olt_id
        LEFT JOIN pon_ports pp ON pp.id = a.pon_id LEFT JOIN onus n ON n.id = a.onu_id
        LEFT JOIN users u ON u.id = a.acknowledged_by
        WHERE a.parent_id IS NULL AND a.event_ts >= $1 AND a.event_ts < $2
        ORDER BY a.event_ts
        """, p.start, p.end)
    items, by_kind, by_severity, durations = [], {}, {}, []
    for r in rows:
        dur = (r["cleared_at"] - r["event_ts"]).total_seconds() / 60 if r["cleared_at"] else None
        if dur is not None:
            durations.append(dur)
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
        by_severity[r["severity"]] = by_severity.get(r["severity"], 0) + 1
        items.append({
            "started_at": r["event_ts"].isoformat(), "cleared_at": r["cleared_at"] and r["cleared_at"].isoformat(),
            "duration_min": round(dur, 1) if dur is not None else None,
            "kind": r["kind"], "severity": r["severity"], "status": r["status"],
            "olt": r["olt"], "pon": r["pon"], "onu": r["onu_index"], "serial": r["serial"],
            "affected_onus": r["affected"], "occurrences": r["occurrences"], "source": r["source"],
            "acknowledged_by": r["acknowledged_by"],
        })
    return {
        "period": {"from": p.start.isoformat(), "to": p.end.isoformat()},
        "total": len(items),
        "open": sum(1 for i in items if i["cleared_at"] is None),
        "mttr_min": round(sum(durations) / len(durations), 1) if durations else None,
        "by_kind": by_kind,
        "by_severity": by_severity,
        "items": items,
    }


# ------------------------------------------------------------------ atendimento da equipe

CAUSE_LABEL = {
    "fiber_third_party": "Rompimento por terceiros (obra, veículo)",
    "fiber_natural": "Rompimento por causa natural (árvore, chuva, animal)",
    "power": "Falta de energia",
    "equipment": "Falha de equipamento (OLT, splitter, ONU)",
    "customer": "Problema no cliente",
    "maintenance": "Manutenção programada",
    "configuration": "Erro de configuração",
    "no_fault": "Sem falha real (falso alarme)",
    "other": "Outro",
}
SLA_ASSUME_MIN = 15          # meta usada no relatório: chamado assumido em até 15 min


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _minutes(a: datetime | None, b: datetime | None) -> float | None:
    return (b - a).total_seconds() / 60 if a and b else None


def _segments(events: list[asyncpg.Record], now: datetime) -> list[tuple]:
    """(operador, segundos) de cada trecho em que o chamado ficou com alguém.

    "assigned" troca o dono; "closed" para o relógio; "reopened" volta a contar
    para o mesmo dono. Trecho ainda em andamento conta até agora.
    """
    out, owner, since = [], None, None
    for e in events:
        t = e["created_at"]
        if e["kind"] == "assigned":
            if owner and since:
                out.append((owner, (t - since).total_seconds()))
            owner, since = e["target_id"], t
        elif e["kind"] == "closed":
            if owner and since:
                out.append((owner, (t - since).total_seconds()))
            since = None
        elif e["kind"] == "reopened" and owner:
            since = t
    if owner and since:
        out.append((owner, (now - since).total_seconds()))
    return out


async def attendance_report(db: asyncpg.Connection, p: Period) -> dict:
    """Atendimento dos chamados abertos no período: por operador, por causa e chamado a chamado."""
    now = datetime.now(timezone.utc)
    rows = await db.fetch(
        """
        SELECT a.id, a.kind, a.severity, a.created_at, a.cleared_at, a.first_assigned_at, a.work_closed_at,
               a.resolution_cause, a.resolution_notes, a.assigned_to, a.work_closed_by,
               o.name AS olt, pp.name AS pon, n.onu_index, ua.name AS owner, uc.name AS closer,
               (SELECT e.target_id FROM alarm_events e WHERE e.alarm_id = a.id AND e.kind = 'assigned'
                ORDER BY e.created_at LIMIT 1) AS first_owner
        FROM alarms a JOIN olts o ON o.id = a.olt_id
        LEFT JOIN pon_ports pp ON pp.id = a.pon_id LEFT JOIN onus n ON n.id = a.onu_id
        LEFT JOIN users ua ON ua.id = a.assigned_to LEFT JOIN users uc ON uc.id = a.work_closed_by
        WHERE a.parent_id IS NULL AND a.created_at >= $1 AND a.created_at < $2
        ORDER BY a.created_at
        """, p.start, p.end)
    ids = [r["id"] for r in rows]
    events: dict = {}
    for e in await db.fetch("SELECT alarm_id, kind, actor_id, target_id, created_at FROM alarm_events "
                            "WHERE alarm_id = ANY($1::uuid[]) ORDER BY created_at", ids):
        events.setdefault(e["alarm_id"], []).append(e)
    names = {u["id"]: u["name"] for u in await db.fetch("SELECT id, name FROM users")}

    ops: dict = {}

    def op(uid):
        return ops.setdefault(uid, {"name": names.get(uid, "(usuário removido)"), "taken": set(), "closed": 0,
                                    "open": 0, "tme": [], "tma": [], "seconds": 0.0, "notes": 0})

    items, tme_all, tma_all, causes = [], [], [], {}
    for r in rows:
        evs = events.get(r["id"], [])
        tme = _minutes(r["created_at"], r["first_assigned_at"])
        tma = _minutes(r["first_assigned_at"], r["work_closed_at"])
        if tme is not None:
            tme_all.append(tme)
            if r["first_owner"]:
                op(r["first_owner"])["tme"].append(tme)
        if tma is not None:
            tma_all.append(tma)
            if r["work_closed_by"]:
                op(r["work_closed_by"])["closed"] += 1
                op(r["work_closed_by"])["tma"].append(tma)
        if r["assigned_to"] and r["work_closed_at"] is None:
            op(r["assigned_to"])["open"] += 1
        for e in evs:
            if e["kind"] == "assigned" and e["target_id"]:
                op(e["target_id"])["taken"].add(r["id"])
            elif e["kind"] == "note" and e["actor_id"]:
                op(e["actor_id"])["notes"] += 1
        for uid, secs in _segments(evs, now):
            op(uid)["seconds"] += secs
        if r["resolution_cause"]:
            c = causes.setdefault(r["resolution_cause"], {"count": 0, "tma": []})
            c["count"] += 1
            if tma is not None:
                c["tma"].append(tma)
        items.append({
            "opened_at": r["created_at"].isoformat(), "kind": r["kind"], "severity": r["severity"],
            "olt": r["olt"], "pon": r["pon"], "onu": r["onu_index"],
            "network_cleared_at": r["cleared_at"] and r["cleared_at"].isoformat(),
            "first_assigned_at": r["first_assigned_at"] and r["first_assigned_at"].isoformat(),
            "closed_at": r["work_closed_at"] and r["work_closed_at"].isoformat(),
            "owner": r["owner"], "closed_by": r["closer"],
            "tme_min": round(tme, 1) if tme is not None else None,
            "tma_min": round(tma, 1) if tma is not None else None,
            "cause": r["resolution_cause"], "notes": r["resolution_notes"],
        })

    assumed = sum(1 for i in items if i["first_assigned_at"])
    closed = sum(1 for i in items if i["closed_at"])
    within_sla = sum(1 for t in tme_all if t <= SLA_ASSUME_MIN)
    operators = sorted((
        {"name": o["name"], "taken": len(o["taken"]), "closed": o["closed"], "open": o["open"],
         "tme_min": _avg(o["tme"]), "tma_min": _avg(o["tma"]),
         "time_in_attendance_min": round(o["seconds"] / 60, 1), "notes": o["notes"]}
        for o in ops.values()), key=lambda o: (-o["closed"], -o["taken"], o["name"]))
    return {
        "period": {"from": p.start.isoformat(), "to": p.end.isoformat()},
        "summary": {
            "tickets": len(items), "assumed": assumed, "unattended": len(items) - assumed, "closed": closed,
            "in_progress": assumed - closed, "tme_min": _avg(tme_all), "tma_min": _avg(tma_all),
            "tma_max_min": round(max(tma_all), 1) if tma_all else None,
            "sla_assume_min": SLA_ASSUME_MIN,
            "assumed_within_sla_pct": round(100 * within_sla / len(tme_all), 1) if tme_all else None,
        },
        "operators": operators,
        "causes": sorted(({"cause": k, "label": CAUSE_LABEL.get(k, k), "count": v["count"],
                           "pct": round(100 * v["count"] / closed, 1) if closed else 0.0, "tma_min": _avg(v["tma"])}
                          for k, v in causes.items()), key=lambda c: -c["count"]),
        "items": items,
    }


# ------------------------------------------------------------------ formatos

def _num(v, digits: int = 1) -> str:
    """Número no padrão brasileiro (vírgula decimal), para o Excel em pt-BR abrir certo."""
    if v is None:
        return ""
    return f"{v:.{digits}f}".replace(".", ",") if isinstance(v, float) else str(v)


def _dt(iso: str | None) -> str:
    return datetime.fromisoformat(iso).astimezone(BRT).strftime("%d/%m/%Y %H:%M:%S") if iso else ""


def _csv(header: list[str], rows: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(header)
    w.writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")      # BOM: Excel reconhece UTF-8 (acentos)


def availability_csv(rep: dict) -> bytes:
    return _csv(
        ["OLT", "ONUs", "Disponibilidade da rede (%)", "Tempo de ONUs fora (min)", "Quedas de ONU",
         "Rompimentos de fibra", "Disponibilidade da gerência (%)", "OLT inacessível (min)"],
        [[o["olt"], o["onus"], _num(o["availability_pct"], 3), _num(o["onu_downtime_min"]), o["onu_outages"],
          o["fiber_cuts"], _num(o["olt_management_pct"], 3), _num(o["olt_unreachable_min"])] for o in rep["olts"]],
    )


def alarms_csv(rep: dict) -> bytes:
    return _csv(
        ["Início", "Fim", "Duração (min)", "Alarme", "Severidade", "Situação", "OLT", "PON", "ONU", "Serial",
         "ONUs afetadas", "Ocorrências", "Origem", "Reconhecido por"],
        [[_dt(i["started_at"]), _dt(i["cleared_at"]), _num(i["duration_min"]), KIND_LABEL.get(i["kind"], i["kind"]),
          SEVERITY_LABEL[i["severity"]], i["status"], i["olt"], i["pon"] or "", "" if i["onu"] is None else i["onu"],
          i["serial"] or "", i["affected_onus"] or "", i["occurrences"], i["source"], i["acknowledged_by"] or ""]
         for i in rep["items"]],
    )


def human_minutes(minutes: float | None) -> str:
    """"45 s", "12 min", "3 h 05 min" (para PDF e tela)."""
    if minutes is None:
        return "-"
    s = round(minutes * 60)
    if s < 60:
        return f"{s} s"
    m = s // 60
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def attendance_csv(rep: dict) -> bytes:
    """Chamado a chamado (o resumo por operador está no PDF e na tela)."""
    return _csv(
        ["Aberto em", "Alarme", "Severidade", "OLT", "PON", "ONU", "Assumido em", "Encerrado em", "Com", "Encerrado por",
         "TME (min)", "TMA (min)", "Causa", "O que foi feito", "Normalizou na rede em"],
        [[_dt(i["opened_at"]), KIND_LABEL.get(i["kind"], i["kind"]), SEVERITY_LABEL[i["severity"]], i["olt"],
          i["pon"] or "", "" if i["onu"] is None else i["onu"], _dt(i["first_assigned_at"]), _dt(i["closed_at"]),
          i["owner"] or "", i["closed_by"] or "", _num(i["tme_min"]), _num(i["tma_min"]),
          CAUSE_LABEL.get(i["cause"], i["cause"] or ""), (i["notes"] or "").replace("\n", " "),
          _dt(i["network_cleared_at"])] for i in rep["items"]],
    )


def attendance_pdf(rep: dict, tenant: str, p: Period) -> bytes:
    s = rep["summary"]
    sla = (f"{_num(s['assumed_within_sla_pct'])} % assumidos em até {s['sla_assume_min']} min"
           if s["assumed_within_sla_pct"] is not None else "")
    longest = f" (maior: {human_minutes(s['tma_max_min'])})" if s["tma_max_min"] is not None else ""
    summary = (f"<b>{s['tickets']} chamados</b> no período: {s['assumed']} assumidos, {s['closed']} encerrados, "
               f"{s['in_progress']} em andamento e {s['unattended']} sem atendimento. "
               f"<b>TME</b> (até assumir): {human_minutes(s['tme_min'])}. "
               f"<b>TMA</b> (assumido até encerrado): {human_minutes(s['tma_min'])}{longest}. {sla}")
    return _pdf("Relatório de atendimento da equipe", tenant, p, [
        [summary],
        "Por operador",
        (["Operador", "Assumidos", "Encerrados", "Em andamento", "TME", "TMA", "Tempo em atendimento", "Anotações"],
         [[o["name"], o["taken"], o["closed"], o["open"], human_minutes(o["tme_min"]), human_minutes(o["tma_min"]),
           human_minutes(o["time_in_attendance_min"]), o["notes"]] for o in rep["operators"]]),
        "Causas dos chamados encerrados",
        (["Causa", "Chamados", "%", "TMA"],
         [[c["label"], c["count"], _num(c["pct"]), human_minutes(c["tma_min"])] for c in rep["causes"]]),
        "Chamados",
        (["Aberto em", "Alarme", "Local", "Com", "TME", "TMA", "Causa"],
         [[_dt(i["opened_at"]), KIND_LABEL.get(i["kind"], i["kind"]),
           " · ".join(x for x in (i["olt"], i["pon"] and f"PON {i['pon']}", i["onu"] is not None and f"ONU {i['onu']}") if x),
           i["closed_by"] or i["owner"] or "sem atendimento", human_minutes(i["tme_min"]),
           human_minutes(i["tma_min"]) if i["closed_at"] else "em andamento" if i["first_assigned_at"] else "-",
           CAUSE_LABEL.get(i["cause"], "") if i["cause"] else ""] for i in rep["items"]]),
        ["TME (tempo médio de espera): da abertura do alarme até alguém assumir o chamado. TMA (tempo médio de "
         "atendimento): de quando foi assumido até o operador encerrar, pela média dos chamados encerrados. "
         "Tempo em atendimento: soma dos trechos em que o chamado ficou com cada operador (transferências "
         "dividem o tempo; chamado encerrado não conta)."],
    ])


def _pdf(title: str, tenant: str, p: Period, blocks: list) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    generated = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillGray(0.4)
        canvas.drawString(1.5 * cm, 1 * cm, f"Lumio · {tenant} · gerado em {generated}")
        canvas.drawRightString(doc.pagesize[0] - 1.5 * cm, 1 * cm, f"página {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.8 * cm, title=title, author="Lumio")
    story = [Paragraph(title, styles["Title"]),
             Paragraph(f"{tenant} · período: {p.label()} (horário de Brasília)", styles["Normal"]),
             Spacer(1, 0.5 * cm)]
    for block in blocks:
        if isinstance(block, str):
            story += [Paragraph(block, styles["Heading3"])]
        elif isinstance(block, tuple):           # (cabeçalho, linhas)
            header, rows = block
            if not rows:
                story += [Paragraph("Nada no período.", styles["Italic"]), Spacer(1, 0.3 * cm)]
                continue
            t = Table([header] + rows, repeatRows=1, hAlign="LEFT")
            t.setStyle(TableStyle([
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#94a3b8")),
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story += [t, Spacer(1, 0.4 * cm)]
        else:
            story += [Paragraph(block[0], styles["Normal"]), Spacer(1, 0.2 * cm)]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def availability_pdf(rep: dict, tenant: str, p: Period) -> bytes:
    overall = rep["overall_availability_pct"]
    return _pdf("Relatório de disponibilidade", tenant, p, [
        [f"<b>Disponibilidade geral da rede de acesso: {_num(overall, 3) if overall is not None else '-'} %</b> "
         "(média das ONUs, ponderada pelo tempo; método no fim do relatório)."],
        "Por OLT",
        (["OLT", "ONUs", "Disponib. rede (%)", "ONUs fora (min)", "Quedas", "Rompimentos", "Disponib. gerência (%)",
          "OLT inacessível (min)"],
         [[o["olt"], o["onus"], _num(o["availability_pct"], 3), _num(o["onu_downtime_min"]), o["onu_outages"],
           o["fiber_cuts"], _num(o["olt_management_pct"], 3), _num(o["olt_unreachable_min"])] for o in rep["olts"]]),
        "ONUs com mais tempo fora do ar",
        (["OLT", "PON", "ONU", "Serial", "Disponib. (%)", "Fora (min)", "Quedas"],
         [[w["olt"], w["pon"], w["onu"], w["serial"] or "", _num(w["availability_pct"], 3), _num(w["downtime_min"]),
           w["outages"]] for w in rep["worst_onus"]]),
        ["Método: tempo fora = soma dos alarmes \"ONU offline\" dentro do período. Enquanto a OLT está inacessível "
         "o estado das ONUs é desconhecido; esse tempo aparece na coluna da gerência, não como ONU fora."],
    ])


def alarms_pdf(rep: dict, tenant: str, p: Period) -> bytes:
    summary = (f"<b>{rep['total']} {'alarme' if rep['total'] == 1 else 'alarmes'}</b> no período ({rep['open']} ainda abertos). "
               f"Tempo médio até normalizar (MTTR): {_num(rep['mttr_min']) if rep['mttr_min'] is not None else '-'} min.")
    return _pdf("Relatório de alarmes", tenant, p, [
        [summary],
        "Por tipo",
        (["Alarme", "Quantidade"], [[KIND_LABEL.get(k, k), v] for k, v in sorted(rep["by_kind"].items(), key=lambda x: -x[1])]),
        "Alarmes",
        (["Início", "Duração (min)", "Alarme", "Severidade", "Local", "ONUs afetadas", "Reconhecido por"],
         [[_dt(i["started_at"]), _num(i["duration_min"]) or "aberto", KIND_LABEL.get(i["kind"], i["kind"]),
           SEVERITY_LABEL[i["severity"]],
           " · ".join(x for x in (i["olt"], i["pon"] and f"PON {i['pon']}", i["onu"] is not None and f"ONU {i['onu']}") if x),
           i["affected_onus"] or "", i["acknowledged_by"] or ""] for i in rep["items"]]),
    ])
