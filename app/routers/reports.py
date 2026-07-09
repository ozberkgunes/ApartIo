import csv
import io
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import models, scoping
from ..auth import require_role
from ..database import get_db
from ..models import ROLE_BUILDING_MANAGER, ROLE_SITE_MANAGER
from ..templating import templates

router = APIRouter()

managers_only = require_role(ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)


def _default_range() -> tuple[date, date]:
    today = date.today()
    year, month = today.year, today.month - 5
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1), today


def _parse_range(start: str, end: str) -> tuple[date, date]:
    default_start, default_end = _default_range()
    try:
        start_date = date.fromisoformat(start) if start else default_start
        end_date = date.fromisoformat(end) if end else default_end
    except ValueError:
        raise HTTPException(400, "Geçersiz tarih")
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    return start_date, end_date


def _months_between(start: date, end: date) -> list[str]:
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            month, year = 1, year + 1
    return months[-24:]  # aşırı geniş aralıkta grafiği sınırla


@router.get("/reports")
def reports(
    request: Request,
    start: str = "",
    end: str = "",
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    start_date, end_date = _parse_range(start, end)

    payments = [p for p in scoping.scoped_payments(db, user) if start_date <= p.paid_at <= end_date]
    expenses = [
        e for e in scoping.scoped_expenses(db, user) if start_date <= e.expense_date <= end_date
    ]
    debts = [d for d in scoping.scoped_debts(db, user) if start_date <= d.due_date <= end_date]

    income_total = sum((p.amount for p in payments), Decimal("0"))
    expense_total = sum((e.amount for e in expenses), Decimal("0"))
    debt_total = sum((d.amount for d in debts), Decimal("0"))
    debt_paid = sum((d.paid_amount for d in debts), Decimal("0"))
    collection_rate = float(debt_paid / debt_total * 100) if debt_total else 0.0

    months = _months_between(start_date, end_date)
    income_series = {m: Decimal("0") for m in months}
    expense_series = {m: Decimal("0") for m in months}
    for p in payments:
        key = f"{p.paid_at.year:04d}-{p.paid_at.month:02d}"
        if key in income_series:
            income_series[key] += p.amount
    for e in expenses:
        key = f"{e.expense_date.year:04d}-{e.expense_date.month:02d}"
        if key in expense_series:
            expense_series[key] += e.amount

    expense_by_category: dict[str, Decimal] = {}
    for e in expenses:
        expense_by_category[e.category] = expense_by_category.get(e.category, Decimal("0")) + e.amount

    debtors = sorted(
        (a for a in scoping.scoped_apartments(db, user) if a.open_debt_total > 0),
        key=lambda a: a.open_debt_total,
        reverse=True,
    )[:10]

    return templates.TemplateResponse(
        request,
        "reports/index.html",
        {
            "user": user,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "income_total": income_total,
            "expense_total": expense_total,
            "net": income_total - expense_total,
            "collection_rate": collection_rate,
            "months": months,
            "income_values": [float(income_series[m]) for m in months],
            "expense_values": [float(expense_series[m]) for m in months],
            "category_labels": list(expense_by_category.keys()),
            "category_values": [float(v) for v in expense_by_category.values()],
            "debtors": debtors,
        },
    )


def _csv_response(filename: str, headers: list[str], rows: list[list]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(headers)
    writer.writerows(rows)
    return Response(
        content="﻿" + buffer.getvalue(),  # BOM: Excel'in Türkçe karakterleri tanıması için
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/export/{kind}")
def export_csv(
    kind: str,
    start: str = "",
    end: str = "",
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    start_date, end_date = _parse_range(start, end)

    if kind == "debts":
        rows = [
            [d.apartment.label, d.description, f"{d.amount:.2f}", f"{d.paid_amount:.2f}",
             f"{d.remaining:.2f}", d.due_date.isoformat(), d.status_label]
            for d in scoping.scoped_debts(db, user)
            if start_date <= d.due_date <= end_date
        ]
        return _csv_response(
            "borclar.csv",
            ["Daire", "Açıklama", "Tutar", "Ödenen", "Kalan", "Vade", "Durum"],
            rows,
        )
    if kind == "payments":
        rows = [
            [p.paid_at.isoformat(), p.debt.apartment.label, p.debt.description,
             f"{p.amount:.2f}", p.method_label]
            for p in scoping.scoped_payments(db, user)
            if start_date <= p.paid_at <= end_date
        ]
        return _csv_response(
            "tahsilatlar.csv", ["Tarih", "Daire", "Borç", "Tutar", "Yöntem"], rows
        )
    if kind == "expenses":
        rows = [
            [e.expense_date.isoformat(), e.scope_label, e.category,
             f"{e.amount:.2f}", e.description or ""]
            for e in scoping.scoped_expenses(db, user)
            if start_date <= e.expense_date <= end_date
        ]
        return _csv_response(
            "giderler.csv", ["Tarih", "Kapsam", "Kategori", "Tutar", "Açıklama"], rows
        )
    raise HTTPException(404, "Geçersiz rapor türü")
