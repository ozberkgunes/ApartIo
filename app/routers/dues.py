from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, scoping
from ..auth import require_role
from ..database import get_db
from ..models import ROLE_BUILDING_MANAGER, ROLE_SITE_MANAGER
from ..services import finance
from ..services import notify as notify_service
from ..templating import templates

router = APIRouter()

managers_only = require_role(ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)


def parse_amount(raw: str) -> Decimal:
    try:
        return Decimal(raw.strip().replace(".", "").replace(",", ".") if "," in raw else raw.strip())
    except InvalidOperation:
        raise HTTPException(400, "Geçersiz tutar")


def scope_options(db: Session) -> list[dict]:
    options = []
    for site in db.scalars(select(models.Site).order_by(models.Site.name)):
        options.append({"value": f"site:{site.id}", "label": f"{site.name} (tüm site)"})
        for block in site.blocks:
            options.append({"value": f"block:{block.id}", "label": block.full_name})
    return options


def parse_scope(db: Session, scope: str) -> tuple[int, int | None]:
    kind, _, raw_id = scope.partition(":")
    if not raw_id.isdigit():
        raise HTTPException(400, "Geçersiz kapsam")
    if kind == "site":
        site = db.get(models.Site, int(raw_id))
        if site is None:
            raise HTTPException(404, "Site bulunamadı")
        return site.id, None
    if kind == "block":
        block = db.get(models.Block, int(raw_id))
        if block is None:
            raise HTTPException(404, "Blok bulunamadı")
        return block.site_id, block.id
    raise HTTPException(400, "Geçersiz kapsam")


def _surcharge_sites(db: Session, user: models.User) -> list[models.Site]:
    if user.role == ROLE_SITE_MANAGER:
        return list(db.scalars(select(models.Site)))
    return [user.block.site] if user.block else []


@router.get("/dues")
def list_dues(
    request: Request,
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    dues_list = scoping.scoped_dues(db, user)
    options = scope_options(db) if user.role == ROLE_SITE_MANAGER else []
    surcharge_proposals = []
    for site in _surcharge_sites(db, user):
        proposal = finance.surcharge_proposal(db, site)
        if proposal:
            surcharge_proposals.append({"site": site, **proposal})
    return templates.TemplateResponse(
        request,
        "dues/list.html",
        {
            "user": user,
            "dues_list": dues_list,
            "scope_options": options,
            "surcharge_proposals": surcharge_proposals,
        },
    )


@router.post("/dues/surcharge/apply")
def apply_surcharge(
    site_id: int = Form(...),
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    site = db.get(models.Site, site_id)
    if site is None:
        raise HTTPException(404, "Site bulunamadı")
    result = finance.apply_surcharge(db, site)
    if result is None:
        return RedirectResponse(
            "/dues?msg=Ek aidat koşulları oluşmadı (uygulanmış olabilir)", status_code=303
        )
    dues, created = result
    responsible_ids = {
        uid for debt in created if (uid := notify_service.responsible_user_id(debt.apartment))
    }
    notify_service.notify(
        db,
        responsible_ids,
        f"Ek aidat: {dues.period}",
        f"Gider açığı nedeniyle {dues.period} dönemi için daire başına "
        f"{dues.amount} ₺ ek aidat tahakkuk ettirildi (KMK m.20).",
        link="/debts",
    )
    return RedirectResponse(
        f"/dues?msg={len(created)} daireye ek aidat borcu oluşturuldu", status_code=303
    )


@router.post("/dues/new")
def create_dues(
    scope: str = Form(""),
    period: str = Form(...),
    amount: str = Form(...),
    due_date: str = Form(...),
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
    dues = models.DuesDefinition(
        site_id=site_id,
        block_id=block_id,
        period=period,
        amount=parse_amount(amount),
        due_date=date.fromisoformat(due_date),
        description=description.strip() or None,
    )
    db.add(dues)
    db.commit()
    return RedirectResponse("/dues?msg=Aidat tanımı oluşturuldu", status_code=303)


@router.post("/dues/{dues_id}/generate")
def generate_debts(
    dues_id: int,
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    dues = db.get(models.DuesDefinition, dues_id)
    if dues is None:
        raise HTTPException(404, "Aidat tanımı bulunamadı")
    if user.role == ROLE_BUILDING_MANAGER and dues.block_id != user.block_id:
        raise HTTPException(403, "Bu aidat tanımı için borç üretme yetkiniz yok.")
    created = finance.generate_debts_for_dues(db, dues)
    if created:
        responsible_ids = {
            uid for debt in created if (uid := notify_service.responsible_user_id(debt.apartment))
        }
        notify_service.notify(
            db,
            responsible_ids,
            f"Yeni aidat borcu: {dues.period}",
            f"{dues.scope_label} için aidat borcunuz oluşturuldu.",
            link="/debts",
        )
        msg = f"{len(created)} daireye borç oluşturuldu"
    else:
        msg = "Yeni borç oluşturulmadı (tüm daireler için zaten üretilmiş)"
    return RedirectResponse(f"/dues?msg={msg}", status_code=303)
