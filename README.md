# ApartIo — Site Yönetimi Uygulaması

FastAPI + SQLAlchemy + Jinja2 (Bootstrap 5, Chart.js, DataTables) ile site/apartman yönetimi. Ayrıntılı proje durumu ve yol haritası için: [apartio.md](apartio.md).

- **Faz 1 (MVP):** kimlik doğrulama, rol bazlı yetkilendirme, site/blok/daire, malik-kiracı, aidat, borç, tahsilat, gider, dashboard, duyurular
- **Faz 2:** talep/arıza yönetimi, uygulama içi bildirimler, mesajlaşma, personel, görev/iş emri, finansal raporlar + CSV dışa aktarım, dosya/evrak yönetimi
- **Faz 2 sonrası eklentiler:** Excel'den gerçek site verisi aktarımı (Troaspark: 3 blok, 120 daire), borç kategorileri + toplu borçlandırma (sabit/m²), KMK m.20 ek aidat önerisi, aktif/ileri tarihli borç ayrımı, doğalgaz abonelik takibi, borç silme ve aidat borçlarını toplu geri alma, borç/tahsilat sayfalarında isim-daire arama + tarih aralığı + sıralama, raporlarda Son Gelirler, malik/kiracı arama ve tip filtresi, dashboard'dan veritabanı yedeği indirme/geri yükleme

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
.venv/bin/python seed.py         # demo verisi (bir kez, isteğe bağlı)
.venv/bin/python import_excel.py # gerçek site verisi: "Aylık Ödeme Takip Dosyası - 2.xlsx" (idempotent)
.venv/bin/python run.py          # http://127.0.0.1:8010
```

Demo kullanıcılar (parola: `demo1234`):

- `admin@apart.io` — Site Yöneticisi
- `blok@apart.io` — Apartman Yöneticisi (A Blok, yalnız seed verisinde)
- `sakin@apart.io` — Sakin (A Blok, Daire 2, kiracı, yalnız seed verisinde)

> Depodaki `apartio.db` gerçek Troaspark verisini içerir; `admin@apart.io` ile giriş yapılır. `seed.py` ayrıca Gül Sitesi demo evrenini üretir.

## Dağıtım (Render)

- `run.py` ortama duyarlıdır: lokalde `127.0.0.1:8010` + hot-reload; Render'da (`RENDER` ortam değişkeni otomatik set) `0.0.0.0:$PORT` ve reload kapalı. `PORT`'u Render kendisi atar, elle tanımlanmaz.
- Önerilen start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Kısıt:** Render'ın diski geçicidir; canlıda girilen veriler her deploy/yeniden başlatmada depodaki `apartio.db` kopyasına döner. Dashboard'daki **Veri Yedekleme** kartıyla (yalnız site yöneticisi) veritabanı indirilip geri yüklenebilir; kalıcı çözüm için persistent disk veya `DATABASE_URL` ile PostgreSQL kullanılmalıdır.

## Testler

```bash
.venv/bin/python -m pytest tests/ -q   # 39 test
```

## Yapı

- `app/models.py` — SQLAlchemy modelleri (User, Site, Block, Apartment, Occupancy, DuesDefinition, Debt, Payment, Expense, Announcement, Staff, Ticket, WorkOrder, MessageThread/Message, Notification, Document)
- `app/auth.py` — bcrypt parola, imzalı oturum cookie'si, `require_role`
- `app/scoping.py` — rol bazlı veri kapsamı filtreleri
- `app/services/finance.py` — aidat→borç üretimi, ödeme durumu, ek aidat önerisi, dashboard özetleri
- `app/services/notify.py` — uygulama içi bildirimler (talep, mesaj, duyuru, aidat borcu)
- `app/routers/` — sayfa rotaları; `app/templates/` — Jinja2 şablonları
- `import_excel.py` — Excel'den daire/malik/borç/ödeme aktarımı (idempotent)
- Yüklenen belgeler `uploads/` klasöründe saklanır (10 MB sınırı)

Veritabanı varsayılan olarak SQLite (`apartio.db`); üretim için `DATABASE_URL` ortam değişkeni ile PostgreSQL'e geçilebilir. `APARTIO_SECRET_KEY` üretimde mutlaka değiştirilmelidir.
