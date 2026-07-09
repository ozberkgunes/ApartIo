"""Rol bazlı veri kapsamı: her sorgu kullanıcının görebileceği kayıtlarla sınırlanır.

- site_manager: filtre yok (tüm veriler)
- building_manager: sadece atandığı blok (user.block_id)
- resident: sadece aktif Occupancy kaydı olduğu daireler
"""

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.orm import Session

from . import models
from .models import (
    Announcement,
    Apartment,
    Block,
    Debt,
    Document,
    DuesDefinition,
    Expense,
    MessageThread,
    Occupancy,
    Payment,
    Staff,
    Ticket,
    User,
    WorkOrder,
    ROLE_BUILDING_MANAGER,
    ROLE_RESIDENT,
    ROLE_SITE_MANAGER,
)


def _apartment_filter(q, user: User):
    if user.role == ROLE_BUILDING_MANAGER:
        return q.where(Apartment.block_id == user.block_id)
    if user.role == ROLE_RESIDENT:
        return q.join(Occupancy, Occupancy.apartment_id == Apartment.id).where(
            Occupancy.user_id == user.id, Occupancy.end_date.is_(None)
        )
    return q


def scoped_apartments(db: Session, user: User) -> list[Apartment]:
    q = select(Apartment).join(Block, Apartment.block_id == Block.id)
    q = _apartment_filter(q, user)
    q = q.order_by(Block.site_id, Block.name, Apartment.floor_no, Apartment.number)
    return list(db.scalars(q).unique())


def can_access_apartment(db: Session, user: User, apartment: Apartment) -> bool:
    if user.role == ROLE_SITE_MANAGER:
        return True
    if user.role == ROLE_BUILDING_MANAGER:
        return apartment.block_id == user.block_id
    return any(o.user_id == user.id for o in apartment.active_occupancies)


def scoped_blocks(db: Session, user: User) -> list[Block]:
    if user.role == ROLE_SITE_MANAGER:
        return list(db.scalars(select(Block).order_by(Block.site_id, Block.name)))
    if user.role == ROLE_BUILDING_MANAGER:
        return [user.block] if user.block else []
    return sorted({a.block for a in scoped_apartments(db, user)}, key=lambda b: b.id)


def scoped_users(db: Session, user: User) -> list[User]:
    if user.role == ROLE_SITE_MANAGER:
        return list(db.scalars(select(User).order_by(User.full_name)))
    if user.role == ROLE_BUILDING_MANAGER:
        q = (
            select(User)
            .join(Occupancy, Occupancy.user_id == User.id)
            .join(Apartment, Occupancy.apartment_id == Apartment.id)
            .where(Apartment.block_id == user.block_id, Occupancy.end_date.is_(None))
            .distinct()
            .order_by(User.full_name)
        )
        return list(db.scalars(q))
    return [user]


def scoped_debts(db: Session, user: User) -> list[Debt]:
    q = select(Debt).join(Apartment, Debt.apartment_id == Apartment.id)
    q = _apartment_filter(q, user)
    q = q.order_by(desc(Debt.due_date), desc(Debt.id))
    return list(db.scalars(q).unique())


def scoped_payments(db: Session, user: User) -> list[Payment]:
    q = (
        select(Payment)
        .join(Debt, Payment.debt_id == Debt.id)
        .join(Apartment, Debt.apartment_id == Apartment.id)
    )
    q = _apartment_filter(q, user)
    q = q.order_by(desc(Payment.paid_at), desc(Payment.id))
    return list(db.scalars(q).unique())


def scoped_occupancies(db: Session, user: User, active_only: bool = True) -> list[Occupancy]:
    q = select(Occupancy).join(Apartment, Occupancy.apartment_id == Apartment.id)
    q = _apartment_filter(q, user) if user.role != ROLE_RESIDENT else q.where(Occupancy.user_id == user.id)
    if active_only:
        q = q.where(Occupancy.end_date.is_(None))
    q = q.order_by(Apartment.block_id, Apartment.floor_no, Apartment.number)
    return list(db.scalars(q).unique())


def _resident_scope_ids(db: Session, user: User) -> tuple[list[int], list[int]]:
    apartments = scoped_apartments(db, user)
    block_ids = list({a.block_id for a in apartments})
    site_ids = list({a.block.site_id for a in apartments})
    return block_ids, site_ids


def scoped_dues(db: Session, user: User) -> list[DuesDefinition]:
    q = select(DuesDefinition).order_by(desc(DuesDefinition.period), desc(DuesDefinition.id))
    if user.role == ROLE_BUILDING_MANAGER:
        site_id = user.block.site_id if user.block else -1
        q = q.where(
            or_(
                DuesDefinition.block_id == user.block_id,
                and_(DuesDefinition.block_id.is_(None), DuesDefinition.site_id == site_id),
            )
        )
    elif user.role == ROLE_RESIDENT:
        block_ids, site_ids = _resident_scope_ids(db, user)
        q = q.where(
            or_(
                DuesDefinition.block_id.in_(block_ids),
                and_(DuesDefinition.block_id.is_(None), DuesDefinition.site_id.in_(site_ids)),
            )
        )
    return list(db.scalars(q))


def scoped_expenses(db: Session, user: User) -> list[Expense]:
    q = select(Expense).order_by(desc(Expense.expense_date), desc(Expense.id))
    if user.role == ROLE_BUILDING_MANAGER:
        site_id = user.block.site_id if user.block else -1
        q = q.where(
            or_(
                Expense.block_id == user.block_id,
                and_(Expense.block_id.is_(None), Expense.site_id == site_id),
            )
        )
    elif user.role == ROLE_RESIDENT:
        block_ids, site_ids = _resident_scope_ids(db, user)
        q = q.where(
            or_(
                Expense.block_id.in_(block_ids),
                and_(Expense.block_id.is_(None), Expense.site_id.in_(site_ids)),
            )
        )
    return list(db.scalars(q))


