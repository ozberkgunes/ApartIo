from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

ROLE_SITE_MANAGER = "site_manager"
ROLE_BUILDING_MANAGER = "building_manager"
ROLE_RESIDENT = "resident"
MANAGER_ROLES = (ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)

ROLE_LABELS = {
    ROLE_SITE_MANAGER: "Site Yöneticisi",
    ROLE_BUILDING_MANAGER: "Apartman Yöneticisi",
    ROLE_RESIDENT: "Sakin",
}

OCC_OWNER = "owner"
OCC_TENANT = "tenant"
OCC_TYPE_LABELS = {OCC_OWNER: "Malik", OCC_TENANT: "Kiracı"}

DEBT_PENDING = "pending"
DEBT_PARTIAL = "partial"
DEBT_PAID = "paid"
DEBT_STATUS_LABELS = {DEBT_PENDING: "Bekliyor", DEBT_PARTIAL: "Kısmi Ödendi", DEBT_PAID: "Ödendi"}

DEBT_CAT_AIDAT = "aidat"
DEBT_CAT_DEMIRBAS = "demirbas"
DEBT_CAT_DOGALGAZ = "dogalgaz"
DEBT_CAT_DOGALGAZ_AVANS = "dogalgaz_avans"
DEBT_CAT_GECIKME = "gecikme"
DEBT_CAT_OTHER = "other"
DEBT_CATEGORY_LABELS = {
    DEBT_CAT_AIDAT: "Aidat",
    DEBT_CAT_DEMIRBAS: "Demirbaş",
    DEBT_CAT_DOGALGAZ: "Doğalgaz",
    DEBT_CAT_DOGALGAZ_AVANS: "Doğalgaz Avans",
    DEBT_CAT_GECIKME: "Gecikme Tazminatı",
    DEBT_CAT_OTHER: "Diğer",
}
# Demirbaş ve doğalgaz avansı KMK gereği kiracıya değil kat malikine tahakkuk eder.
OWNER_BILLED_CATEGORIES = (DEBT_CAT_DEMIRBAS, DEBT_CAT_DOGALGAZ_AVANS)

PAYMENT_METHOD_LABELS = {"cash": "Nakit", "transfer": "Havale/EFT", "card": "Kart"}

TICKET_CATEGORY_LABELS = {"fault": "Arıza", "request": "Talep", "complaint": "Şikayet", "other": "Diğer"}
TICKET_PRIORITY_LABELS = {"low": "Düşük", "normal": "Normal", "high": "Yüksek"}
TICKET_STATUS_LABELS = {"open": "Açık", "in_progress": "İşlemde", "resolved": "Çözüldü", "closed": "Kapalı"}

WORK_STATUS_LABELS = {"todo": "Bekliyor", "in_progress": "Devam Ediyor", "done": "Tamamlandı"}

DOC_CATEGORY_LABELS = {
    "invoice": "Fatura",
    "contract": "Sözleşme",
    "decision": "Karar",
    "report": "Rapor",
    "other": "Diğer",
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(32), default=ROLE_RESIDENT)
    # Apartman yöneticisinin sorumlu olduğu blok
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    block: Mapped["Block | None"] = relationship(foreign_keys=[block_id])
    occupancies: Mapped[list["Occupancy"]] = relationship(back_populates="user")

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(255))

    blocks: Mapped[list["Block"]] = relationship(back_populates="site")


class Block(Base):
    __tablename__ = "blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    name: Mapped[str] = mapped_column(String(120))

    site: Mapped[Site] = relationship(back_populates="blocks")
    apartments: Mapped[list["Apartment"]] = relationship(back_populates="block")

    @property
    def full_name(self) -> str:
        return f"{self.site.name} / {self.name}"


