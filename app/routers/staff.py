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


@router.get("/staff")
def list_staff(
    request: Request,
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)),
    db: Session = Depends(get_db),
):
    staff_list = scoping.scoped_staff(db, user)
    sites = db.scalars(select(models.Site).order_by(models.Site.name)).all()
    edit_id = request.query_params.get("edit")
    edit_staff = None
    if user.role == ROLE_SITE_MANAGER and edit_id and edit_id.isdigit():
        edit_staff = db.get(models.Staff, int(edit_id))
    return templates.TemplateResponse(
        request,
        "staff/list.html",
        {"user": user, "staff_list": staff_list, "sites": sites, "edit_staff": edit_staff},
    )


@router.post("/staff/save")
def save_staff(
    staff_id: str = Form(""),
    site_id: int = Form(...),
    full_name: str = Form(...),
    title: str = Form(...),
    phone: str = Form(""),
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    if staff_id:
        staff = db.get(models.Staff, int(staff_id))
        if staff is None:
            raise HTTPException(404, "Personel bulunamadı")
        staff.site_id, staff.full_name = site_id, full_name.strip()
        staff.title, staff.phone = title.strip(), phone.strip() or None
        msg = "Personel güncellendi"
    else:
        db.add(
            models.Staff(
                site_id=site_id,
                full_name=full_name.strip(),
                title=title.strip(),
                phone=phone.strip() or None,
            )
        )
        msg = "Personel eklendi"
    db.commit()
    return RedirectResponse(f"/staff?msg={msg}", status_code=303)


@router.post("/staff/{staff_id}/toggle")
def toggle_staff(
    staff_id: int,
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    staff = db.get(models.Staff, staff_id)
    if staff is None:
        raise HTTPException(404, "Personel bulunamadı")
    staff.is_active = not staff.is_active
    db.commit()
    msg = "Personel aktifleştirildi" if staff.is_active else "Personel pasifleştirildi"
    return RedirectResponse(f"/staff?msg={msg}", status_code=303)
