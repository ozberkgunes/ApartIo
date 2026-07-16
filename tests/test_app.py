from datetime import date
from decimal import Decimal

from app import models, scoping
from app.auth import hash_password, verify_password
from app.services.finance import generate_debts_for_dues, update_debt_status


def test_password_hash_and_verify():
    hashed = hash_password("gizli123")
    assert verify_password("gizli123", hashed)
    assert not verify_password("yanlis", hashed)


def test_scoping_apartments(db_session, seed_data):
    d = seed_data
    assert len(scoping.scoped_apartments(db_session, d["admin"])) == 4
    # Blok yöneticisi sadece A bloktaki 2 daireyi görür
    manager_apartments = scoping.scoped_apartments(db_session, d["manager"])
    assert {a.block_id for a in manager_apartments} == {d["block_a"].id}
    assert len(manager_apartments) == 2
    # Sakin sadece oturduğu daireyi görür
    resident_apartments = scoping.scoped_apartments(db_session, d["resident"])
    assert [a.id for a in resident_apartments] == [d["apartments"][0].id]


def test_can_access_apartment(db_session, seed_data):
    d = seed_data
    b_flat = d["apartments"][2]  # B blok
    assert scoping.can_access_apartment(db_session, d["admin"], b_flat)
    assert not scoping.can_access_apartment(db_session, d["manager"], b_flat)
    assert not scoping.can_access_apartment(db_session, d["resident"], b_flat)
    assert scoping.can_access_apartment(db_session, d["resident"], d["apartments"][0])


def test_generate_debts_idempotent(db_session, seed_data):
    d = seed_data
    assert len(generate_debts_for_dues(db_session, d["dues"])) == 4
    # İkinci üretim mükerrer borç açmamalı
    assert generate_debts_for_dues(db_session, d["dues"]) == []


def test_payment_updates_status(db_session, seed_data):
    d = seed_data
    generate_debts_for_dues(db_session, d["dues"])
    debt = db_session.query(models.Debt).filter_by(apartment_id=d["apartments"][0].id).one()

    db_session.add(models.Payment(debt_id=debt.id, amount=Decimal("200.00"), paid_at=date(2026, 7, 5)))
    db_session.commit()
    db_session.refresh(debt)
    update_debt_status(db_session, debt)
    assert debt.status == models.DEBT_PARTIAL
    assert debt.remaining == Decimal("300.00")

    db_session.add(models.Payment(debt_id=debt.id, amount=Decimal("300.00"), paid_at=date(2026, 7, 6)))
    db_session.commit()
    db_session.refresh(debt)
    update_debt_status(db_session, debt)
    assert debt.status == models.DEBT_PAID
    assert debt.remaining == Decimal("0.00")


def test_login_flow_and_role_access(client, seed_data):
    # Oturum yokken dashboard login'e yönlendirir
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

    # Hatalı parola reddedilir
    response = client.post("/login", data={"email": "resident@test", "password": "yanlis"})
    assert response.status_code == 401

    # Sakin giriş yapar, dashboard açılır
    response = client.post(
        "/login", data={"email": "resident@test", "password": "test1234"}, follow_redirects=False
    )
    assert response.status_code == 303
    response = client.get("/")
    assert response.status_code == 200

    # Sakin, kullanıcı yönetimine erişemez
    assert client.get("/users").status_code == 403

    # Sakin, başkasının (B blok) dairesine erişemez
    b_flat_id = seed_data["apartments"][2].id
    assert client.get(f"/apartments/{b_flat_id}").status_code == 403


def test_building_manager_scope(client, seed_data):
    client.post("/login", data={"email": "manager@test", "password": "test1234"})

    # Kendi bloğundaki daireye erişir
    a_flat_id = seed_data["apartments"][0].id
    assert client.get(f"/apartments/{a_flat_id}").status_code == 200

    # Başka bloktaki daireye erişemez
    b_flat_id = seed_data["apartments"][2].id
    assert client.get(f"/apartments/{b_flat_id}").status_code == 403

    # Site yönetimi sayfasına erişemez
    assert client.get("/sites").status_code == 403


# ---------- Faz 2 ----------


def _make_ticket(db_session, seed_data, apartment_index=0, creator=None):
    d = seed_data
    ticket = models.Ticket(
        apartment_id=d["apartments"][apartment_index].id,
        created_by=(creator or d["resident"]).id,
        category="fault",
        title="Test arıza",
        description="Açıklama",
    )
    db_session.add(ticket)
    db_session.commit()
    return ticket