class Apartment(Base):
    __tablename__ = "apartments"

    id: Mapped[int] = mapped_column(primary_key=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"))
    floor_no: Mapped[int] = mapped_column(default=0)
    number: Mapped[str] = mapped_column(String(16))
    area_m2: Mapped[float | None] = mapped_column()
    unit_type: Mapped[str | None] = mapped_column(String(24))  # İŞ YERİ, 1+1, 2+1, 3+1...
    # Doğalgaz aboneliği: True=yapıldı, False=yapılmadı, None=bilinmiyor
    gas_subscribed: Mapped[bool | None] = mapped_column(Boolean)

    block: Mapped[Block] = relationship(back_populates="apartments")
    occupancies: Mapped[list["Occupancy"]] = relationship(back_populates="apartment")
    debts: Mapped[list["Debt"]] = relationship(back_populates="apartment")

    @property
    def label(self) -> str:
        return f"{self.block.full_name} — Kat {self.floor_no}, No {self.number}"

    @property
    def active_occupancies(self) -> list["Occupancy"]:
        return [o for o in self.occupancies if o.end_date is None]

    def _active_by_type(self, occ_type: str) -> "Occupancy | None":
        for o in self.active_occupancies:
            if o.type == occ_type:
                return o
        return None

    @property
    def owner(self) -> "Occupancy | None":
        return self._active_by_type(OCC_OWNER)

    @property
    def tenant(self) -> "Occupancy | None":
        return self._active_by_type(OCC_TENANT)

    @property
    def open_debt_total(self) -> Decimal:
        return sum((d.remaining for d in self.debts if d.status != DEBT_PAID), Decimal("0"))


class Occupancy(Base):
    __tablename__ = "occupancies"

    id: Mapped[int] = mapped_column(primary_key=True)
    apartment_id: Mapped[int] = mapped_column(ForeignKey("apartments.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(16))  # owner | tenant
    start_date: Mapped[date] = mapped_column(Date, default=date.today)
    end_date: Mapped[date | None] = mapped_column(Date)

    apartment: Mapped[Apartment] = relationship(back_populates="occupancies")
    user: Mapped[User] = relationship(back_populates="occupancies")

    @property
    def type_label(self) -> str:
        return OCC_TYPE_LABELS.get(self.type, self.type)


class DuesDefinition(Base):
    __tablename__ = "dues_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id"))  # null = tüm site
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    due_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(255))
    is_surcharge: Mapped[bool] = mapped_column(Boolean, default=False)  # ek aidat (gider açığı zammı)

    site: Mapped[Site] = relationship()
    block: Mapped[Block | None] = relationship()
    debts: Mapped[list["Debt"]] = relationship(back_populates="dues")

    @property
    def scope_label(self) -> str:
        return self.block.full_name if self.block else f"{self.site.name} (tüm site)"


