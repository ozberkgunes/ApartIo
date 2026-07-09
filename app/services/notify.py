"""Uygulama içi bildirimler. SMS/e-posta kanalları Faz 4'te eklenecek."""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..models import (
    Apartment,
    Block,
    Notification,
    Occupancy,
    User,
    ROLE_BUILDING_MANAGER,
    ROLE_SITE_MANAGER,
)


def notify(
    db: Session,
    user_ids: Iterable[int],
    title: str,
    body: str = "",
    link: str | None = None,
    exclude_user_id: int | None = None,
) -> None:
    targets = set(user_ids)
    if exclude_user_id is not None:
        targets.discard(exclude_user_id)
    for uid in targets:
        db.add(Notification(user_id=uid, title=title, body=body or None, link=link))
    if targets:
        db.commit()


def managers_for_apartment(db: Session, apartment: Apartment) -> set[int]:
    """Dairenin bloğundan sorumlu apartman yöneticileri + tüm site yöneticileri."""
    site_managers = set(
        db.scalars(
            select(User.id).where(User.role == ROLE_SITE_MANAGER, User.is_active.is_(True))
        )
    )
    block_managers = set(
        db.scalars(
            select(User.id).where(
                User.role == ROLE_BUILDING_MANAGER,
                User.block_id == apartment.block_id,
                User.is_active.is_(True),
            )
        )
    )
    return site_managers | block_managers


def responsible_user_id(apartment: Apartment, bill_to_owner: bool = False) -> int | None:
    """Borç/bildirim muhatabı: aktif kiracı varsa kiracı, yoksa malik.

    bill_to_owner=True (demirbaş, doğalgaz avansı) ise kiracıya bakılmaksızın malik.
    """
    occupancy = apartment.owner if bill_to_owner else (apartment.tenant or apartment.owner)
    return occupancy.user_id if occupancy else None


def users_in_scope(db: Session, site_id: int, block_id: int | None = None) -> set[int]:
    """Kapsamdaki (blok ya da tüm site) aktif sakinler + ilgili blok yöneticileri."""
    occ_q = (
        select(Occupancy.user_id)
        .join(Apartment, Occupancy.apartment_id == Apartment.id)
        .where(Occupancy.end_date.is_(None))
    )
    if block_id:
        occ_q = occ_q.where(Apartment.block_id == block_id)
    else:
        occ_q = occ_q.join(Block, Apartment.block_id == Block.id).where(Block.site_id == site_id)
    ids = set(db.scalars(occ_q))

    bm_q = select(User.id).where(User.role == ROLE_BUILDING_MANAGER, User.is_active.is_(True))
    if block_id:
        bm_q = bm_q.where(User.block_id == block_id)
    else:
        bm_q = bm_q.where(User.block_id.in_(select(Block.id).where(Block.site_id == site_id)))
    ids |= set(db.scalars(bm_q))
    return ids


def unread_count(db: Session, user_id: int) -> int:
    return len(
        db.scalars(
            select(Notification.id).where(
                Notification.user_id == user_id, Notification.is_read.is_(False)
            )
        ).all()
    )
