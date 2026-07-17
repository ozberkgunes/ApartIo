"""Vadesi yaklaşan/geçen borçlar için otomatik hatırlatma bildirimleri (İş #56).

Zamanlayıcı app.main'deki lifespan'da çalışır; kurallar tarih bazlı olduğundan
ve gönderimler DebtReminder tablosuyla teklenendiğinden aynı turun birden çok
kez (ör. iki uvicorn worker'ında) koşması mükerrer bildirim üretmez.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Debt, DebtReminder, DEBT_PAID
from . import notify as notify_service
from .finance import _add_months

REMIND_UPCOMING_DAYS = 3          # vadeye bu kadar gün kala hatırlat
REMINDER_INTERVAL_SECONDS = 6 * 60 * 60
REMINDER_STARTUP_DELAY_SECONDS = 60


def _period_key(debt: Debt, today: date) -> str | None:
    if debt.due_date >= today:
        days_left = (debt.due_date - today).days
        return "upcoming" if days_left <= REMIND_UPCOMING_DAYS else None
    months_overdue = 0
    while _add_months(debt.due_date, months_overdue + 1) <= today:
        months_overdue += 1
    return f"overdue-{months_overdue}"


def pending_reminders(db: Session, today: date) -> list[tuple[Debt, str]]:
    """Hatırlatılacak (borç, period_key) çiftleri; gönderilmişler elenir."""
    sent = {
        (r.debt_id, r.period_key) for r in db.scalars(select(DebtReminder))
    }
    result = []
    for debt in db.scalars(select(Debt).where(Debt.status != DEBT_PAID)):
        if debt.remaining <= 0:
            continue
        key = _period_key(debt, today)
        if key and (debt.id, key) not in sent:
            result.append((debt, key))
    return result


def send_due_reminders(db: Session, today: date | None = None) -> int:
    """Bekleyen hatırlatmaları gönderir; hatırlatılan borç sayısını döndürür.

    Kullanıcı başına tür bazında tek bildirim atılır (N borç, toplam tutar).
    Kayıtlar bildirimden önce commit edilir; teklik kısıtı ihlalinde (eş zamanlı
    ikinci worker) tur sessizce atlanır — kaçan borçlar sonraki turda gönderilir.
    """
    today = today or date.today()
    pending = pending_reminders(db, today)
    if not pending:
        return 0

    groups: dict[tuple[int, str], list[Debt]] = {}
    for debt, key in pending:
        user_id = notify_service.responsible_user_id(debt.apartment, debt.bill_to_owner)
        if user_id is None:
            continue  # sorumlusu olmayan daire: kayıt da açma, sorumlu atanınca hatırlatılır
        kind = "upcoming" if key == "upcoming" else "overdue"
        groups.setdefault((user_id, kind), []).append(debt)
        db.add(DebtReminder(debt_id=debt.id, period_key=key, sent_on=today))

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return 0

    for (user_id, kind), debts in groups.items():
        total = sum((d.remaining for d in debts), Decimal("0"))
        if kind == "upcoming":
            title = "Borç hatırlatması: vade yaklaşıyor"
            body = f"{len(debts)} borcunuzun vadesi yaklaşıyor — kalan toplam {total} ₺."
        else:
            title = "Borç hatırlatması: vadesi geçti"
            body = (
                f"{len(debts)} borcunuzun vadesi geçti — kalan toplam {total} ₺. "
                "Gecikme tazminatı uygulanabilir (KMK m.20)."
            )
        notify_service.notify(db, [user_id], title, body, link="/debts")
    return sum(len(debts) for debts in groups.values())