class Debt(Base):
    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(primary_key=True)
    apartment_id: Mapped[int] = mapped_column(ForeignKey("apartments.id"))
    dues_id: Mapped[int | None] = mapped_column(ForeignKey("dues_definitions.id"))
    description: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default=DEBT_PENDING)
    category: Mapped[str] = mapped_column(String(24), default=DEBT_CAT_OTHER)
    # True: borç dairenin kiracısına değil kat malikine aittir (demirbaş, doğalgaz avansı)
    bill_to_owner: Mapped[bool] = mapped_column(Boolean, default=False)
    # Gecikme tazminatı borçları anapara borcuna bu alanla bağlanır (KMK m.20)
    source_debt_id: Mapped[int | None] = mapped_column(ForeignKey("debts.id"))

    apartment: Mapped[Apartment] = relationship(back_populates="debts")
    dues: Mapped[DuesDefinition | None] = relationship(back_populates="debts")
    payments: Mapped[list["Payment"]] = relationship(back_populates="debt")
    source_debt: Mapped["Debt | None"] = relationship(
        remote_side="Debt.id", back_populates="late_fee_debts"
    )
    late_fee_debts: Mapped[list["Debt"]] = relationship(back_populates="source_debt")

    @property
    def paid_amount(self) -> Decimal:
        return sum((p.amount for p in self.payments), Decimal("0"))

    @property
    def remaining(self) -> Decimal:
        return (self.amount or Decimal("0")) - self.paid_amount

    @property
    def status_label(self) -> str:
        return DEBT_STATUS_LABELS.get(self.status, self.status)

    @property
    def category_label(self) -> str:
        return DEBT_CATEGORY_LABELS.get(self.category, self.category)

    @property
    def is_future(self) -> bool:
        """Cari aydan sonraki döneme tahakkuk eden borç "ileri tarihli"dir."""
        today = date.today()
        return (self.due_date.year, self.due_date.month) > (today.year, today.month)

    @property
    def timing_label(self) -> str:
        return "İleri Tarihli" if self.is_future else "Aktif"


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    debt_id: Mapped[int] = mapped_column(ForeignKey("debts.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    paid_at: Mapped[date] = mapped_column(Date, default=date.today)
    method: Mapped[str] = mapped_column(String(16), default="cash")
    received_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    debt: Mapped[Debt] = relationship(back_populates="payments")
    receiver: Mapped[User | None] = relationship()

    @property
    def method_label(self) -> str:
        return PAYMENT_METHOD_LABELS.get(self.method, self.method)


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id"))  # null = tüm site
    category: Mapped[str] = mapped_column(String(64))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    expense_date: Mapped[date] = mapped_column(Date, default=date.today)
    description: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    site: Mapped[Site] = relationship()
    block: Mapped[Block | None] = relationship()
    creator: Mapped[User | None] = relationship()

    @property
    def scope_label(self) -> str:
        return self.block.full_name if self.block else f"{self.site.name} (tüm site)"


class Staff(Base):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    full_name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(64))  # kapıcı, güvenlik, temizlik, teknisyen...
    phone: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    site: Mapped[Site] = relationship()


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    apartment_id: Mapped[int] = mapped_column(ForeignKey("apartments.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    category: Mapped[str] = mapped_column(String(16), default="fault")
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    apartment: Mapped[Apartment] = relationship()
    creator: Mapped[User] = relationship()
    comments: Mapped[list["TicketComment"]] = relationship(back_populates="ticket")
    work_orders: Mapped[list["WorkOrder"]] = relationship(back_populates="ticket")

    @property
    def category_label(self) -> str:
        return TICKET_CATEGORY_LABELS.get(self.category, self.category)

    @property
    def priority_label(self) -> str:
        return TICKET_PRIORITY_LABELS.get(self.priority, self.priority)

    @property
    def status_label(self) -> str:
        return TICKET_STATUS_LABELS.get(self.status, self.status)


class TicketComment(Base):
    __tablename__ = "ticket_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    ticket: Mapped[Ticket] = relationship(back_populates="comments")
    user: Mapped[User] = relationship()


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id"))  # null = tüm site
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"))
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="todo")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    site: Mapped[Site] = relationship()
    block: Mapped[Block | None] = relationship()
    ticket: Mapped[Ticket | None] = relationship(back_populates="work_orders")
    staff: Mapped[Staff | None] = relationship()
    creator: Mapped[User | None] = relationship()

    @property
    def status_label(self) -> str:
        return WORK_STATUS_LABELS.get(self.status, self.status)

    @property
    def scope_label(self) -> str:
        return self.block.full_name if self.block else f"{self.site.name} (tüm site)"


class MessageThread(Base):
    __tablename__ = "message_threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    recipient: Mapped[User] = relationship(foreign_keys=[recipient_id])
    messages: Mapped[list["Message"]] = relationship(back_populates="thread")

    def other_user(self, user_id: int) -> User:
        return self.recipient if self.created_by == user_id else self.creator

    @property
    def last_message(self) -> "Message | None":
        return max(self.messages, key=lambda m: m.id) if self.messages else None

    def unread_count_for(self, user_id: int) -> int:
        return sum(1 for m in self.messages if m.sender_id != user_id and m.read_at is None)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("message_threads.id"))
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)

    thread: Mapped[MessageThread] = relationship(back_populates="messages")
    sender: Mapped[User] = relationship()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(String(500))
    link: Mapped[str | None] = mapped_column(String(255))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    user: Mapped[User] = relationship()


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id"))  # null = tüm site
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(16), default="other")
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(64), unique=True)
    content_type: Mapped[str | None] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(default=0)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)  # sakinlere açık mı
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    site: Mapped[Site] = relationship()
    block: Mapped[Block | None] = relationship()
    uploader: Mapped[User | None] = relationship()

    @property
    def category_label(self) -> str:
        return DOC_CATEGORY_LABELS.get(self.category, self.category)

    @property
    def scope_label(self) -> str:
        return self.block.full_name if self.block else f"{self.site.name} (tüm site)"


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id"))  # null = tüm site
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    site: Mapped[Site] = relationship()
    block: Mapped[Block | None] = relationship()
    creator: Mapped[User | None] = relationship()

    @property
    def scope_label(self) -> str:
        return self.block.full_name if self.block else f"{self.site.name} (tüm site)"
