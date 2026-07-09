from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import desc, select, update
from sqlalchemy.orm import Session

from .. import models
from ..auth import get_current_user
from ..database import get_db
from ..services import notify as notify_service
from ..templating import templates

router = APIRouter()


@router.get("/notifications")
def list_notifications(
    request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notifications = db.scalars(
        select(models.Notification)
        .where(models.Notification.user_id == user.id)
        .order_by(desc(models.Notification.created_at))
        .limit(100)
    ).all()
    return templates.TemplateResponse(
        request, "notifications/list.html", {"user": user, "notifications": notifications}
    )


@router.get("/notifications/unread-count")
def unread_count(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"count": notify_service.unread_count(db, user.id)}


@router.post("/notifications/read-all")
def mark_all_read(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.execute(
        update(models.Notification)
        .where(models.Notification.user_id == user.id, models.Notification.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()
    return RedirectResponse("/notifications?msg=Tümü okundu işaretlendi", status_code=303)


@router.get("/notifications/{notification_id}/go")
def open_notification(
    notification_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = db.get(models.Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(404, "Bildirim bulunamadı")
    notification.is_read = True
    db.commit()
    return RedirectResponse(notification.link or "/notifications", status_code=303)