def test_ticket_scoping(db_session, seed_data):
    d = seed_data
    ticket_a = _make_ticket(db_session, seed_data, 0, d["resident"])  # A blok
    ticket_b = _make_ticket(db_session, seed_data, 2, d["other"])  # B blok

    assert {t.id for t in scoping.scoped_tickets(db_session, d["admin"])} == {ticket_a.id, ticket_b.id}
    assert {t.id for t in scoping.scoped_tickets(db_session, d["manager"])} == {ticket_a.id}
    assert {t.id for t in scoping.scoped_tickets(db_session, d["resident"])} == {ticket_a.id}


def test_ticket_creates_notification_for_managers(client, db_session, seed_data):
    d = seed_data
    client.post("/login", data={"email": "resident@test", "password": "test1234"})
    response = client.post(
        "/tickets/new",
        data={
            "apartment_id": d["apartments"][0].id,
            "category": "fault",
            "priority": "high",
            "title": "Kapı kilidi bozuk",
            "description": "Bina giriş kapısının kilidi çalışmıyor.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    manager_notifs = db_session.query(models.Notification).filter_by(user_id=d["manager"].id).all()
    admin_notifs = db_session.query(models.Notification).filter_by(user_id=d["admin"].id).all()
    assert len(manager_notifs) == 1
    assert len(admin_notifs) == 1
    assert "Kapı kilidi bozuk" in manager_notifs[0].title


def test_resident_cannot_create_ticket_for_other_apartment(client, seed_data):
    d = seed_data
    client.post("/login", data={"email": "resident@test", "password": "test1234"})
    response = client.post(
        "/tickets/new",
        data={
            "apartment_id": d["apartments"][2].id,  # B blok, başkasının dairesi
            "category": "fault",
            "priority": "normal",
            "title": "X",
            "description": "Y",
        },
    )
    assert response.status_code == 403


def test_message_flow_and_access(client, db_session, seed_data):
    d = seed_data
    client.post("/login", data={"email": "resident@test", "password": "test1234"})

    # Sakin, blok yöneticisine mesaj başlatabilir
    response = client.post(
        "/messages/new",
        data={"recipient_id": d["manager"].id, "subject": "Merhaba", "body": "Bir sorum var."},
        follow_redirects=False,
    )
    assert response.status_code == 303
    thread = db_session.query(models.MessageThread).one()

    # Sakin, ilgisiz başka bir sakine mesaj başlatamaz
    response = client.post(
        "/messages/new",
        data={"recipient_id": d["other"].id, "subject": "X", "body": "Y"},
    )
    assert response.status_code == 403

    # Üçüncü kişi konuşmayı göremez
    client.get("/logout")
    client.post("/login", data={"email": "other@test", "password": "test1234"})
    assert client.get(f"/messages/{thread.id}").status_code == 403

    # Alıcı görebilir ve yanıtlayabilir
    client.get("/logout")
    client.post("/login", data={"email": "manager@test", "password": "test1234"})
    assert client.get(f"/messages/{thread.id}").status_code == 200
    response = client.post(
        f"/messages/{thread.id}/reply", data={"body": "Buyurun."}, follow_redirects=False
    )
    assert response.status_code == 303
    assert db_session.query(models.Message).count() == 2


def test_work_order_scope(client, db_session, seed_data):
    d = seed_data
    # Blok yöneticisi kendi bloğu için görev oluşturur
    client.post("/login", data={"email": "manager@test", "password": "test1234"})
    response = client.post(
        "/tasks/new", data={"title": "Merdiven temizliği"}, follow_redirects=False
    )
    assert response.status_code == 303
    work_order = db_session.query(models.WorkOrder).one()
    assert work_order.block_id == d["block_a"].id

    # Sakin görev sayfasına erişemez
    client.get("/logout")
    client.post("/login", data={"email": "resident@test", "password": "test1234"})
    assert client.get("/tasks").status_code == 403


def test_work_order_status_syncs_ticket(client, db_session, seed_data):
    d = seed_data
    ticket = _make_ticket(db_session, seed_data, 0, d["resident"])

    client.post("/login", data={"email": "manager@test", "password": "test1234"})

    # Talepten iş emri üret → talep işleme alınır
    client.post(f"/tickets/{ticket.id}/workorder", data={"staff_id": "", "due_date": ""})
    db_session.refresh(ticket)
    assert ticket.status == "in_progress"
    work_order = db_session.query(models.WorkOrder).filter_by(ticket_id=ticket.id).one()

    # İş emri tamamlanınca talep çözülür
    client.post(f"/tasks/{work_order.id}/status", data={"status": "done"})
    db_session.refresh(ticket)
    assert ticket.status == "resolved"

    # Talep sahibine bildirim düşer
    notifications = db_session.query(models.Notification).filter_by(user_id=d["resident"].id).all()
    assert any("Çözüldü" in (n.body or "") for n in notifications)

    # İş emri yeniden açılınca talep tekrar işleme alınır
    client.post(f"/tasks/{work_order.id}/status", data={"status": "todo"})
    db_session.refresh(ticket)
    assert ticket.status == "in_progress"


def test_reports_access(client, seed_data):
    client.post("/login", data={"email": "admin@test", "password": "test1234"})
    assert client.get("/reports").status_code == 200
    response = client.get("/reports/export/debts")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]

    client.get("/logout")
    client.post("/login", data={"email": "resident@test", "password": "test1234"})
    assert client.get("/reports").status_code == 403

# ---------- Kategorili / toplu borçlandırma ----------


def test_bulk_debt_fixed_amount_bills_owner_category(client, db_session, seed_data):
    d = seed_data
    client.post("/login", data={"email": "admin@test", "password": "test1234"})
    response = client.post("/debts/bulk", data={
        "scope": f"block:{d['block_a'].id}", "category": "demirbas",
        "amount": "1000", "amount_mode": "fixed",
        "due_date": "2026-07-31", "description": "2026-07 demirbaş taksidi",
    }, follow_redirects=False)
    assert response.status_code == 303

    debts = db_session.query(models.Debt).filter_by(category="demirbas").all()
    assert len(debts) == 2  # A bloktaki 2 daire
    assert all(debt.bill_to_owner for debt in debts)
    assert all(debt.amount == Decimal("1000") for debt in debts)
    assert {debt.apartment.block_id for debt in debts} == {d["block_a"].id}


def test_bulk_debt_per_m2_skips_missing_area(client, db_session, seed_data):
    d = seed_data
    d["apartments"][2].area_m2 = 80.0  # B blokta yalnız bir dairenin m²'si var
    db_session.commit()

    client.post("/login", data={"email": "admin@test", "password": "test1234"})
    client.post("/debts/bulk", data={
        "scope": f"block:{d['block_b'].id}", "category": "dogalgaz_avans",
        "amount": "25", "amount_mode": "per_m2",
        "due_date": "2026-07-31", "description": "Doğalgaz avansı",
    })
    debts = db_session.query(models.Debt).filter_by(category="dogalgaz_avans").all()
    assert len(debts) == 1  # m²'si olmayan daire atlandı
    assert debts[0].amount == Decimal("2000.00")  # 25 ₺ × 80 m²
    assert debts[0].bill_to_owner


def test_bulk_debt_building_manager_limited_to_own_block(client, db_session, seed_data):
    d = seed_data
    client.post("/login", data={"email": "manager@test", "password": "test1234"})
    # Blok yöneticisinin scope'u yok sayılır; kendi bloğuna (A) borç üretir
    client.post("/debts/bulk", data={
        "scope": f"block:{d['block_b'].id}", "category": "dogalgaz",
        "amount": "300", "amount_mode": "fixed",
        "due_date": "2026-07-31", "description": "Doğalgaz payı",
    })
    debts = db_session.query(models.Debt).filter_by(category="dogalgaz").all()
    assert {debt.apartment.block_id for debt in debts} == {d["block_a"].id}
    assert all(not debt.bill_to_owner for debt in debts)


def test_manual_debt_invalid_category_rejected(client, seed_data):
    d = seed_data
    client.post("/login", data={"email": "admin@test", "password": "test1234"})
    response = client.post("/debts/new", data={
        "apartment_id": d["apartments"][0].id, "description": "x",
        "amount": "100", "due_date": "2026-07-31", "category": "uydurma",
    })
    assert response.status_code == 400


def test_responsible_user_owner_billed(db_session, seed_data):
    from app.services.notify import responsible_user_id

    d = seed_data
    apartment = d["apartments"][0]  # kiracı: resident
    owner = models.Occupancy(
        apartment_id=apartment.id, user_id=d["other"].id,
        type=models.OCC_OWNER, start_date=date(2026, 1, 1),
    )
    db_session.add(owner)
    db_session.commit()
    db_session.refresh(apartment)

    # Normal borç kiracıya, malik borcu (demirbaş/avans) malike gider
    assert responsible_user_id(apartment) == d["resident"].id
    assert responsible_user_id(apartment, bill_to_owner=True) == d["other"].id


# ---------- Ek aidat (zam) mekanizması — KMK m.20 ----------


def _setup_deficit(db_session, seed_data, expense="3000", period_day=25):
    """Cari dönemde aidat tahakkuku (4×500=2000) + gideri oluşturur."""
    d = seed_data
    today = date(2026, 7, period_day)
    dues = models.DuesDefinition(
        site_id=d["site"].id, period="2026-07", amount=Decimal("500.00"),
        due_date=date(2026, 7, 10),
    )
    db_session.add(dues)
    db_session.commit()
    generate_debts_for_dues(db_session, dues)
    db_session.add(models.Expense(
        site_id=d["site"].id, category="Doğalgaz", amount=Decimal(expense),
        expense_date=date(2026, 7, 5),
    ))
    db_session.commit()
    return today


def test_surcharge_proposal_requires_day_after_20(db_session, seed_data):
    from app.services.finance import surcharge_proposal

    d = seed_data
    _setup_deficit(db_session, seed_data)
    assert surcharge_proposal(db_session, d["site"], today=date(2026, 7, 20)) is None
    proposal = surcharge_proposal(db_session, d["site"], today=date(2026, 7, 25))
    assert proposal is not None
    # Açık: 3000 gider − 2000 tahakkuk = 1000; 4 daireye eşit → 250
    assert proposal["deficit"] == Decimal("1000.00")
    assert proposal["apartment_count"] == 4
    assert proposal["per_apartment"] == Decimal("250.00")


def test_surcharge_proposal_none_when_income_covers(db_session, seed_data):
    from app.services.finance import surcharge_proposal

    d = seed_data
    _setup_deficit(db_session, seed_data, expense="1500")  # gider < 2000 tahakkuk
    assert surcharge_proposal(db_session, d["site"], today=date(2026, 7, 25)) is None


def test_apply_surcharge_creates_debts_once(db_session, seed_data):
    from app.services.finance import apply_surcharge, surcharge_proposal

    d = seed_data
    today = _setup_deficit(db_session, seed_data)
    result = apply_surcharge(db_session, d["site"], today=today)
    assert result is not None
    dues, created = result
    assert dues.is_surcharge
    assert dues.amount == Decimal("250.00")
    assert len(created) == 4
    assert all(debt.category == models.DEBT_CAT_AIDAT for debt in created)

    # Aynı dönem için ikinci öneri/uygulama yapılmaz
    assert surcharge_proposal(db_session, d["site"], today=today) is None
    assert apply_surcharge(db_session, d["site"], today=today) is None


def test_surcharge_apply_endpoint_site_manager_only(client, db_session, seed_data):
    d = seed_data
    _setup_deficit(db_session, seed_data)
    client.post("/login", data={"email": "manager@test", "password": "test1234"})
    assert client.post(
        "/dues/surcharge/apply", data={"site_id": d["site"].id}
    ).status_code == 403


# ---------- Excel içe aktarma yardımcıları ----------


def test_import_parse_unit_label():
    from import_excel import parse_unit_label

    assert parse_unit_label("A-BLOK DAİRE 02") == ("A", 2)
    assert parse_unit_label("A-BLOK KREŞ") == ("A", 1)
    assert parse_unit_label("B-BLOK KAPICI D.") == ("B", 0)
    assert parse_unit_label("C-BLOK DÜKKAN 01") == ("C", 1)
    assert parse_unit_label("TOPLAM") is None
    assert parse_unit_label("") is None


def test_import_month_column_pairs():
    from datetime import datetime

    from import_excel import month_column_pairs

    # AIDAT sayfası düzeni: 2024-01'in fazladan Tahakkuk kolonu (idx 11) atlanır;
    # başlıktaki bayat 2024 yılı YEAR_OVERRIDE ile 2026'ya çevrilir (site açılışı 2026)
    header = [None] * 36
    header[11] = datetime(2024, 1, 1)
    header[14] = datetime(2024, 2, 1)
    header[16] = datetime(2024, 3, 1)
    pairs = month_column_pairs(header, 18)
    assert pairs == [("2026-01", 12, 13), ("2026-02", 14, 15), ("2026-03", 16, 17)]

    # DEMIRBAS sayfası düzeni: ay isimleri + TOPLAM sınırı
    header = [None] * 19
    header[11], header[13], header[15], header[17] = "Temmuz", "Ağustos", "Eylül", "TOPLAM"
    pairs = month_column_pairs(header, 19)
    assert pairs == [("2026-07", 11, 12), ("2026-08", 13, 14), ("2026-09", 15, 16)]


def test_import_slug_email_and_money():
    from import_excel import parse_money, slug_email

    assert slug_email("Sinan Ünsal") == "sinan.unsal@troaspark.local"
    assert slug_email("BERKCAN DEMİRDÖĞEN") == "berkcan.demirdogen@troaspark.local"
    assert parse_money("4000") == Decimal("4000")
    assert parse_money(0) is None
    assert parse_money("") is None
    assert parse_money(None) is None


# ---------- Aktif / ileri tarihli borç ayrımı ----------


def test_debt_is_future_month_boundary(db_session, seed_data):
    from datetime import timedelta

    d = seed_data
    today = date.today()
    month_end = (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    current = models.Debt(apartment_id=d["apartments"][0].id, description="cari ay",
                          amount=Decimal("100"), due_date=month_end)
    future = models.Debt(apartment_id=d["apartments"][0].id, description="gelecek ay",
                         amount=Decimal("100"), due_date=month_end + timedelta(days=1))
    past = models.Debt(apartment_id=d["apartments"][0].id, description="geçmiş",
                       amount=Decimal("100"), due_date=today - timedelta(days=400))
    db_session.add_all([current, future, past])
    db_session.commit()

    assert not current.is_future  # ay sonuna kadar aktif
    assert future.is_future       # sonraki ayın ilk günü ileri tarihli
    assert not past.is_future
    assert future.timing_label == "İleri Tarihli"
    assert current.timing_label == "Aktif"


def test_debts_timing_filter(client, db_session, seed_data):
    from datetime import timedelta

    d = seed_data
    today = date.today()
    db_session.add_all([
        models.Debt(apartment_id=d["apartments"][0].id, description="aktif borç X",
                    amount=Decimal("100"), due_date=today),
        models.Debt(apartment_id=d["apartments"][0].id, description="ileri borç Y",
                    amount=Decimal("100"), due_date=today + timedelta(days=90)),
    ])
    db_session.commit()

    client.post("/login", data={"email": "resident@test", "password": "test1234"})
    active_page = client.get("/debts?timing=active").text
    assert "aktif borç X" in active_page and "ileri borç Y" not in active_page
    future_page = client.get("/debts?timing=future").text
    assert "ileri borç Y" in future_page and "aktif borç X" not in future_page


def test_dashboard_totals_split_future(db_session, seed_data):
    from datetime import timedelta

    from app.services.finance import resident_dashboard

    d = seed_data
    today = date.today()
    db_session.add_all([
        models.Debt(apartment_id=d["apartments"][0].id, description="aktif",
                    amount=Decimal("400"), due_date=today),
        models.Debt(apartment_id=d["apartments"][0].id, description="ileri",
                    amount=Decimal("250"), due_date=today + timedelta(days=90)),
    ])
    db_session.commit()

    ctx = resident_dashboard(db_session, d["resident"])
    assert ctx["open_total"] == Decimal("400")
    assert ctx["future_total"] == Decimal("250")


# ---------- Doğalgaz abonelik sayfası ----------


def test_gas_subscriptions_page_and_update(client, db_session, seed_data):
    d = seed_data
    d["apartments"][0].gas_subscribed = True
    d["apartments"][1].gas_subscribed = False
    db_session.commit()

    client.post("/login", data={"email": "admin@test", "password": "test1234"})
    page = client.get("/gas-subscriptions").text
    assert "Doğalgaz Abonelik Durumu" in page

    only_subscribed = client.get("/gas-subscriptions?status=subscribed").text
    assert only_subscribed.count("text-bg-success\">Abone</span>") == 1

    # Durum güncelleme: bilinmiyor → abone
    target = d["apartments"][2]
    client.post(f"/gas-subscriptions/{target.id}/set", data={"value": "yes"})
    db_session.refresh(target)
    assert target.gas_subscribed is True

    # Sakin erişemez
    client.get("/logout")
    client.post("/login", data={"email": "resident@test", "password": "test1234"})
    assert client.get("/gas-subscriptions").status_code == 403


def test_gas_subscription_block_manager_scope(client, db_session, seed_data):
    d = seed_data
    other_block_apartment = d["apartments"][2]  # B blok
    client.post("/login", data={"email": "manager@test", "password": "test1234"})
    response = client.post(
        f"/gas-subscriptions/{other_block_apartment.id}/set", data={"value": "yes"}
    )
    assert response.status_code == 403


# ---------- Borç silme ----------

def test_delete_debt_without_payments(client, db_session, seed_data):
    d = seed_data
    debt = models.Debt(apartment_id=d["apartments"][0].id, description="hatalı borç",
                       amount=Decimal("100"), due_date=date(2026, 7, 1))
    db_session.add(debt)
    db_session.commit()

    client.post("/login", data={"email": "admin@test", "password": "test1234"})
    page = client.get("/debts").text
    assert "hatalı borç" in page

    response = client.post(f"/debts/{debt.id}/delete")
    assert "Borç silindi" in response.text
    assert db_session.get(models.Debt, debt.id) is None


def test_delete_debt_with_payment_refused(client, db_session, seed_data):
    d = seed_data
    debt = models.Debt(apartment_id=d["apartments"][0].id, description="ödemeli borç",
                       amount=Decimal("100"), due_date=date(2026, 7, 1))
    db_session.add(debt)
    db_session.flush()
    db_session.add(models.Payment(debt_id=debt.id, amount=Decimal("50"), paid_at=date(2026, 7, 5)))
    db_session.commit()

    client.post("/login", data={"email": "admin@test", "password": "test1234"})
    response = client.post(f"/debts/{debt.id}/delete")
    assert "Tahsilatı olan borç silinemez" in response.text
    assert db_session.get(models.Debt, debt.id) is not None


def test_delete_debt_forbidden_for_non_site_manager(client, db_session, seed_data):
    d = seed_data
    debt = models.Debt(apartment_id=d["apartments"][0].id, description="borç",
                       amount=Decimal("100"), due_date=date(2026, 7, 1))
    db_session.add(debt)
    db_session.commit()

    client.post("/login", data={"email": "manager@test", "password": "test1234"})
    assert client.post(f"/debts/{debt.id}/delete").status_code == 403


def test_dues_undo_generated_debts(client, db_session, seed_data):
    d = seed_data
    debts = generate_debts_for_dues(db_session, d["dues"])
    assert len(debts) == 4
    db_session.add(models.Payment(debt_id=debts[0].id, amount=Decimal("100"), paid_at=date(2026, 7, 5)))
    db_session.commit()

    client.post("/login", data={"email": "admin@test", "password": "test1234"})
    response = client.post(f"/dues/{d['dues'].id}/undo")
    assert "3 borç silindi" in response.text
    assert "1 borçta tahsilat olduğundan atlandı" in response.text
    remaining = db_session.query(models.Debt).all()
    assert [x.id for x in remaining] == [debts[0].id]


# ---------- Borç/tahsilat filtreleri ----------

def test_debts_occupant_column_and_q_filter(client, db_session, seed_data):
    d = seed_data
    db_session.add_all([
        models.Debt(apartment_id=d["apartments"][0].id, description="borç A",
                    amount=Decimal("100"), due_date=date(2026, 7, 1)),
        models.Debt(apartment_id=d["apartments"][2].id, description="borç B",
                    amount=Decimal("100"), due_date=date(2026, 7, 1)),
    ])
    db_session.commit()

    client.post("/login", data={"email": "admin@test", "password": "test1234"})
    page = client.get("/debts").text
    assert "<th>Sorumlu</th>" in page
    assert "Diğer Sakin" in page

    filtered = client.get("/debts", params={"q": "diğer"}).text
    assert "borç B" in filtered and "borç A" not in filtered

    # Sakin: Sorumlu kolonu ve Sil butonu görünmez
    client.get("/logout")
    client.post("/login", data={"email": "resident@test", "password": "test1234"})
    page = client.get("/debts").text
    assert "<th>Sorumlu</th>" not in page
    assert "/delete" not in page


def test_payments_q_date_filter_and_sort(client, db_session, seed_data):
    d = seed_data
    debt_jan = models.Debt(apartment_id=d["apartments"][0].id, description="ocak borcu",
                           amount=Decimal("100"), due_date=date(2026, 1, 10))
    debt_jun = models.Debt(apartment_id=d["apartments"][2].id, description="haziran borcu",
                           amount=Decimal("100"), due_date=date(2026, 6, 10))
    db_session.add_all([debt_jan, debt_jun])
    db_session.flush()
    db_session.add_all([
        models.Payment(debt_id=debt_jan.id, amount=Decimal("100"), paid_at=date(2026, 1, 5)),
        models.Payment(debt_id=debt_jun.id, amount=Decimal("100"), paid_at=date(2026, 6, 5)),
    ])
    db_session.commit()

    client.post("/login", data={"email": "admin@test", "password": "test1234"})
    page = client.get("/payments").text
    assert "ocak borcu" in page and "haziran borcu" in page
    # Varsayılan sıralama: yeniden eskiye
    assert page.index("haziran borcu") < page.index("ocak borcu")

    asc = client.get("/payments", params={"sort": "asc"}).text
    assert asc.index("ocak borcu") < asc.index("haziran borcu")

    after_may = client.get("/payments", params={"start": "2026-05-01"}).text
    assert "haziran borcu" in after_may and "ocak borcu" not in after_may

    until_feb = client.get("/payments", params={"end": "2026-02-01"}).text
    assert "ocak borcu" in until_feb and "haziran borcu" not in until_feb

    by_name = client.get("/payments", params={"q": "diğer"}).text
    assert "haziran borcu" in by_name and "ocak borcu" not in by_name

    assert client.get("/payments", params={"start": "zzz"}).status_code == 400


def test_reports_recent_payments(client, db_session, seed_data):
    d = seed_data
    debt = models.Debt(apartment_id=d["apartments"][0].id, description="temmuz aidatı",
                       amount=Decimal("100"), due_date=date(2026, 7, 10))
    db_session.add(debt)
    db_session.flush()
    db_session.add(models.Payment(debt_id=debt.id, amount=Decimal("100"), paid_at=date(2026, 7, 5)))
    db_session.commit()

    client.post("/login", data={"email": "admin@test", "password": "test1234"})
    page = client.get("/reports").text
    assert "Son Gelirler" in page
    assert "temmuz aidatı" in page

    # Aralık dışında kalan tahsilat listelenmez
    out_of_range = client.get("/reports", params={"start": "2025-01-01", "end": "2025-02-01"}).text
    assert "temmuz aidatı" not in out_of_range


# ---------- Malik/Kiracı arama ve filtre ----------

def test_residents_search_and_type_filter(client, db_session, seed_data):
    # Tablodaki tip rozetleri üzerinden doğrula (soldaki form tüm isimleri her zaman listeler)
    owner_badge = 'text-bg-info">Malik</span>'
    tenant_badge = 'text-bg-info">Kiracı</span>'

    client.post("/login", data={"email": "admin@test", "password": "test1234"})
    page = client.get("/residents").text
    assert page.count(owner_badge) == 1 and page.count(tenant_badge) == 1

    tenants = client.get("/residents", params={"occ_type": "tenant"}).text
    assert tenants.count(tenant_badge) == 1 and tenants.count(owner_badge) == 0

    by_name = client.get("/residents", params={"q": "diğer"}).text
    assert by_name.count(owner_badge) == 1 and by_name.count(tenant_badge) == 0

    bogus = client.get("/residents", params={"occ_type": "bogus"}).text
    assert bogus.count(owner_badge) == 1 and bogus.count(tenant_badge) == 1


# ---------- Gecikme tazminatı (KMK m.20, aylık %5) ----------

def _overdue_debt(db_session, apartment_id, amount="1000.00", due=date(2026, 1, 10)):
    debt = models.Debt(
        apartment_id=apartment_id, description="Ocak aidatı",
        amount=Decimal(amount), due_date=due, category=models.DEBT_CAT_AIDAT,
    )
    db_session.add(debt)
    db_session.commit()
    return debt


def test_late_fee_accrues_per_completed_month(db_session, seed_data):
    from app.services.finance import late_fee_accrued

    debt = _overdue_debt(db_session, seed_data["apartments"][0].id)
    # Vade 10 Ocak → 15 Nisan'da 3 tam ay gecikme: 1000 × %5 × 3
    assert late_fee_accrued(debt, today=date(2026, 4, 15)) == Decimal("150.00")
    # İlk ay dolmadan tazminat işlemez
    assert late_fee_accrued(debt, today=date(2026, 2, 9)) == Decimal("0.00")
    # Vadesi gelmemiş borç
    assert late_fee_accrued(debt, today=date(2026, 1, 5)) == Decimal("0.00")


def test_late_fee_month_end_clamp(db_session, seed_data):
    from app.services.finance import late_fee_accrued

    # 31 Ocak vadeli borcun ilk ay dönümü 28 Şubat'tır (gün kısıtlaması)
    debt = _overdue_debt(db_session, seed_data["apartments"][0].id, due=date(2026, 1, 31))
    assert late_fee_accrued(debt, today=date(2026, 2, 27)) == Decimal("0.00")
    assert late_fee_accrued(debt, today=date(2026, 2, 28)) == Decimal("50.00")


def test_late_fee_partial_payment_reduces_base(db_session, seed_data):
    from app.services.finance import late_fee_accrued

    debt = _overdue_debt(db_session, seed_data["apartments"][0].id)
    # Ay dönümünden önce 400 ₺ ödendi → her ayın matrahı 600 ₺
    db_session.add(models.Payment(debt_id=debt.id, amount=Decimal("400.00"), paid_at=date(2026, 2, 5)))
    db_session.commit()
    db_session.refresh(debt)
    assert late_fee_accrued(debt, today=date(2026, 3, 15)) == Decimal("60.00")

    # İlk ay içinde tamamı ödenirse hiç tazminat işlemez
    db_session.add(models.Payment(debt_id=debt.id, amount=Decimal("600.00"), paid_at=date(2026, 2, 8)))
    db_session.commit()
    db_session.refresh(debt)
    assert late_fee_accrued(debt, today=date(2026, 6, 15)) == Decimal("0.00")


def test_late_fee_not_compounded(db_session, seed_data):
    from app.services.finance import late_fee_accrued

    fee_debt = models.Debt(
        apartment_id=seed_data["apartments"][0].id, description="Gecikme tazminatı",
        amount=Decimal("150.00"), due_date=date(2026, 1, 10), category=models.DEBT_CAT_GECIKME,
    )
    db_session.add(fee_debt)
    db_session.commit()
    # Gecikme borcunun kendisine tazminat işlemez (anapara esası)
    assert late_fee_accrued(fee_debt, today=date(2026, 6, 15)) == Decimal("0.00")


def test_apply_late_fee_idempotent_until_time_passes(db_session, seed_data):
    from app.services.finance import apply_late_fee, late_fee_billable

    debt = _overdue_debt(db_session, seed_data["apartments"][0].id)
    fee = apply_late_fee(db_session, debt, today=date(2026, 4, 15))
    assert fee is not None
    assert fee.amount == Decimal("150.00")
    assert fee.category == models.DEBT_CAT_GECIKME
    assert fee.source_debt_id == debt.id
    db_session.refresh(debt)

    # Aynı gün ikinci tahakkuk üretilmez
    assert apply_late_fee(db_session, debt, today=date(2026, 4, 15)) is None
    assert late_fee_billable(debt, today=date(2026, 4, 15)) == Decimal("0.00")

    # Bir ay daha geçince yalnız fark kesilir
    later_fee = apply_late_fee(db_session, debt, today=date(2026, 5, 15))
    assert later_fee is not None
    assert later_fee.amount == Decimal("50.00")


def test_late_fee_endpoint_roles_and_scope(client, db_session, seed_data):
    from datetime import timedelta

    d = seed_data
    debt_b = _overdue_debt(db_session, d["apartments"][2].id, due=date.today() - timedelta(days=100))

    # Sakin tahakkuk yapamaz
    client.post("/login", data={"email": "resident@test", "password": "test1234"})
    assert client.post(f"/debts/{debt_b.id}/late-fee").status_code == 403

    # A blok yöneticisi B bloktaki borca erişemez
    client.get("/logout")
    client.post("/login", data={"email": "manager@test", "password": "test1234"})
    assert client.post(f"/debts/{debt_b.id}/late-fee").status_code == 403

    # Site yöneticisi tahakkuk eder; gecikme borcu + sorumluya bildirim oluşur
    client.get("/logout")
    client.post("/login", data={"email": "admin@test", "password": "test1234"})
    response = client.post(f"/debts/{debt_b.id}/late-fee", follow_redirects=False)
    assert response.status_code == 303
    fee = db_session.query(models.Debt).filter_by(source_debt_id=debt_b.id).one()
    assert fee.category == models.DEBT_CAT_GECIKME
    notes = db_session.query(models.Notification).filter_by(user_id=d["other"].id).all()
    assert any("Gecikme tazminatı" in n.title for n in notes)


def test_late_fee_bulk_endpoint(client, db_session, seed_data):
    from datetime import timedelta

    d = seed_data
    _overdue_debt(db_session, d["apartments"][0].id, due=date.today() - timedelta(days=100))
    _overdue_debt(db_session, d["apartments"][2].id, due=date.today() - timedelta(days=100))

    client.post("/login", data={"email": "admin@test", "password": "test1234"})
    response = client.post("/debts/late-fees/apply", follow_redirects=False)
    assert response.status_code == 303
    fees = db_session.query(models.Debt).filter_by(category=models.DEBT_CAT_GECIKME).all()
    assert len(fees) == 2

    # Hemen ardından ikinci toplu tahakkuk yeni borç üretmez
    client.post("/debts/late-fees/apply", follow_redirects=False)
    fees = db_session.query(models.Debt).filter_by(category=models.DEBT_CAT_GECIKME).all()
    assert len(fees) == 2
