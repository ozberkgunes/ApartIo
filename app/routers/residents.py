from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, scoping
from ..auth import require_role
from ..database import get_db
from ..models import ROLE_BUILDING_MANAGER, ROLE_SITE_MANAGER
from ..templating import templates

router = APIRouter()

managers_only = require_role(ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)


@router.get("/residents")
def list_residents(
    request: Request,
    q: str = "",
    occ_type: str = "",
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    occupancies = scoping.scoped_occupancies(db, user, active_only=True)
    if occ_type in models.OCC_TYPE_LABELS:
        occupancies = [o for o in occupancies if o.type == occ_type]
    if q.strip():
        needle = q.strip().lower()
        occupancies = [o for o in occupancies if needle in o.user.full_name.lower()]
    apartments = scoping.scoped_apartments(db, user)
    residents = db.scalars(
        select(models.User)
        .where(models.User.role == models.ROLE_RESIDENT, models.User.is_active.is_(True))
        .order_by(models.User.full_name)
    ).all()
    return templates.TemplateResponse(
        request,
        "residents/list.html",
        {
            "user": user,
            "occupancies": occupancies,
            "apartments": apartments,
            "residents": residents,
            "q_filter": q,
            "occ_type_filter": occ_type if occ_type in models.OCC_TYPE_LABELS else "",
        },
    )


@router.post("/residents/add")
def add_occupancy(
    apartment_id: int = Form(...),
    user_id: int = Form(...),
    occ_type: str = Form(...),
    start_date: str = Form(...),
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    apartment = db.get(models.Apartment, apartment_id)
    if apartment is None:
        raise HTTPException(404, "Daire bulunamadı")
    if not scoping.can_access_apartment(db, user, apartment):
        raise HTTPException(403, "Bu daireye erişim yetkiniz yok.")
    if occ_type not in models.OCC_TYPE_LABELS:
        raise HTTPException(400, "Geçersiz tip")
    if apartment._active_by_type(occ_type):
        label = models.OCC_TYPE_LABELS[occ_type]
        return RedirectResponse(
            f"/residents?err=Bu dairede zaten aktif bir {label} kaydı var", status_code=303
        )
    db.add(
        models.Occupancy(
            apartment_id=apartment_id,
            user_id=user_id,
            type=occ_type,
            start_date=date.fromisoformat(start_date),
        )
    )
    db.commit()
    return RedirectResponse("/residents?msg=Kayıt eklendi", status_code=303)


@router.post("/residents/{occupancy_id}/end")
def end_occupancy(
    occupancy_id: int,
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    occupancy = db.get(models.Occupancy, occupancy_id)
    if occupancy is None:
        raise HTTPException(404, "Kayıt bulunamadı")
    if not scoping.can_access_apartment(db, user, occupancy.apartment):
        raise HTTPException(403, "Bu daireye erişim yetkiniz yok.")
    occupancy.end_date = date.today()
    db.commit()
    return RedirectResponse("/residents?msg=Kayıt sonlandırıldı", status_code=303)
