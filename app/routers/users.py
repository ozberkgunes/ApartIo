from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, scoping
from ..auth import hash_password, require_role
from ..database import get_db
from ..models import ROLE_BUILDING_MANAGER, ROLE_SITE_MANAGER
from ..templating import templates

router = APIRouter()


@router.get("/users")
def list_users(
    request: Request,
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)),
    db: Session = Depends(get_db),
):
    users = scoping.scoped_users(db, user)
    return templates.TemplateResponse(request, "users/list.html", {"user": user, "users": users})


@router.get("/users/new")
def new_user_form(
    request: Request,
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    blocks = db.scalars(select(models.Block)).all()
    return templates.TemplateResponse(
        request, "users/form.html", {"user": user, "edit_user": None, "blocks": blocks}
    )


@router.post("/users/new")
def create_user(
    email: str = Form(...),
    full_name: str = Form(...),
    phone: str = Form(""),
    role: str = Form(...),
    block_id: str = Form(""),
    password: str = Form(...),
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    if db.scalar(select(models.User).where(models.User.email == email)):
        return RedirectResponse("/users/new?err=Bu e-posta zaten kayıtlı", status_code=303)
    if role not in models.ROLE_LABELS:
        raise HTTPException(400, "Geçersiz rol")
    new_user = models.User(
        email=email,
        full_name=full_name.strip(),
        phone=phone.strip() or None,
        role=role,
        block_id=int(block_id) if role == ROLE_BUILDING_MANAGER and block_id else None,
        password_hash=hash_password(password),
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse("/users?msg=Kullanıcı oluşturuldu", status_code=303)


@router.get("/users/{user_id}/edit")
def edit_user_form(
    user_id: int,
    request: Request,
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    edit_user = db.get(models.User, user_id)
    if edit_user is None:
        raise HTTPException(404, "Kullanıcı bulunamadı")
    blocks = db.scalars(select(models.Block)).all()
    return templates.TemplateResponse(
        request, "users/form.html", {"user": user, "edit_user": edit_user, "blocks": blocks}
    )


@router.post("/users/{user_id}/edit")
def update_user(
    user_id: int,
    email: str = Form(...),
    full_name: str = Form(...),
    phone: str = Form(""),
    role: str = Form(...),
    block_id: str = Form(""),
    password: str = Form(""),
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    edit_user = db.get(models.User, user_id)
    if edit_user is None:
        raise HTTPException(404, "Kullanıcı bulunamadı")
    if role not in models.ROLE_LABELS:
        raise HTTPException(400, "Geçersiz rol")
    email = email.strip().lower()
    existing = db.scalar(select(models.User).where(models.User.email == email))
    if existing and existing.id != user_id:
        return RedirectResponse(
            f"/users/{user_id}/edit?err=Bu e-posta zaten kayıtlı", status_code=303
        )
    edit_user.email = email
    edit_user.full_name = full_name.strip()
    edit_user.phone = phone.strip() or None
    edit_user.role = role
    edit_user.block_id = int(block_id) if role == ROLE_BUILDING_MANAGER and block_id else None
    if password:
        edit_user.password_hash = hash_password(password)
    db.commit()
    return RedirectResponse("/users?msg=Kullanıcı güncellendi", status_code=303)


@router.post("/users/{user_id}/toggle")
def toggle_user(
    user_id: int,
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    target = db.get(models.User, user_id)
    if target is None:
        raise HTTPException(404, "Kullanıcı bulunamadı")
    if target.id == user.id:
        return RedirectResponse("/users?err=Kendi hesabınızı pasifleştiremezsiniz", status_code=303)
    target.is_active = not target.is_active
    db.commit()
    msg = "Kullanıcı aktifleştirildi" if target.is_active else "Kullanıcı pasifleştirildi"
    return RedirectResponse(f"/users?msg={msg}", status_code=303)
