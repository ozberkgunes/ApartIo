# ApartIo — Site Yönetimi Uygulaması

FastAPI + SQLAlchemy + Jinja2 (Bootstrap 5, Chart.js, DataTables) ile site/apartman yönetimi.

- **Faz 1 (MVP):** kimlik doğrulama, rol bazlı yetkilendirme, site/blok/daire, malik-kiracı, aidat, borç, tahsilat, gider, dashboard, duyurular
- **Faz 2:** talep/arıza yönetimi, uygulama içi bildirimler, mesajlaşma, personel, görev/iş emri, finansal raporlar + CSV dışa aktarım, dosya/evrak yönetimi

## Roller

| Rol | Kapsam |
|---|---|
| Site Yöneticisi | Tüm sitelerdeki tüm veriler (CRUD) |
| Apartman Yöneticisi | Sadece atandığı bloğun daireleri, sakinleri ve finans kayıtları |
| Sakin | Sadece kendi dairesi, borçları ve ödemeleri |

## Kurulum ve Çalıştırma

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python seed.py        # demo verisi (bir kez)
.venv/bin/python run.py         # http://127.0.0.1:8000
```

Demo kullanıcılar (parola: `demo1234`):

- `admin@apart.io` — Site Yöneticisi
- `blok@apart.io` — Apartman Yöneticisi (A Blok)
- `sakin@apart.io` — Sakin (A Blok, Daire 2, kiracı)

## Testler

```bash
.venv/bin/python -m pytest tests/ -q
```

## Yapı

- `app/models.py` — SQLAlchemy modelleri (User, Site, Block, Apartment, Occupancy, DuesDefinition, Debt, Payment, Expense, Announcement, Staff, Ticket, WorkOrder, MessageThread/Message, Notification, Document)
- `app/auth.py` — bcrypt parola, imzalı oturum cookie'si, `require_role`
- `app/scoping.py` — rol bazlı veri kapsamı filtreleri
- `app/services/finance.py` — aidat→borç üretimi, ödeme durumu, dashboard özetleri
- `app/services/notify.py` — uygulama içi bildirimler (talep, mesaj, duyuru, aidat borcu)
- `app/routers/` — sayfa rotaları; `app/templates/` — Jinja2 şablonları
- Yüklenen belgeler `uploads/` klasöründe saklanır (10 MB sınırı)

Veritabanı varsayılan olarak SQLite (`apartio.db`); üretim için `DATABASE_URL` ortam değişkeni ile PostgreSQL'e geçilebilir. `APARTIO_SECRET_KEY` üretimde mutlaka değiştirilmelidir.
