"""Demo verisi oluşturur. Çalıştırma: python seed.py"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app import models
from app.auth import hash_password
from app.database import Base, SessionLocal, engine
from app.services.finance import generate_debts_for_dues, update_debt_status

ADMIN_EMAIL = "admin@apart.io"
PASSWORD = "demo1234"


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.scalar(select(models.User).where(models.User.email == ADMIN_EMAIL)):
            print("Seed verisi zaten mevcut, işlem yapılmadı.")
            return

        # --- Yapı: site, bloklar, daireler ---
        site = models.Site(name="Gül Sitesi", address="Çiçek Mah. Gül Sok. No:1, İstanbul")
        db.add(site)
        db.flush()

        block_a = models.Block(site_id=site.id, name="A Blok")
        block_b = models.Block(site_id=site.id, name="B Blok")
        db.add_all([block_a, block_b])
        db.flush()

        apartments = []
        for block in (block_a, block_b):
            number = 1
            for floor in (1, 2):
                for _ in range(2):
                    apartment = models.Apartment(
                        block_id=block.id, floor_no=floor, number=str(number), area_m2=100 + number * 5
                    )
                    apartments.append(apartment)
                    number += 1
        db.add_all(apartments)
        db.flush()

        # --- Kullanıcılar ---
        pw = hash_password(PASSWORD)
        admin = models.User(
            email=ADMIN_EMAIL, full_name="Selin Öztürk", phone="0532 111 11 11",
            role=models.ROLE_SITE_MANAGER, password_hash=pw,
        )
        blok_yonetici = models.User(
            email="blok@apart.io", full_name="Murat Kaya", phone="0532 222 22 22",
            role=models.ROLE_BUILDING_MANAGER, block_id=block_a.id, password_hash=pw,
        )
        sakin = models.User(
            email="sakin@apart.io", full_name="Elif Demir", phone="0532 333 33 33",
            role=models.ROLE_RESIDENT, password_hash=pw,
        )
        extra_residents = [
            models.User(email="ayse@apart.io", full_name="Ayşe Yılmaz", role=models.ROLE_RESIDENT, password_hash=pw),
            models.User(email="mehmet@apart.io", full_name="Mehmet Can", role=models.ROLE_RESIDENT, password_hash=pw),
            models.User(email="fatma@apart.io", full_name="Fatma Şahin", role=models.ROLE_RESIDENT, password_hash=pw),
            models.User(email="ali@apart.io", full_name="Ali Vural", role=models.ROLE_RESIDENT, password_hash=pw),
        ]
        db.add_all([admin, blok_yonetici, sakin, *extra_residents])
        db.flush()

        # --- Malik / Kiracı atamaları ---
        a_flats = [a for a in apartments if a.block_id == block_a.id]
        b_flats = [a for a in apartments if a.block_id == block_b.id]
        start = date.today() - timedelta(days=365)
        db.add_all([
            models.Occupancy(apartment_id=a_flats[0].id, user_id=extra_residents[0].id, type=models.OCC_OWNER, start_date=start),
            models.Occupancy(apartment_id=a_flats[1].id, user_id=extra_residents[1].id, type=models.OCC_OWNER, start_date=start),
            # Elif Demir, A Blok 2 numarada kiracı
            models.Occupancy(apartment_id=a_flats[1].id, user_id=sakin.id, type=models.OCC_TENANT, start_date=start + timedelta(days=90)),
            models.Occupancy(apartment_id=b_flats[0].id, user_id=extra_residents[2].id, type=models.OCC_OWNER, start_date=start),
            models.Occupancy(apartment_id=b_flats[1].id, user_id=extra_residents[3].id, type=models.OCC_OWNER, start_date=start),
        ])
        db.flush()

        # --- Aidat + borç üretimi ---
        today = date.today()
        period = f"{today.year:04d}-{today.month:02d}"
        dues = models.DuesDefinition(
            site_id=site.id, block_id=None, period=period,
            amount=Decimal("750.00"), due_date=today.replace(day=10) if today.day <= 28 else today,
            description=f"{period} aidatı",
        )
        db.add(dues)
        db.commit()
        created = len(generate_debts_for_dues(db, dues))

        # --- Örnek tahsilatlar ---
        debt_full = db.scalar(select(models.Debt).where(models.Debt.apartment_id == a_flats[0].id))
        debt_partial = db.scalar(select(models.Debt).where(models.Debt.apartment_id == a_flats[1].id))
        db.add_all([
            models.Payment(debt_id=debt_full.id, amount=Decimal("750.00"), method="transfer", received_by=admin.id),
            models.Payment(debt_id=debt_partial.id, amount=Decimal("300.00"), method="cash", received_by=blok_yonetici.id),
        ])
        db.commit()
        update_debt_status(db, debt_full)
        update_debt_status(db, debt_partial)

        # --- Giderler ---
        db.add_all([
            models.Expense(site_id=site.id, category="Temizlik", amount=Decimal("1200.00"),
                           expense_date=today, description="Aylık temizlik hizmeti", created_by=admin.id),
            models.Expense(site_id=site.id, category="Elektrik", amount=Decimal("800.00"),
                           expense_date=today, description="Ortak alan elektriği", created_by=admin.id),
            models.Expense(site_id=site.id, block_id=block_a.id, category="Bakım/Onarım", amount=Decimal("500.00"),
                           expense_date=today, description="Asansör bakımı", created_by=blok_yonetici.id),
        ])

        # --- Personel ---
        staff_kapici = models.Staff(site_id=site.id, full_name="Hasan Çelik", title="Kapıcı", phone="0532 444 44 44")
        staff_teknisyen = models.Staff(site_id=site.id, full_name="Osman Aydın", title="Teknisyen", phone="0532 555 55 55")
        db.add_all([staff_kapici, staff_teknisyen])
        db.flush()

        # --- Talep + iş emri ---
        ticket = models.Ticket(
            apartment_id=a_flats[1].id,
            created_by=sakin.id,
            category="fault",
            priority="high",
            title="Mutfak lavabosunda su kaçağı",
            description="Mutfak lavabosunun altındaki borudan su sızıyor, dolaba zarar vermeye başladı.",
            status="in_progress",
        )
        db.add(ticket)
        db.flush()
        db.add(models.TicketComment(
            ticket_id=ticket.id, user_id=blok_yonetici.id,
            body="Teknisyen yönlendirildi, yarın 10:00'da gelecek.",
        ))
        db.add(models.WorkOrder(
            site_id=site.id, block_id=block_a.id, ticket_id=ticket.id,
            staff_id=staff_teknisyen.id, title=ticket.title,
            description=f"{a_flats[1].label} — su kaçağı onarımı",
            due_date=today + timedelta(days=1), status="in_progress", created_by=blok_yonetici.id,
        ))

        # --- Duyurular ---
        db.add_all([
            models.Announcement(site_id=site.id, title="Su Kesintisi",
                                body="Yarın 09:00-13:00 arası tüm sitede su kesintisi olacaktır.",
                                created_by=admin.id),
            models.Announcement(site_id=site.id, block_id=block_a.id, title="Asansör Bakımı",
                                body="A Blok asansörü Cuma günü bakımda olacaktır.",
                                created_by=blok_yonetici.id),
        ])
        db.commit()

        print(f"Seed tamamlandı: 1 site, 2 blok, {len(apartments)} daire, {created} borç üretildi.")
        print("Giriş bilgileri (parola hepsi için: demo1234):")
        print("  Site Yöneticisi   : admin@apart.io")
        print("  Apartman Yöneticisi: blok@apart.io  (A Blok)")
        print("  Sakin             : sakin@apart.io (A Blok, Daire 2, kiracı)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
