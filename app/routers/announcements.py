from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import models, scoping
from ..auth import get_current_user, require_role
from ..database import get_db
from ..models import ROLE_BUILDING_MANAGER, ROLE_SITE_MANAGER
from ..services import notify as notify_service
from ..templating import templates
from .dues import parse_scope, scope_options

router = APIRouter()

managers_only = require_role(ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)


@router.get("/announcements")
def list_announcements(
    request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    announcements = scoping.scoped_announcements(db, user)
    options = scope_options(db) if user.role == ROLE_SITE_MANAGER else []
    return templates.TemplateResponse(
        request,
        "announcements/list.html",
        {"user": user, "announcements": announcements, "scope_options": options},
    )


@router.post("/announcements/new")
def create_announcement(
    scope: str = Form(""),
    title: str = Form(...),
    body: str = Form(...),
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    if user.role == ROLE_BUILDING_MANAGER:
        if user.block is None:
            raise HTTPException(403, "Size atanmış bir blok yok.")
        site_id, block_id = user.block.site_id, user.block_id
    else:
        site_id, block_id = parse_scope(db, scope)
    announcement = models.Announcement(
        site_id=site_id,
        block_id=block_id,
        title=title.strip(),
        body=body.strip(),
        created_by=user.id,
    )
    db.add(announcement)
    db.commit()
    notify_service.notify(
        db,
        notify_service.users_in_scope(db, site_id, block_id),
        f"Yeni duyuru: {announcement.title}",
        announcement.body[:200],
        link="/announcements",
        exclude_user_id=user.id,
    )
    return RedirectResponse("/announcements?msg=Duyuru yayınlandı", status_code=303)


@router.post("/announcements/{announcement_id}/delete")
def delete_announcement(
    announcement_id: int,
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    announcement = db.get(models.Announcement, announcement_id)
    if announcement is None:
        raise HTTPException(404, "Duyuru bulunamadı")
    if user.role != ROLE_SITE_MANAGER and announcement.created_by != user.id:
        raise HTTPException(403, "Sadece kendi duyurunuzu silebilirsiniz.")
    db.delete(announcement)
    db.commit()
    return RedirectResponse("/announcements?msg=Duyuru silindi", status_code=303)
