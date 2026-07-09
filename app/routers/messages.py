from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import models, scoping
from ..auth import get_current_user
from ..database import get_db
from ..services import notify as notify_service
from ..templating import templates

router = APIRouter()


@router.get("/messages")
def list_threads(
    request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    threads = scoping.scoped_threads(db, user)
    return templates.TemplateResponse(
        request, "messages/list.html", {"user": user, "threads": threads}
    )


@router.get("/messages/new")
def new_thread_form(
    request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    recipients = scoping.message_recipients(db, user)
    return templates.TemplateResponse(
        request, "messages/new.html", {"user": user, "recipients": recipients}
    )


@router.post("/messages/new")
def create_thread(
    recipient_id: int = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allowed_ids = {r.id for r in scoping.message_recipients(db, user)}
    if recipient_id not in allowed_ids:
        raise HTTPException(403, "Bu kişiye mesaj gönderemezsiniz.")
    thread = models.MessageThread(
        subject=subject.strip(), created_by=user.id, recipient_id=recipient_id
    )
    db.add(thread)
    db.flush()
    db.add(models.Message(thread_id=thread.id, sender_id=user.id, body=body.strip()))
    db.commit()
    notify_service.notify(
        db,
        [recipient_id],
        f"Yeni mesaj: {thread.subject}",
        f"{user.full_name} size mesaj gönderdi.",
        link=f"/messages/{thread.id}",
    )
    return RedirectResponse(f"/messages/{thread.id}?msg=Mesaj gönderildi", status_code=303)


def _get_thread(db: Session, user: models.User, thread_id: int) -> models.MessageThread:
    thread = db.get(models.MessageThread, thread_id)
    if thread is None:
        raise HTTPException(404, "Mesaj bulunamadı")
    if user.id not in (thread.created_by, thread.recipient_id):
        raise HTTPException(403, "Bu mesajlaşmaya erişim yetkiniz yok.")
    return thread


@router.get("/messages/{thread_id}")
def thread_detail(
    thread_id: int,
    request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    thread = _get_thread(db, user, thread_id)
    # Karşı tarafın mesajlarını okundu işaretle
    for message in thread.messages:
        if message.sender_id != user.id and message.read_at is None:
            message.read_at = datetime.now()
    db.commit()
    return templates.TemplateResponse(
        request, "messages/thread.html", {"user": user, "thread": thread}
    )


@router.post("/messages/{thread_id}/reply")
def reply_thread(
    thread_id: int,
    body: str = Form(...),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    thread = _get_thread(db, user, thread_id)
    db.add(models.Message(thread_id=thread.id, sender_id=user.id, body=body.strip()))
    db.commit()
    notify_service.notify(
        db,
        [thread.other_user(user.id).id],
        f"Yeni mesaj: {thread.subject}",
        f"{user.full_name} yanıt yazdı.",
        link=f"/messages/{thread.id}",
    )
    return RedirectResponse(f"/messages/{thread_id}", status_code=303)
