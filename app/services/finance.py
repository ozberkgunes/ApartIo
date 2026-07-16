"""Finansal iş kuralları: aidat→borç üretimi, ödeme durumu, dashboard özetleri."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, scoping
from ..models import (
    Apartment,
    Block,
    Debt,
    DuesDefinition,
    Expense,
    Site,
    DEBT_CAT_AIDAT,
    DEBT_CAT_GECIKME,
    DEBT_PAID,
    DEBT_PARTIAL,
    DEBT_PENDING,
)

SURCHARGE_DAY = 20  # ek aidat önerisi ayın bu gününden sonra yapılır (KMK m.20)
LATE_FEE_MONTHLY_RATE = Decimal("0.05")  # gecikme tazminatı: aylık %5 (KMK m.20)


def generate_debts_for_dues(db: Session, dues: DuesDefinition) -> list[Debt]:
    """Aidat tanımının kapsamındaki her daireye borç açar; mükerrer üretimi engeller.

    Yeni oluşturulan borçları döndürür (bildirim gönderimi için).
    """
    if dues.block_id:
        apartments = db.scalars(select(Apartment).where(Apartment.block_id == dues.block_id)).all()
    else:
        apartments = db.scalars(
            select(Apartment).join(Block).where(Block.site_id == dues.site_id)
        ).all()

    existing_ids = {
        row for row in db.scalars(select(Debt.apartment_id).where(Debt.dues_id == dues.id))
    }

    description = dues.description or f"{dues.period} aidatı"
    created: list[Debt] = []
    for apartment in apartments:
        if apartment.id in existing_ids:
            continue
        debt = Debt(
            apartment_id=apartment.id,
            dues_id=dues.id,
            description=description,
            amount=dues.amount,
            due_date=dues.due_date,
            status=DEBT_PENDING,
            category=DEBT_CAT_AIDAT,
        )
        db.add(debt)
        created.append(debt)
    db.commit()
    return created


def update_debt_status(db: Session, debt: Debt) -> None:
    paid = debt.paid_amount
    if paid >= debt.amount:
        debt.status = DEBT_PAID
    elif paid > 0:
        debt.status = DEBT_PARTIAL
    else:
        debt.status = DEBT_PENDING
    db.commit()


def _add_months(d: date, n: int) -> date:
    """Gün kısıtlamalı ay ekleme: 31 Oca + 1 ay → 28/29 Şub."""
    month_index = d.year * 12 + (d.month - 1) + n
    year, month = divmod(month_index, 12)
    month += 1
    next_month_start = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last_day = (next_month_start - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


def late_fee_accrued(debt: Debt, today: date | None = None) -> Decimal:
    """Birikmiş gecikme tazminatı (KMK m.20): tamamlanmış her gecikme ayı için,
    ay dönümü itibarıyla hâlâ ödenmemiş anapara × aylık %5.

    Ay içi ödeme o ayın matrahını düşürür (borçlu lehine yorum); kısmi ay için
    tazminat işlemez. Gecikme borçlarının kendisine tazminat işlemez.
    """
    if debt.category == DEBT_CAT_GECIKME:
        return Decimal("0.00")
    today = today or date.today()
    total = Decimal("0")
    month = 1
    while True:
        month_end = _add_months(debt.due_date, month)
        if month_end > today:
            break
        outstanding = debt.amount - sum(
            (p.amount for p in debt.payments if p.paid_at <= month_end), Decimal("0")
        )
        if outstanding > 0:
            total += outstanding * LATE_FEE_MONTHLY_RATE
        month += 1
    return total.quantize(Decimal("0.01"))


def late_fee_billed(debt: Debt) -> Decimal:
    return sum((f.amount for f in debt.late_fee_debts), Decimal("0"))


def late_fee_billable(debt: Debt, today: date | None = None) -> Decimal:
    return max(late_fee_accrued(debt, today) - late_fee_billed(debt), Decimal("0.00"))


def apply_late_fee(db: Session, debt: Debt, today: date | None = None) -> Debt | None:
    """Kesilebilir gecikme tazminatını ayrı borç olarak tahakkuk ettirir.

    Kesilebilir tutar = birikmiş − daha önce kesilmiş; sıfırsa None döner,
    bu yüzden art arda çağrılar mükerrer borç üretmez.
    """
    created = apply_late_fees(db, [debt], today)
    return created[0] if created else None


def apply_late_fees(db: Session, debts: list[Debt], today: date | None = None) -> list[Debt]:
    """Toplu tahakkuk: kesilebilir tutarı olan her borca gecikme borcu açar."""
    created: list[Debt] = []
    for debt in debts:
        amount = late_fee_billable(debt, today)
        if amount <= 0:
            continue
        fee = Debt(
            apartment_id=debt.apartment_id,
            # ilişki üzerinden bağla ki debt.late_fee_debts aynı oturumda da güncel kalsın
            source_debt=debt,
            description=f"Gecikme tazminatı (KMK m.20): {debt.description}",
            amount=amount,
            due_date=today or date.today(),
            status=DEBT_PENDING,
            category=DEBT_CAT_GECIKME,
            bill_to_owner=debt.bill_to_owner,
        )
        db.add(fee)
        created.append(fee)
    db.commit()
    return created


def _month_bounds(period: str) -> tuple[date, date]:
    """YYYY-MM dönemini [ay başı, ay sonu] tarih aralığına çevirir."""
    year, month = int(period[:4]), int(period[5:7])
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def surcharge_proposal(
    db: Session, site: Site, today: date | None = None
) -> dict | None:
    """Cari dönem gideri aidat tahakkukunu aşıyorsa ek aidat (zam) önerisi döndürür.

    KMK m.20 gereği açık, kapsamdaki dairelere eşit bölünür. Öneri yalnızca
    ayın SURCHARGE_DAY gününden sonra ve dönem için daha önce ek aidat
    uygulanmamışsa üretilir.
    """
    today = today or date.today()
    if today.day <= SURCHARGE_DAY:
        return None
    period = _month_key(today)

    existing = db.scalar(
        select(DuesDefinition).where(
            DuesDefinition.site_id == site.id,
            DuesDefinition.period == period,
            DuesDefinition.is_surcharge.is_(True),
        )
    )
    if existing is not None:
        return None

    start, end = _month_bounds(period)
    expense_total = sum(
        (
            e.amount
            for e in db.scalars(
                select(Expense).where(
                    Expense.site_id == site.id,
                    Expense.expense_date >= start,
                    Expense.expense_date < end,
                )
            )
        ),
        Decimal("0"),
    )
    dues_total = sum(
        (
            d.amount
            for d in db.scalars(
                select(Debt)
                .join(DuesDefinition, Debt.dues_id == DuesDefinition.id)
                .where(
                    DuesDefinition.site_id == site.id,
                    DuesDefinition.period == period,
                    Debt.category == DEBT_CAT_AIDAT,
                )
            )
        ),
        Decimal("0"),
    )
    deficit = expense_total - dues_total
    if deficit <= 0:
        return None

    apartment_count = len(
        db.scalars(
            select(Apartment.id).join(Block).where(Block.site_id == site.id)
        ).all()
    )
    if apartment_count == 0:
        return None
    per_apartment = (deficit / apartment_count).quantize(Decimal("0.01"), rounding=ROUND_UP)

    return {
        "period": period,
        "expense_total": expense_total,
        "dues_total": dues_total,
        "deficit": deficit,
        "apartment_count": apartment_count,
        "per_apartment": per_apartment,
    }


def apply_surcharge(
    db: Session, site: Site, today: date | None = None
) -> tuple[DuesDefinition, list[Debt]] | None:
    """Ek aidat önerisini uygular: is_surcharge işaretli aidat tanımı + borçlar.

    Öneri koşulları sağlanmıyorsa None döner; aynı dönem için ikinci kez
    çağrıldığında surcharge_proposal None döndüğünden mükerrer üretim olmaz.
    """
    proposal = surcharge_proposal(db, site, today=today)
    if proposal is None:
        return None
    _, next_month = _month_bounds(proposal["period"])
    dues = DuesDefinition(
        site_id=site.id,
        block_id=None,
        period=proposal["period"],
        amount=proposal["per_apartment"],
        due_date=next_month - timedelta(days=1),
        description=f"{proposal['period']} ek aidat (gider açığı, KMK m.20)",
        is_surcharge=True,
    )
    db.add(dues)
    db.commit()
    created = generate_debts_for_dues(db, dues)
    return dues, created


def last_months(n: int = 6) -> list[str]:
    today = date.today()
    year, month = today.year, today.month
    months: list[str] = []
    for _ in range(n):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return list(reversed(months))


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def manager_dashboard(db: Session, user: models.User) -> dict:
    apartments = scoping.scoped_apartments(db, user)
    debts = scoping.scoped_debts(db, user)
    payments = scoping.scoped_payments(db, user)
    expenses = scoping.scoped_expenses(db, user)
    occupancies = scoping.scoped_occupancies(db, user, active_only=True)

    open_debts = [d for d in debts if d.status != DEBT_PAID]
    open_total = sum((d.remaining for d in open_debts if not d.is_future), Decimal("0"))
    future_total = sum((d.remaining for d in open_debts if d.is_future), Decimal("0"))

    current = _month_key(date.today())
    month_income = sum((p.amount for p in payments if _month_key(p.paid_at) == current), Decimal("0"))
    month_expense = sum(
        (e.amount for e in expenses if _month_key(e.expense_date) == current), Decimal("0")
    )

    months = last_months(6)
    income_series = {m: Decimal("0") for m in months}
    expense_series = {m: Decimal("0") for m in months}
    for p in payments:
        key = _month_key(p.paid_at)
        if key in income_series:
            income_series[key] += p.amount
    for e in expenses:
        key = _month_key(e.expense_date)
        if key in expense_series:
            expense_series[key] += e.amount

    status_counts = {
        DEBT_PENDING: sum(1 for d in debts if d.status == DEBT_PENDING),
        DEBT_PARTIAL: sum(1 for d in debts if d.status == DEBT_PARTIAL),
        DEBT_PAID: sum(1 for d in debts if d.status == DEBT_PAID),
    }

    if user.role == models.ROLE_SITE_MANAGER:
        sites = list(db.scalars(select(Site)))
    else:
        sites = [user.block.site] if user.block else []
    surcharge_proposals = []
    for site in sites:
        proposal = surcharge_proposal(db, site)
        if proposal:
            surcharge_proposals.append({"site": site, **proposal})

    return {
        "surcharge_proposals": surcharge_proposals,
        "apartment_count": len(apartments),
        "resident_count": len({o.user_id for o in occupancies}),
        "open_total": open_total,
        "future_total": future_total,
        "month_income": month_income,
        "month_expense": month_expense,
        "months": months,
        "income_values": [float(income_series[m]) for m in months],
        "expense_values": [float(expense_series[m]) for m in months],
        "status_counts": status_counts,
        # aktif borçlar önce; ileri tarihliler listenin sonuna düşer
        "open_debts": sorted(open_debts, key=lambda d: d.is_future)[:10],
    }


def resident_dashboard(db: Session, user: models.User) -> dict:
    apartments = scoping.scoped_apartments(db, user)
    debts = scoping.scoped_debts(db, user)
    open_debts = [d for d in debts if d.status != DEBT_PAID]
    open_total = sum((d.remaining for d in open_debts if not d.is_future), Decimal("0"))
    future_total = sum((d.remaining for d in open_debts if d.is_future), Decimal("0"))
    paid_total = sum((d.paid_amount for d in debts), Decimal("0"))
    return {
        "apartments": apartments,
        "debts": debts,
        "open_total": open_total,
        "future_total": future_total,
        "paid_total": paid_total,
    }
