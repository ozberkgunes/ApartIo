from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import models, scoping
from ..auth import get_current_user, require_role
from ..database import get_db
from ..models import ROLE_BUILDING_MANAGER, ROLE_SITE_MANAGER
from ..services import notify as notify_service
from ..templating import templates

router = APIRouter()

managers_only = require_role(ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)


@router.get("/tickets")
def list_tickets(
    request: Request,
    status: str = "",
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tickets = scoping.scoped_tickets(db, user)
    if status in models.TICKET_STATUS_LABELS:
        tickets = [t for t in tickets if t.status == status]
    return templates.TemplateResponse(
        request, "tickets/list.html", {"user": user, "tickets": tickets, "status_filter": status}
    )


@router.get("/tickets/new")
def new_ticket_form(
    request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    apartments = scoping.scoped_apartments(db, user)
    if not apartments:
        raise HTTPException(403, "Talep oluşturabileceğiniz bir daire kaydınız yok.")
    return templates.TemplateResponse(
        request, "tickets/form.html", {"user": user, "apartments": apartments}
    )


@router.post("/tickets/new")
def create_ticket(
    apartment_id: int = Form(...),
    category: str = Form(...),
    priority: str = Form("normal"),
    title: str = Form(...),
    description: str = Form(...),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    apartment = db.get(models.Apartment, apartment_id)
    if apartment is None:
        raise HTTPException(404, "Daire bulunamadı")
    if not scoping.can_access_apartment(db, user, apartment):
        raise HTTPException(403, "Bu daire için talep oluşturamazsınız.")
    if category not in models.TICKET_CATEGORY_LABELS or priority not in models.TICKET_PRIORITY_LABELS:
        raise HTTPException(400, "Geçersiz kategori veya öncelik")
    ticket = models.Ticket(
        apartment_id=apartment_id,
        created_by=user.id,
        category=category,
        priority=priority,
        title=title.strip(),
        description=description.strip(),
    )
    db.add(ticket)
    db.commit()
    notify_service.notify(
        db,
        notify_service.managers_for_apartment(db, apartment),
        f"Yeni talep: {ticket.title}",
        f"{apartment.label} — {ticket.category_label}",
        link=f"/tickets/{ticket.id}",
        exclude_user_id=user.id,
    )
    return RedirectResponse(f"/tickets/{ticket.id}?msg=Talep oluşturuldu", status_code=303)


@router.get("/tickets/{ticket_id}")
def ticket_detail(
    ticket_id: int,
    request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ticket = db.get(models.Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(404, "Talep bulunamadı")
    if not scoping.can_access_ticket(db, user, ticket):
        raise HTTPException(403, "Bu talebe erişim yetkiniz yok.")
    staff_list = scoping.scoped_staff(db, user) if user.role in models.MANAGER_ROLES else []
    return templates.TemplateResponse(
        request,
        "tickets/detail.html",
        {"user": user, "ticket": ticket, "staff_list": staff_list},
    )


@router.post("/tickets/{ticket_id}/status")
def update_ticket_status(
    ticket_id: int,
    status: str = Form(...),
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    ticket = db.get(models.Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(404, "Talep bulunamadı")
    if not scoping.can_access_ticket(db, user, ticket):
        raise HTTPException(403, "Bu talebe erişim yetkiniz yok.")
    if status not in models.TICKET_STATUS_LABELS:
        raise HTTPException(400, "Geçersiz durum")
    ticket.status = status
    db.commit()
    notify_service.notify(
        db,
        [ticket.created_by],
        f"Talebiniz güncellendi: {ticket.title}",
        f"Yeni durum: {ticket.status_label}",
        link=f"/tickets/{ticket.id}",
        exclude_user_id=user.id,
    )
    return RedirectResponse(f"/tickets/{ticket_id}?msg=Durum güncellendi", status_code=303)


@router.post("/tickets/{ticket_id}/comment")
def add_ticket_comment(
    ticket_id: int,
    body: str = Form(...),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ticket = db.get(models.Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(404, "Talep bulunamadı")
    if not scoping.can_access_ticket(db, user, ticket):
        raise HTTPException(403, "Bu talebe erişim yetkiniz yok.")
    db.add(models.TicketComment(ticket_id=ticket_id, user_id=user.id, body=body.strip()))
    db.commit()
    targets = notify_service.managers_for_apartment(db, ticket.apartment) | {ticket.created_by}
    notify_service.notify(
        db,
        targets,
        f"Talebe yorum eklendi: {ticket.title}",
        body.strip()[:200],
        link=f"/tickets/{ticket.id}",
        exclude_user_id=user.id,
    )
    return RedirectResponse(f"/tickets/{ticket_id}?msg=Yorum eklendi", status_code=303)


@router.post("/tickets/{ticket_id}/workorder")
def create_work_order_from_ticket(
    ticket_id: int,
    staff_id: str = Form(""),
    due_date: str = Form(""),
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    ticket = db.get(models.Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(404, "Talep bulunamadı")
    if not scoping.can_access_ticket(db, user, ticket):
        raise HTTPException(403, "Bu talebe erişim yetkiniz yok.")
    block = ticket.apartment.block
    db.add(
        models.WorkOrder(
            site_id=block.site_id,
            block_id=block.id,
            ticket_id=ticket.id,
            staff_id=int(staff_id) if staff_id else None,
            title=ticket.title,
            description=f"{ticket.apartment.label} — {ticket.description}",
            due_date=date.fromisoformat(due_date) if due_date else None,
            created_by=user.id,
        )
    )
    if ticket.status == "open":
        ticket.status = "in_progress"
    db.commit()
    return RedirectResponse(f"/tickets/{ticket_id}?msg=İş emri oluşturuldu", status_code=303)
