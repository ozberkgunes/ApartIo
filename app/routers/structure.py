from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, scoping
from ..auth import get_current_user, require_role
from ..database import get_db
from ..models import ROLE_BUILDING_MANAGER, ROLE_SITE_MANAGER
from ..templating import templates

router = APIRouter()


# ---------- Siteler ----------

@router.get("/sites")
def list_sites(
    request: Request,
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    sites = db.scalars(select(models.Site).order_by(models.Site.name)).all()
    edit_id = request.query_params.get("edit")
    edit_site = db.get(models.Site, int(edit_id)) if edit_id and edit_id.isdigit() else None
    return templates.TemplateResponse(
        request, "structure/sites.html", {"user": user, "sites": sites, "edit_site": edit_site}
    )


@router.post("/sites/save")
def save_site(
    site_id: str = Form(""),
    name: str = Form(...),
    address: str = Form(""),
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    if site_id:
        site = db.get(models.Site, int(site_id))
        if site is None:
            raise HTTPException(404, "Site bulunamadı")
        site.name, site.address = name.strip(), address.strip() or None
        msg = "Site güncellendi"
    else:
        db.add(models.Site(name=name.strip(), address=address.strip() or None))
        msg = "Site oluşturuldu"
    db.commit()
    return RedirectResponse(f"/sites?msg={msg}", status_code=303)


@router.post("/sites/{site_id}/delete")
def delete_site(
    site_id: int,
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    site = db.get(models.Site, site_id)
    if site is None:
        raise HTTPException(404, "Site bulunamadı")
    if site.blocks:
        return RedirectResponse("/sites?err=Önce siteye bağlı blokları silin", status_code=303)
    db.delete(site)
    db.commit()
    return RedirectResponse("/sites?msg=Site silindi", status_code=303)


# ---------- Bloklar ----------

@router.get("/blocks")
def list_blocks(
    request: Request,
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)),
    db: Session = Depends(get_db),
):
    blocks = scoping.scoped_blocks(db, user)
    sites = db.scalars(select(models.Site).order_by(models.Site.name)).all()
    edit_id = request.query_params.get("edit")
    edit_block = None
    if user.role == ROLE_SITE_MANAGER and edit_id and edit_id.isdigit():
        edit_block = db.get(models.Block, int(edit_id))
    return templates.TemplateResponse(
        request,
        "structure/blocks.html",
        {"user": user, "blocks": blocks, "sites": sites, "edit_block": edit_block},
    )


@router.post("/blocks/save")
def save_block(
    block_id: str = Form(""),
    site_id: int = Form(...),
    name: str = Form(...),
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    if block_id:
        block = db.get(models.Block, int(block_id))
        if block is None:
            raise HTTPException(404, "Blok bulunamadı")
        block.site_id, block.name = site_id, name.strip()
        msg = "Blok güncellendi"
    else:
        db.add(models.Block(site_id=site_id, name=name.strip()))
        msg = "Blok oluşturuldu"
    db.commit()
    return RedirectResponse(f"/blocks?msg={msg}", status_code=303)


@router.post("/blocks/{block_id}/delete")
def delete_block(
    block_id: int,
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    block = db.get(models.Block, block_id)
    if block is None:
        raise HTTPException(404, "Blok bulunamadı")
    if block.apartments:
        return RedirectResponse("/blocks?err=Önce bloğa bağlı daireleri silin", status_code=303)
    db.delete(block)
    db.commit()
    return RedirectResponse("/blocks?msg=Blok silindi", status_code=303)


# ---------- Daireler ----------

@router.get("/apartments")
def list_apartments(
    request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    apartments = scoping.scoped_apartments(db, user)
    return templates.TemplateResponse(
        request, "structure/apartments.html", {"user": user, "apartments": apartments}
    )


@router.get("/apartments/new")
def new_apartment_form(
    request: Request,
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)),
    db: Session = Depends(get_db),
):
    blocks = scoping.scoped_blocks(db, user)
    return templates.TemplateResponse(
        request,
        "structure/apartment_form.html",
        {"user": user, "apartment": None, "blocks": blocks},
    )


@router.post("/apartments/save")
def save_apartment(
    apartment_id: str = Form(""),
    block_id: int = Form(...),
    floor_no: int = Form(...),
    number: str = Form(...),
    area_m2: str = Form(""),
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)),
    db: Session = Depends(get_db),
):
    if user.role == ROLE_BUILDING_MANAGER and block_id != user.block_id:
        raise HTTPException(403, "Sadece kendi bloğunuza daire ekleyebilirsiniz.")
    area = float(area_m2.replace(",", ".")) if area_m2.strip() else None
    if apartment_id:
        apartment = db.get(models.Apartment, int(apartment_id))
        if apartment is None:
            raise HTTPException(404, "Daire bulunamadı")
        if not scoping.can_access_apartment(db, user, apartment):
            raise HTTPException(403, "Bu daireye erişim yetkiniz yok.")
        apartment.block_id, apartment.floor_no = block_id, floor_no
        apartment.number, apartment.area_m2 = number.strip(), area
        msg = "Daire güncellendi"
    else:
        db.add(
            models.Apartment(
                block_id=block_id, floor_no=floor_no, number=number.strip(), area_m2=area
            )
        )
        msg = "Daire oluşturuldu"
    db.commit()
    return RedirectResponse(f"/apartments?msg={msg}", status_code=303)


