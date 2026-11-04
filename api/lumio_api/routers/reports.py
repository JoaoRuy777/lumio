"""Relatórios por período (JSON para a tela, CSV e PDF para baixar)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status

from .. import reports
from ..deps import TenantDb, User

router = APIRouter(prefix="/reports", tags=["relatórios"])

Format = Literal["json", "csv", "pdf"]
MAX_SPAN = timedelta(days=366)


def period(since: datetime | None, until: datetime | None) -> reports.Period:
    end = until or datetime.now(timezone.utc)
    start = since or end - timedelta(days=7)
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "informe datas com fuso (ex.: 2026-11-01T00:00:00-03:00)")
    if start >= end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "o início precisa ser antes do fim")
    if end - start > MAX_SPAN:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "período máximo de 366 dias")
    return reports.Period(start, end)


async def tenant_name(db) -> str:
    return await db.fetchval("SELECT name FROM tenants")


def download(content: bytes, media: str, filename: str) -> Response:
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/availability", summary="Disponibilidade por OLT e piores ONUs no período (padrão: últimos 7 dias)")
async def availability(user: User, db: TenantDb,
                       since: Annotated[datetime | None, Query(alias="from")] = None,
                       until: Annotated[datetime | None, Query(alias="to")] = None,
                       format: Format = "json"):
    p = period(since, until)
    rep = await reports.availability(db, p)
    if format == "csv":
        return download(reports.availability_csv(rep), "text/csv; charset=utf-8", f"lumio-disponibilidade-{p.slug()}.csv")
    if format == "pdf":
        return download(reports.availability_pdf(rep, await tenant_name(db), p), "application/pdf",
                        f"lumio-disponibilidade-{p.slug()}.pdf")
    return rep


@router.get("/alarms", summary="Alarmes do período, com resumo e MTTR (padrão: últimos 7 dias)")
async def alarms(user: User, db: TenantDb,
                 since: Annotated[datetime | None, Query(alias="from")] = None,
                 until: Annotated[datetime | None, Query(alias="to")] = None,
                 format: Format = "json"):
    p = period(since, until)
    rep = await reports.alarms_report(db, p)
    if format == "csv":
        return download(reports.alarms_csv(rep), "text/csv; charset=utf-8", f"lumio-alarmes-{p.slug()}.csv")
    if format == "pdf":
        return download(reports.alarms_pdf(rep, await tenant_name(db), p), "application/pdf", f"lumio-alarmes-{p.slug()}.pdf")
    return rep