def scoped_tickets(db: Session, user: User) -> list[Ticket]:
    q = select(Ticket)
    if user.role == ROLE_BUILDING_MANAGER:
        q = q.join(Apartment, Ticket.apartment_id == Apartment.id).where(
            Apartment.block_id == user.block_id
        )
    elif user.role == ROLE_RESIDENT:
        apartment_ids = [a.id for a in scoped_apartments(db, user)]
        q = q.where(
            or_(Ticket.created_by == user.id, Ticket.apartment_id.in_(apartment_ids))
        )
    q = q.order_by(desc(Ticket.created_at))
    return list(db.scalars(q).unique())


def can_access_ticket(db: Session, user: User, ticket: Ticket) -> bool:
    if ticket.created_by == user.id:
        return True
    return can_access_apartment(db, user, ticket.apartment)


def scoped_staff(db: Session, user: User) -> list[Staff]:
    q = select(Staff).order_by(Staff.full_name)
    if user.role == ROLE_BUILDING_MANAGER:
        site_id = user.block.site_id if user.block else -1
        q = q.where(Staff.site_id == site_id)
    elif user.role == ROLE_RESIDENT:
        return []
    return list(db.scalars(q))


def scoped_work_orders(db: Session, user: User) -> list[WorkOrder]:
    q = select(WorkOrder).order_by(desc(WorkOrder.created_at))
    if user.role == ROLE_BUILDING_MANAGER:
        site_id = user.block.site_id if user.block else -1
        q = q.where(
            or_(
                WorkOrder.block_id == user.block_id,
                and_(WorkOrder.block_id.is_(None), WorkOrder.site_id == site_id),
            )
        )
    elif user.role == ROLE_RESIDENT:
        return []
    return list(db.scalars(q))


def scoped_documents(db: Session, user: User) -> list[Document]:
    q = select(Document).order_by(desc(Document.created_at))
    if user.role == ROLE_BUILDING_MANAGER:
        site_id = user.block.site_id if user.block else -1
        q = q.where(
            or_(
                Document.block_id == user.block_id,
                and_(Document.block_id.is_(None), Document.site_id == site_id),
            )
        )
    elif user.role == ROLE_RESIDENT:
        block_ids, site_ids = _resident_scope_ids(db, user)
        q = q.where(
            Document.is_public.is_(True),
            or_(
                Document.block_id.in_(block_ids),
                and_(Document.block_id.is_(None), Document.site_id.in_(site_ids)),
            ),
        )
    return list(db.scalars(q))


def can_access_document(db: Session, user: User, document: Document) -> bool:
    if user.role == ROLE_SITE_MANAGER:
        return True
    if user.role == ROLE_BUILDING_MANAGER:
        site_id = user.block.site_id if user.block else -1
        return document.block_id == user.block_id or (
            document.block_id is None and document.site_id == site_id
        )
    if not document.is_public:
        return False
    block_ids, site_ids = _resident_scope_ids(db, user)
    return document.block_id in block_ids or (
        document.block_id is None and document.site_id in site_ids
    )


def scoped_threads(db: Session, user: User) -> list[MessageThread]:
    q = (
        select(MessageThread)
        .where(
            or_(MessageThread.created_by == user.id, MessageThread.recipient_id == user.id)
        )
        .order_by(desc(MessageThread.id))
    )
    return list(db.scalars(q))


def message_recipients(db: Session, user: User) -> list[User]:
    """Kullanıcının yeni mesaj başlatabileceği kişiler."""
    if user.role == ROLE_SITE_MANAGER:
        q = select(User).where(User.id != user.id, User.is_active.is_(True)).order_by(User.full_name)
        return list(db.scalars(q))
    if user.role == ROLE_BUILDING_MANAGER:
        recipients = {u.id: u for u in scoped_users(db, user)}
        for sm in db.scalars(
            select(User).where(User.role == ROLE_SITE_MANAGER, User.is_active.is_(True))
        ):
            recipients[sm.id] = sm
        recipients.pop(user.id, None)
        return sorted(recipients.values(), key=lambda u: u.full_name)
    # resident: site yöneticileri + oturduğu blokların yöneticileri
    block_ids, _ = _resident_scope_ids(db, user)
    q = select(User).where(
        User.is_active.is_(True),
        or_(
            User.role == ROLE_SITE_MANAGER,
            and_(User.role == ROLE_BUILDING_MANAGER, User.block_id.in_(block_ids)),
        ),
    ).order_by(User.full_name)
    return list(db.scalars(q))


def scoped_announcements(db: Session, user: User) -> list[Announcement]:
    q = select(Announcement).order_by(desc(Announcement.created_at))
    if user.role == ROLE_BUILDING_MANAGER:
        site_id = user.block.site_id if user.block else -1
        q = q.where(
            or_(
                Announcement.block_id == user.block_id,
                and_(Announcement.block_id.is_(None), Announcement.site_id == site_id),
            )
        )
    elif user.role == ROLE_RESIDENT:
        block_ids, site_ids = _resident_scope_ids(db, user)
        q = q.where(
            or_(
                Announcement.block_id.in_(block_ids),
                and_(Announcement.block_id.is_(None), Announcement.site_id.in_(site_ids)),
            )
        )
    return list(db.scalars(q))
