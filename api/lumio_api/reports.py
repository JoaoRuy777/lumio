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
