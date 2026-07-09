from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, scoping
from ..auth import get_current_user, require_role
from ..database import get_db
from ..models import OWNER_BILLED_CATEGORIES, ROLE_BUILDING_MANAGER, ROLE_SITE_MANAGER
from ..services import finance as finance_service
from ..services import notify as notify_service
from ..templating import templates
from .dues import parse_amount, parse_scope, scope_options

router = APIRouter()

managers_only = require_role(ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)


# ---------- Borçlar ----------

@router.get("/debts")
def list_debts(
    request: Request,
    status: str = "",
    category: str = "",
    timing: str = "",
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    debts = scoping.scoped_debts(db, user)
    if status in models.DEBT_STATUS_LABELS:
        debts = [d for d in debts if d.status == status]
    if category in models.DEBT_CATEGORY_LABELS:
        debts = [d for d in debts if d.category == category]
    if timing == "active":
        debts = [d for d in debts if not d.is_future]
    elif timing == "future":
        debts = [d for d in debts if d.is_future]
    apartments = (
        scoping.scoped_apartments(db, user) if user.role in models.MANAGER_ROLES else []
    )
    options = scope_options(db) if user.role == ROLE_SITE_MANAGER else []
    return templates.TemplateResponse(
        request,
        "finance/debts.html",
        {
            "user": user,
            "debts": debts,
            "apartments": apartments,
            "status_filter": status,
            "category_filter": category,
            "timing_filter": timing,
            "category_labels": models.DEBT_CATEGORY_LABELS,
            "scope_options": options,
        },
    )


def _validated_category(category: str) -> str:
    if category not in models.DEBT_CATEGORY_LABELS:
        raise HTTPException(400, "Geçersiz borç kategorisi")
    return category


@router.post("/debts/new")
def create_debt(
    apartment_id: int = Form(...),
    description: str = Form(...),
    amount: str = Form(...),
    due_date: str = Form(...),
    category: str = Form(models.DEBT_CAT_OTHER),
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    apartment = db.get(models.Apartment, apartment_id)
    if apartment is None:
        raise HTTPException(404, "Daire bulunamadı")
    if not scoping.can_access_apartment(db, user, apartment):
        raise HTTPException(403, "Bu daireye erişim yetkiniz yok.")
    category = _validated_category(category)
    db.add(
        models.Debt(
            apartment_id=apartment_id,
            description=description.strip(),
            amount=parse_amount(amount),
            due_date=date.fromisoformat(due_date),
            category=category,
            bill_to_owner=category in OWNER_BILLED_CATEGORIES,
        )
    )
    db.commit()
    return RedirectResponse("/debts?msg=Borç kaydedildi", status_code=303)


@router.post("/debts/bulk")
def create_bulk_debts(
    scope: str = Form(""),
    category: str = Form(...),
    amount: str = Form(...),
    amount_mode: str = Form("fixed"),  # fixed: daire başına | per_m2: m² başına birim fiyat
    due_date: str = Form(...),
    description: str = Form(...),
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    if user.role == ROLE_BUILDING_MANAGER:
        if user.block is None:
            raise HTTPException(403, "Size atanmış bir blok yok.")
        block_id = user.block_id
        site_id = user.block.site_id
    else:
        site_id, block_id = parse_scope(db, scope)
    category = _validated_category(category)
    value = parse_amount(amount)
    if value <= 0:
        raise HTTPException(400, "Tutar sıfırdan büyük olmalı")
    if amount_mode not in ("fixed", "per_m2"):
        raise HTTPException(400, "Geçersiz tutar tipi")

    q = select(models.Apartment).join(models.Block)
    if block_id:
        q = q.where(models.Apartment.block_id == block_id)
    else:
        q = q.where(models.Block.site_id == site_id)
    apartments = list(db.scalars(q))

    bill_to_owner = category in OWNER_BILLED_CATEGORIES
    parsed_due = date.fromisoformat(due_date)
    created: list[models.Debt] = []
    skipped_no_area = 0
    for apartment in apartments:
        if amount_mode == "per_m2":
            if not apartment.area_m2:
                skipped_no_area += 1
                continue
            debt_amount = (value * Decimal(str(apartment.area_m2))).quantize(Decimal("0.01"))
        else:
            debt_amount = value
        debt = models.Debt(
            apartment_id=apartment.id,
            description=description.strip(),
            amount=debt_amount,
            due_date=parsed_due,
            category=category,
            bill_to_owner=bill_to_owner,
        )
        db.add(debt)
        created.append(debt)
    db.commit()

    responsible_ids = {
        uid
        for debt in created
        if (uid := notify_service.responsible_user_id(debt.apartment, debt.bill_to_owner))
    }
    if responsible_ids:
        notify_service.notify(
            db,
            responsible_ids,
            f"Yeni borç: {models.DEBT_CATEGORY_LABELS[category]}",
            f"{description.strip()} — borcunuz oluşturuldu.",
            link="/debts",
        )
    msg = f"{len(created)} daireye borç oluşturuldu"
    if skipped_no_area:
        msg += f" ({skipped_no_area} daire m² bilgisi olmadığından atlandı)"
    return RedirectResponse(f"/debts?msg={msg}", status_code=303)


@router.get("/debts/{debt_id}")
def debt_detail(
    debt_id: int,
    request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    debt = db.get(models.Debt, debt_id)
    if debt is None:
        raise HTTPException(404, "Borç bulunamadı")
    if not scoping.can_access_apartment(db, user, debt.apartment):
        raise HTTPException(403, "Bu borca erişim yetkiniz yok.")
    return templates.TemplateResponse(
        request, "finance/debt_detail.html", {"user": user, "debt": debt}
    )


@router.post("/debts/{debt_id}/pay")
def record_payment(
    debt_id: int,
    amount: str = Form(...),
    method: str = Form("cash"),
    paid_at: str = Form(...),
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    debt = db.get(models.Debt, debt_id)
    if debt is None:
        raise HTTPException(404, "Borç bulunamadı")
    if not scoping.can_access_apartment(db, user, debt.apartment):
        raise HTTPException(403, "Bu borca erişim yetkiniz yok.")
    value = parse_amount(amount)
    if value <= 0:
        return RedirectResponse(f"/debts/{debt_id}?err=Tutar sıfırdan büyük olmalı", status_code=303)
    db.add(
        models.Payment(
            debt_id=debt_id,
            amount=value,
            method=method,
            paid_at=date.fromisoformat(paid_at),
            received_by=user.id,
        )
    )
    db.commit()
    db.refresh(debt)
    finance_service.update_debt_status(db, debt)
    return RedirectResponse(f"/debts/{debt_id}?msg=Tahsilat kaydedildi", status_code=303)


# ---------- Tahsilatlar (Gelir) ----------

@router.get("/payments")
def list_payments(
    request: Request,
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    payments = scoping.scoped_payments(db, user)
    return templates.TemplateResponse(
        request, "finance/payments.html", {"user": user, "payments": payments}
    )


@router.post("/payments/{payment_id}/delete")
def delete_payment(
    payment_id: int,
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    payment = db.get(models.Payment, payment_id)
    if payment is None:
        raise HTTPException(404, "Tahsilat bulunamadı")
    debt = payment.debt
    db.delete(payment)
    db.commit()
    db.refresh(debt)
    finance_service.update_debt_status(db, debt)
    return RedirectResponse("/payments?msg=Tahsilat silindi", status_code=303)


# ---------- Giderler ----------

@router.get("/expenses")
def list_expenses(
    request: Request,
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    expenses = scoping.scoped_expenses(db, user)
    options = scope_options(db) if user.role == ROLE_SITE_MANAGER else []
    return templates.TemplateResponse(
        request,
        "finance/expenses.html",
        {"user": user, "expenses": expenses, "scope_options": options},
    )


@router.post("/expenses/new")
def create_expense(
    scope: str = Form(""),
    category: str = Form(...),
    amount: str = Form(...),
    expense_date: str = Form(...),
    description: str = Form(""),
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    if user.role == ROLE_BUILDING_MANAGER:
        if user.block is None:
            raise HTTPException(403, "Size atanmış bir blok yok.")
        site_id, block_id = user.block.site_id, user.block_id
    else:
        site_id, block_id = parse_scope(db, scope)
    db.add(
        models.Expense(
            site_id=site_id,
            block_id=block_id,
            category=category.strip(),
            amount=parse_amount(amount),
            expense_date=date.fromisoformat(expense_date),
            description=description.strip() or None,
            created_by=user.id,
        )
    )
    db.commit()
    return RedirectResponse("/expenses?msg=Gider kaydedildi", status_code=303)


@router.post("/expenses/{expense_id}/delete")
def delete_expense(
    expense_id: int,
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    expense = db.get(models.Expense, expense_id)
    if expense is None:
        raise HTTPException(404, "Gider bulunamadı")
    db.delete(expense)
    db.commit()
    return RedirectResponse("/expenses?msg=Gider silindi", status_code=303)