@router.get("/apartments/{apartment_id}/edit")
def edit_apartment_form(
    apartment_id: int,
    request: Request,
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)),
    db: Session = Depends(get_db),
):
    apartment = db.get(models.Apartment, apartment_id)
    if apartment is None:
        raise HTTPException(404, "Daire bulunamadı")
    if not scoping.can_access_apartment(db, user, apartment):
        raise HTTPException(403, "Bu daireye erişim yetkiniz yok.")
    blocks = scoping.scoped_blocks(db, user)
    return templates.TemplateResponse(
        request,
        "structure/apartment_form.html",
        {"user": user, "apartment": apartment, "blocks": blocks},
    )


@router.post("/apartments/{apartment_id}/delete")
def delete_apartment(
    apartment_id: int,
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    apartment = db.get(models.Apartment, apartment_id)
    if apartment is None:
        raise HTTPException(404, "Daire bulunamadı")
    if apartment.debts or apartment.occupancies:
        return RedirectResponse(
            "/apartments?err=Borç veya sakin kaydı olan daire silinemez", status_code=303
        )
    db.delete(apartment)
    db.commit()
    return RedirectResponse("/apartments?msg=Daire silindi", status_code=303)


@router.get("/apartments/{apartment_id}")
def apartment_detail(
    apartment_id: int,
    request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    apartment = db.get(models.Apartment, apartment_id)
    if apartment is None:
        raise HTTPException(404, "Daire bulunamadı")
    if not scoping.can_access_apartment(db, user, apartment):
        raise HTTPException(403, "Bu daireye erişim yetkiniz yok.")
    residents = db.scalars(
        select(models.User)
        .where(models.User.role == models.ROLE_RESIDENT, models.User.is_active.is_(True))
        .order_by(models.User.full_name)
    ).all()
    return templates.TemplateResponse(
        request,
        "structure/apartment_detail.html",
        {"user": user, "apartment": apartment, "residents": residents},
    )


# ---------- Doğalgaz Abonelik ----------

@router.get("/gas-subscriptions")
def gas_subscriptions(
    request: Request,
    status: str = "",
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)),
    db: Session = Depends(get_db),
):
    apartments = scoping.scoped_apartments(db, user)
    counts = {
        "subscribed": sum(1 for a in apartments if a.gas_subscribed is True),
        "not_subscribed": sum(1 for a in apartments if a.gas_subscribed is False),
        "unknown": sum(1 for a in apartments if a.gas_subscribed is None),
    }
    if status == "subscribed":
        apartments = [a for a in apartments if a.gas_subscribed is True]
    elif status == "not_subscribed":
        apartments = [a for a in apartments if a.gas_subscribed is False]
    elif status == "unknown":
        apartments = [a for a in apartments if a.gas_subscribed is None]
    return templates.TemplateResponse(
        request,
        "structure/gas_subscriptions.html",
        {"user": user, "apartments": apartments, "counts": counts, "status_filter": status},
    )


@router.post("/gas-subscriptions/{apartment_id}/set")
def set_gas_subscription(
    apartment_id: int,
    value: str = Form(...),  # yes | no | unknown
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)),
    db: Session = Depends(get_db),
):
    apartment = db.get(models.Apartment, apartment_id)
    if apartment is None:
        raise HTTPException(404, "Daire bulunamadı")
    if not scoping.can_access_apartment(db, user, apartment):
        raise HTTPException(403, "Bu daireye erişim yetkiniz yok.")
    if value not in ("yes", "no", "unknown"):
        raise HTTPException(400, "Geçersiz değer")
    apartment.gas_subscribed = {"yes": True, "no": False, "unknown": None}[value]
    db.commit()
    return RedirectResponse("/gas-subscriptions?msg=Abonelik durumu güncellendi", status_code=303)
