from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import models, scoping
from ..auth import require_role
from ..database import get_db
from ..models import ROLE_BUILDING_MANAGER, ROLE_SITE_MANAGER
from ..services import notify as notify_service
from ..templating import templates
from .dues import parse_scope, scope_options

router = APIRouter()

managers_only = require_role(ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)


@router.get("/tasks")
def list_tasks(
    request: Request,
    status: str = "",
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    work_orders = scoping.scoped_work_orders(db, user)
    if status in models.WORK_STATUS_LABELS:
        work_orders = [w for w in work_orders if w.status == status]
    staff_list = [s for s in scoping.scoped_staff(db, user) if s.is_active]
    options = scope_options(db) if user.role == ROLE_SITE_MANAGER else []
    return templates.TemplateResponse(
        request,
        "tasks/list.html",
        {
            "user": user,
            "work_orders": work_orders,
            "staff_list": staff_list,
            "scope_options": options,
            "status_filter": status,
        },
    )


@router.post("/tasks/new")
def create_task(
    scope: str = Form(""),
    title: str = Form(...),
    description: str = Form(""),
    staff_id: str = Form(""),
    due_date: str = Form(""),
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
        models.WorkOrder(
            site_id=site_id,
            block_id=block_id,
            title=title.strip(),
            description=description.strip() or None,
            staff_id=int(staff_id) if staff_id else None,
            due_date=date.fromisoformat(due_date) if due_date else None,
            created_by=user.id,
        )
    )
    db.commit()
    return RedirectResponse("/tasks?msg=Görev oluşturuldu", status_code=303)


def _get_scoped_work_order(db: Session, user: models.User, work_order_id: int) -> models.WorkOrder:
    work_order = db.get(models.WorkOrder, work_order_id)
    if work_order is None:
        raise HTTPException(404, "Görev bulunamadı")
    if user.role == ROLE_BUILDING_MANAGER:
        site_id = user.block.site_id if user.block else -1
        in_scope = work_order.block_id == user.block_id or (
            work_order.block_id is None and work_order.site_id == site_id
        )
        if not in_scope:
            raise HTTPException(403, "Bu göreve erişim yetkiniz yok.")
    return work_order


def _sync_ticket_status(db: Session, work_order: models.WorkOrder, actor: models.User) -> None:
    """İş emri durumunu bağlı talebe yansıtır ve talep sahibine bildirim gönderir."""
    ticket = work_order.ticket
    if ticket is None:
        return
    new_status = None
    if work_order.status == "done":
        # Talebin tüm iş emirleri bittiyse talep çözülmüş sayılır
        if all(w.status == "done" for w in ticket.work_orders) and ticket.status in ("open", "in_progress"):
            new_status = "resolved"
    elif work_order.status == "in_progress":
        if ticket.status == "open":
            new_status = "in_progress"
    elif work_order.status == "todo":
        # İş emri yeniden açıldıysa çözülmüş talep de yeniden işleme alınır
        if ticket.status == "resolved":
            new_status = "in_progress"
    if new_status is None:
        return
    ticket.status = new_status
    db.commit()
    notify_service.notify(
        db,
        [ticket.created_by],
        f"Talebiniz güncellendi: {ticket.title}",
        f"Yeni durum: {ticket.status_label}",
        link=f"/tickets/{ticket.id}",
        exclude_user_id=actor.id,
    )


@router.post("/tasks/{work_order_id}/status")
def update_task_status(
    work_order_id: int,
    status: str = Form(...),
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    work_order = _get_scoped_work_order(db, user, work_order_id)
    if status not in models.WORK_STATUS_LABELS:
        raise HTTPException(400, "Geçersiz durum")
    work_order.status = status
    db.commit()
    _sync_ticket_status(db, work_order, user)
    return RedirectResponse("/tasks?msg=Görev durumu güncellendi", status_code=303)


@router.post("/tasks/{work_order_id}/delete")
def delete_task(
    work_order_id: int,
    user: models.User = Depends(require_role(ROLE_SITE_MANAGER)),
    db: Session = Depends(get_db),
):
    work_order = db.get(models.WorkOrder, work_order_id)
    if work_order is None:
        raise HTTPException(404, "Görev bulunamadı")
    db.delete(work_order)
    db.commit()
    return RedirectResponse("/tasks?msg=Görev silindi", status_code=303)
