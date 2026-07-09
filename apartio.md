# ApartIo — Proje Durum Dokümanı

> Son güncelleme: 09.07.2026
> Durum: **Faz 1 ve Faz 2 tamamlandı**, gerçek site verisi (Troaspark) yüklendi ve finans eklentileri devrede; Render'da yayında; Faz 3 bekliyor.

## 1. Proje Özeti

Site/apartman yönetimi web uygulaması. Üç kullanıcı profili vardır:

| Rol | Erişim Kapsamı |
|---|---|
| **Site Yöneticisi** (`site_manager`) | Tüm kullanıcılar, borçlar, ödemeler, aidatlar, daireler — sınırsız erişim ve tüm CRUD işlemleri |
| **Apartman Yöneticisi** (`building_manager`) | Sadece atandığı bloktaki daireler, sakinler ve finans kayıtları |
| **Apartman Sakini** (`resident`) | Sadece kendi dairesi, borçları, ödemeleri ve kapsamındaki duyurular/belgeler |

Kapsam kuralları tek merkezden (`app/scoping.py`) uygulanır; her liste/detay sorgusu role göre filtrelenir, kapsam dışı kayıt isteklerine 403 döner.

## 2. Teknoloji Yığını

- **Backend:** Python, FastAPI
- **Veritabanı:** SQLAlchemy 2.0 ORM — geliştirmede SQLite (`apartio.db`), üretimde `DATABASE_URL` ortam değişkeni ile PostgreSQL
- **Frontend:** Sunucu taraflı Jinja2 şablonları + Bootstrap 5.3 + Chart.js 4 + DataTables 2 (CDN; ayrı Node/React projesi yok — `planned-actual-trip-analysis` projesiyle aynı yaklaşım)
- **Kimlik doğrulama:** bcrypt parola hash + `itsdangerous` imzalı oturum cookie'si (7 gün)
- **Test:** pytest + FastAPI TestClient (39 test)

### Çalıştırma

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python seed.py         # demo verisi (bir kez)
.venv/bin/python import_excel.py # "Aylık Ödeme Takip Dosyası - 2.xlsx" → Troaspark Sitesi (idempotent)
.venv/bin/python run.py          # http://127.0.0.1:8010 (8000 portu başka projede)
.venv/bin/python -m pytest tests/ -q
```

### Dağıtım (Render) — 09.07.2026

- `run.py` ortama duyarlı: lokalde `127.0.0.1:8010` + hot-reload; Render'da (`RENDER` env değişkeni set) `0.0.0.0:$PORT`, reload kapalı. `PORT`'u Render kendisi atar, elle tanımlanmaz.
- Önerilen start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- `apartio.db` repoya commit'li (gitignore'dan çıkarıldı) — deploy sonrası gerçek veriyle açılır.
- **Kısıt:** Render diski geçicidir; canlıda girilen veri her deploy/yeniden başlatmada git'teki kopyaya döner. Çare: dashboard'daki Veri Yedekleme kartı (aşağıda) ile indir/geri yükle; kalıcı çözüm için persistent disk veya PostgreSQL (`DATABASE_URL`).

Kullanıcılar (parola hepsi için `demo1234`): `admin@apart.io` (site yöneticisi) + Excel'den aktarılan kat malikleri `ad.soyad@troaspark.local` (rol: sakin).

> **Mevcut geliştirme veritabanının durumu (08.07.2026):** `seed.py`'nin ürettiği Gül Sitesi demo verisi ve demo kullanıcıları (blok@, sakin@, ayse@ vb.) kullanıcı isteğiyle tamamen silindi; veritabanında yalnız **Troaspark Sitesi** var (3 blok, 120 daire, 33 malik). `admin@apart.io` tek site yöneticisi olduğu için korundu. Sıfırdan kurulumda `seed.py` yine Gül Sitesi'ni üretir — gerekmiyorsa atlanıp doğrudan `import_excel.py` çalıştırılabilir (tabloları o da oluşturur; ancak admin kullanıcıyı yalnız seed açar).

### Proje Yapısı

```
ApartIo/
├── run.py / seed.py / import_excel.py / requirements.txt
├── app/
│   ├── main.py            # FastAPI app, router kayıtları, hata yönlendirmeleri
│   ├── config.py          # SECRET_KEY, DATABASE_URL, UPLOAD_DIR (env'den)
│   ├── database.py        # engine, SessionLocal, get_db
│   ├── models.py          # tüm SQLAlchemy modelleri
│   ├── auth.py            # parola hash, oturum cookie, require_role
│   ├── scoping.py         # rol bazlı veri kapsamı filtreleri (tek merkez)
│   ├── templating.py      # Jinja2 ortamı, ₺ biçimlendirme filtresi
│   ├── services/
│   │   ├── finance.py     # aidat→borç üretimi, ödeme durumu, dashboard özetleri
│   │   └── notify.py      # uygulama içi bildirim üretimi
│   ├── routers/           # auth, dashboard, users, structure, residents, dues,
│   │                      # finance, announcements, tickets, staff, tasks,
│   │                      # messages, notifications, documents, reports
│   ├── templates/         # base + modül şablonları
│   └── static/
├── tests/                 # conftest + 39 test
└── uploads/               # yüklenen belgeler (gitignore'da)
```

## 3. Veri Modeli

| Model | Açıklama |
|---|---|
| `User` | E-posta, bcrypt hash, rol, blok ataması (apartman yöneticisi için), aktif/pasif |
| `Site` → `Block` → `Apartment` | Yapı hiyerarşisi; kat bilgisi dairede `floor_no`, nitelik (`unit_type`: İŞ YERİ/1+1/2+1...), `area_m2` ve doğalgaz aboneliği (`gas_subscribed`: yapıldı/yapılmadı/bilinmiyor) dairede tutulur |
| `Occupancy` | Daire–kullanıcı ilişkisi: malik (`owner`) / kiracı (`tenant`), başlangıç/bitiş tarihli |
| `DuesDefinition` | Aidat tanımı: dönem (YYYY-AA), tutar, kapsam (tüm site veya tek blok); `is_surcharge` bayrağı ek aidat (zam) tanımlarını işaretler |
| `Debt` | Daireye kesilen borç (aidattan üretilen, toplu veya manuel); kategori: aidat/demirbaş/doğalgaz/doğalgaz avans/diğer; `bill_to_owner` bayrağı borcu kiracı yerine malike bağlar; durum: bekliyor/kısmi/ödendi |
| `Payment` | Tahsilat (gelir): tutar, yöntem, tahsil eden |
| `Expense` | Gider: kategori, kapsam, tutar |
| `Announcement` | Duyuru: site geneli veya blok kapsamlı |
| `Staff` | Personel: ad, görev (kapıcı/güvenlik/teknisyen...), telefon |
| `Ticket` + `TicketComment` | Talep/arıza: kategori, öncelik, durum, yorumlar |
| `WorkOrder` | Görev/iş emri: personel ataması, termin, talep bağlantısı |
| `MessageThread` + `Message` | Birebir mesajlaşma, okundu takibi |
| `Notification` | Uygulama içi bildirim: başlık, bağlantı, okundu durumu |
| `Document` | Belge: kategori, kapsam, "sakinlere açık" bayrağı, disk üzerinde saklama |

Önemli iş kuralları:
- **Borç sorumlusu:** dairenin aktif kiracısı varsa kiracı, yoksa malik. İstisna: `bill_to_owner=True` borçlar (demirbaş ve doğalgaz avansı, KMK gereği) her zaman kat malikine aittir (`services/notify.py::responsible_user_id`).
- **Aidat → borç üretimi:** kapsamdaki her daireye tek borç (kategori: aidat); mükerrer üretim engellenir (`services/finance.py::generate_debts_for_dues`).
- **Toplu borçlandırma:** `/debts/bulk` — kapsam (site/blok) + kategori + tutar tipi (daire başına sabit veya m² başına birim fiyat) ile kapsamdaki tüm dairelere borç; m² bilgisi olmayan daireler `per_m2` modunda atlanır.
- **Ek aidat (zam) mekanizması — KMK m.20:** ayın 20'sinden sonra cari dönem giderleri aidat tahakkukunu aşıyorsa sistem açığı daire sayısına eşit bölerek öneri üretir (`services/finance.py::surcharge_proposal`); dashboard ve `/dues` sayfasında uyarı gösterilir, site yöneticisi onaylayınca (`POST /dues/surcharge/apply`) `is_surcharge=True` aidat tanımı + borçlar oluşur. Dönem başına bir kez uygulanır.
- **Ödeme → durum:** toplam ödeme tutara ulaşınca `paid`, kısmiyse `partial`.
- **Aktif / ileri tarihli borç:** vadesi cari ay ve öncesine düşen borçlar "aktif", cari aydan sonraki döneme tahakkuk edenler "ileri tarihli"dir (`Debt.is_future` — hesaplanır, ay değişince otomatik kayar). `/debts` sayfasında zamanlama filtresi; dashboard KPI'ları aktif ve ileri tarihli toplamları ayrı gösterir.
- **Doğalgaz abonelik takibi:** `/gas-subscriptions` (Yapı menüsü) — daire bazında abone / abone değil / bilinmiyor durumu, KPI sayaçları, filtre ve tek tıkla durum güncelleme; blok yöneticisi yalnız kendi bloğunu görür/değiştirir. İlk durumlar Excel'in DOĞALGAZ ABONELİK sayfasından içe aktarılır.
- **Excel içe aktarma:** `import_excel.py` — "Aylık Ödeme Takip Dosyası"ndan 120 daire (A/B/C blok), kat malikleri, demirbaş (Temmuz–Eylül 2026) ve aidat (Haziran–Aralık 2026) tahakkuk/ödemeleri; blok/daire her zaman etiket kolonundan çözülür (BLOK kolonu güvenilmez), Excel başlıklarındaki bayat 2024 tarihleri `YEAR_OVERRIDE` ile 2026'ya çevrilir (site açılışı: Haziran 2026), idempotenttir.

## 4. Tamamlananlar

### ✅ Faz 1 (MVP) — tamamlandı

| # | Modül | Uygulama |
|---|---|---|
| 1 | Kimlik Doğrulama | `/login`, `/logout` — cookie oturumu, bcrypt |
| 2 | Kullanıcı Yönetimi | `/users` — CRUD (site yöneticisi), pasifleştirme; blok yöneticisi kendi bloğunu salt okunur görür |
| 3 | Yetkilendirme | `require_role` dependency + `scoping.py` kapsam filtreleri |
| 4 | Site Yönetimi | `/sites` — CRUD |
| 5 | Blok Yönetimi | `/blocks` — CRUD |
| 6 | Kat Yönetimi | Daire üzerinde `floor_no` alanı (ayrı tablo gerekirse sonra normalize edilir) |
| 7 | Daire Yönetimi | `/apartments` — CRUD + detay sayfası |
| 8 | Malik Bilgileri | `/residents` — Occupancy ataması (owner) |
| 9 | Kiracı Bilgileri | `/residents` — Occupancy ataması (tenant), sonlandırma |
| 10 | Dashboard | `/` — rol bazlı: KPI kartları, 6 aylık gelir/gider grafiği, borç durumu grafiği; sakin kendi bakiyesini görür |
| 11 | Aidat Yönetimi | `/dues` — dönemsel tanım (site veya blok kapsamı) |
| 12 | Borç Yönetimi | `/debts` — aidattan otomatik üretim + manuel borç, durum filtresi |
| 13 | Gelir Yönetimi | `/debts/{id}` tahsilat kaydı + `/payments` listesi |
| 14 | Gider Yönetimi | `/expenses` — kategori bazlı gider girişi |
| 18 | Duyurular | `/announcements` — site/blok kapsamlı yayınlama |

### ✅ Faz 2 — tamamlandı

| # | Modül | Uygulama |
|---|---|---|
| 21 | Talep / Arıza | `/tickets` — sakin talep açar (kategori/öncelik), yönetici durum değiştirir, yorumlar |
| 22 | İş Emri | Talepten tek tıkla personele atanmış iş emri üretimi |
| 23 | Personel | `/staff` — personel kartları, aktif/pasif |
| 24 | Görev Yönetimi | `/tasks` — görev oluşturma, Başlat → Tamamla akışı, termin takibi |
| 19 | Bildirimler | Uygulama içi bildirim merkezi `/notifications` + navbar'da canlı sayaçlı zil. Tetikleyiciler: yeni talep→yöneticiler, durum/yorum→talep sahibi, mesaj→alıcı, duyuru→kapsamdaki sakinler, aidat borcu→daire sorumlusu. (SMS/e-posta kanalları Faz 4'te) |
| 20 | Mesajlaşma | `/messages` — sakin ↔ yönetici birebir konuşma, okunmamış rozetleri; sakin yalnızca kendi yöneticilerine yazabilir |
| 17/42 | Raporlar | `/reports` — tarih aralığı filtreli KPI'lar, aylık gelir/gider grafiği, gider dağılımı, en borçlu daireler, CSV dışa aktarım (borç/tahsilat/gider, Excel uyumlu) |
| 26/27 | Dosya / Evrak | `/documents` — 10 MB sınırlı yükleme, kategori, "sakinlere açık" seçeneği, erişim kontrollü indirme |

### ✅ Faz 2 sonrası eklentiler — 07–08.07.2026

| İş | Uygulama |
|---|---|
| Excel içe aktarma | `import_excel.py` — "Aylık Ödeme Takip Dosyası - 2.xlsx" → Troaspark Sitesi: 120 daire (nitelik + m²), 33 kat maliki (`Occupancy` owner), demirbaş borç/ödemeleri (Tem–Eyl 2026, toplam ödeme 94.000₺ Excel ile birebir), aidat borç/ödemeleri (Haz–Ara 2026). İdempotent; bayat 2024 başlık tarihleri `YEAR_OVERRIDE` ile 2026'ya çevrilir |
| Borç kategorileri | `Debt.category` (aidat/demirbaş/doğalgaz/doğalgaz avans/diğer) + `bill_to_owner` (demirbaş ve avans KMK gereği malike); `/debts` sayfasında kategori filtresi ve rozetler |
| Toplu borçlandırma | `POST /debts/bulk` — kapsam + kategori + daire başına sabit veya m² başına birim fiyat; sorumlulara bildirim |
| Ek aidat (zam) — KMK m.20 | Ayın 20'sinden sonra dönem gideri aidat tahakkukunu aşarsa açık daire sayısına eşit bölünüp önerilir; site yöneticisi onayıyla uygulanır, dönem başına bir kez (`surcharge_proposal` / `apply_surcharge`) |
| Aktif / ileri tarihli borç | `Debt.is_future` (hesaplanır): vadesi cari aydan sonraki döneme düşen borçlar "ileri tarihli"; `/debts` zamanlama filtresi, dashboard'da ayrık toplamlar |
| Doğalgaz abonelik takibi | `/gas-subscriptions` — daire bazlı abone/değil/bilinmiyor (Excel'den 42/22/56), KPI + filtre + tek tıkla güncelleme; `Apartment.gas_subscribed` |
| Veri temizliği | Gül Sitesi demo verisi silindi (admin korundu); test amaçlı kesilen 56 avans borcu + bildirimleri kaldırıldı; curl kaynaklı bozuk Türkçe karakterli 60 kayıt onarıldı |

### ✅ Eklentiler — 09.07.2026

| İş | Uygulama |
|---|---|
| Render dağıtımı | `run.py` ortama duyarlı hale getirildi (lokal: `127.0.0.1:8010` + reload; Render: `0.0.0.0:$PORT`); `apartio.db` repoya alındı — bkz. "Dağıtım (Render)" bölümü |
| Veri Yedekleme kartı | Dashboard'da (yalnız site yöneticisi): **Veriyi İndir** → `GET /reports/export-db` — SQLite backup API ile tutarlı kopya, tarih+saat damgalı dosya adı; **Yedekten Geri Yükle** → `POST /reports/import-db` — SQLite imza + `integrity_check` + ApartIo tablo doğrulaması, 10 MB sınır, onay penceresi; **verinin son güncellenme zamanı** (dosya mtime) gösterilir. Render'ın geçici diskine karşı manuel yedek/geri yükleme akışı |
| Borç silme | `POST /debts/{id}/delete` (satır bazlı "Sil") + `POST /dues/{id}/undo` ("Borçları Geri Al" — o tanımdan üretilen borçları topluca siler). **Tahsilatı olan borç silinmez** (`?err=` uyarısı); toplu geri almada atlanır ve sayısı raporlanır. Yalnız site yöneticisi |
| Borçlar sayfası | **Sorumlu** kolonu (aktif kiracı, yoksa malik; yalnız yöneticiler görür) + **isim/daire arama** (`?q=`) — mevcut durum/kategori/zamanlama filtreleriyle birlikte çalışır |
| Tahsilatlar sayfası | Aynı `?q=` araması + **tarih aralığı** (`?start=&end=`, geçersiz tarih → 400, ters aralık düzeltilir) + **tarih sıralaması** (`?sort=asc|desc`, Tarih başlığından ▲/▼); tabloya `data-order="[]"` (DataTables sunucu sırasını ezmesin) |
| Raporlar | **Son Gelirler** kartı — seçili tarih aralığındaki son 10 tahsilat (Tarih, Daire, Borç linki, Tutar, Yöntem) |
| Malik/Kiracı sayfası | **Tümü / Malik / Kiracı** tip filtresi (`?occ_type=`) + **isim arama** (`?q=`); birlikte kullanılabilir |

### Test Kapsamı (39 test — tümü geçiyor)

- Parola hash/doğrulama
- Daire kapsam filtreleri (3 rol) ve `can_access_apartment`
- Aidat→borç üretimi + mükerrer üretim engeli
- Ödeme sonrası borç durumu geçişleri
- Login akışı, hatalı parola, rol bazlı 403'ler
- Talep kapsamı, talep→yönetici bildirimi, başkasının dairesine talep engeli
- Mesajlaşma erişim kontrolü (üçüncü kişi 403), görev kapsamı, rapor yetkisi
- Toplu borçlandırma (sabit/m², blok yöneticisi kendi bloğuyla sınırlı), kategori doğrulaması
- Ek aidat: gün > 20 koşulu, açık hesabı, dönem başına tek uygulama, yetki (403)
- Excel içe aktarma yardımcıları (etiket çözümleme, ay-kolon eşleme, e-posta/tutar dönüşümü)
- Borç silme: tahsilatsız borç silinir, tahsilatlı reddedilir, yetkisiz rol 403, toplu geri almada atlanan sayısı
- Borç/tahsilat filtreleri: Sorumlu kolonu (sakinde gizli), `q` araması, tarih aralığı, asc/desc sıralama, geçersiz tarih 400
- Raporlarda Son Gelirler (aralık içi görünür, aralık dışı görünmez); malik/kiracı tip filtresi + isim arama

## 5. Yapılacaklar

### 🔜 Faz 3 — sıradaki

| # | Modül | Not |
|---|---|---|
| 31 | Araç Yönetimi | Araçlar sisteme tanımlanır (plaka, daire ilişkisi) |
| 32 | Otopark Yönetimi | Park yerleri tanımı ve daire/araç ataması |
| 33 | Ziyaretçi Yönetimi | QR kodlu misafir sistemi |
| 34 | Kargo Takibi | Kargo teslim süreçleri (geldi → teslim edildi) |
| 36 | Ortak Alan Yönetimi | Rezervasyona konu alanlar (toplantı salonu, spor salonu...) |
| 35 | Rezervasyon Sistemi | Ortak alan rezervasyonları (çakışma kontrolü) |
| 37 | Sayaç Yönetimi | Sayaç tanımları (su/elektrik/doğalgaz, daire bazlı) |
| 38 | Sayaç Okuma | Dönemsel tüketim girişleri; istenirse tüketimden borç üretimi |
| 40 | Bakım Takvimi | Periyodik bakım planları (asansör, yangın tüpü...); iş emriyle entegrasyon |
| 41 | Takvim | Etkinlik + bakım takvimi görünümü |

### 🔮 Faz 4 — gelecek

| # | Modül | Not |
|---|---|---|
| 43 | Online Ödeme | Banka/ödeme kuruluşu entegrasyonu (iyzico, PayTR vb.) |
| 44 | Entegrasyonlar | SMS ve e-posta gönderimi — mevcut `services/notify.py` kanal ekleyecek şekilde tasarlandı |
| 45 | Mobil Uygulama | Mevcut rotaların yanına `/api` JSON katmanı eklenerek |
| 46 | Web Yönetim Paneli | Gelişmiş yönetim ekranları |
| 47 | Çoklu Dil | i18n altyapısı |
| 48 | Çoklu Site Desteği | Veri modeli hazır (Site tablosu); site yöneticisi–site ataması eklenecek |
| 49/50 | Güvenlik Kayıtları / Log | Denetim logları, işlem kayıtları |
| 51 | Yedekleme | Otomatik veri yedekleme |
| 52 | Acil Durum Bilgileri | Acil iletişim ve prosedürler |
| 28/29/30 | Karar Defteri / Toplantılar / Anket | Faz sıralamasında sonraya bırakıldı |
| 53 | Yapay Zekâ | Akıllı duyuru/rapor/sınıflandırma |

### Teknik Borç / İyileştirmeler

- [ ] **Alembic migration** — şu an `create_all` ile tablo oluşturuluyor; `gas_subscribed` kolonu mevcut DB'ye elle `ALTER TABLE` ile eklendi (08.07.2026) — bu tür değişiklikler artıyor, Alembic'e geçilmeli
- [ ] Üretim dağıtımı: `APARTIO_SECRET_KEY` zorunlu kılınmalı, PostgreSQL + HTTPS + reverse proxy
- [ ] CSRF koruması (form POST'ları için)
- [ ] Sayfalama — büyük veri setlerinde sunucu taraflı sayfalama (şu an DataTables istemci tarafında)
- [ ] `starlette.testclient` httpx uyarısı — ileride `httpx2` paketine geçiş
- [ ] Kat Yönetimi'nin ayrı tabloya normalize edilmesi (ihtiyaç olursa)

## 6. Mimari Kararlar (özet)

1. **SPA yerine sunucu taraflı şablonlar:** Referans projeyle tutarlılık, tek dil (Python), basit dağıtım. Mobil (Faz 4) için ayrı `/api` katmanı eklenecek.
2. **Kapsam tek merkezde:** Tüm rol filtreleri `scoping.py`'de; yeni modül eklerken tek yapılması gereken oraya `scoped_*` fonksiyonu eklemek.
3. **Bildirimler uygulama içi:** `notify.py` kanal bağımsız yazıldı; Faz 4'te SMS/e-posta aynı fonksiyondan dallanacak.
4. **Para birimi `Decimal`/`Numeric(12,2)`:** kayan nokta hatası yok; ₺ gösterimi Jinja `tl` filtresiyle.
5. **Soft delete kullanıcılarda:** Kullanıcı silinmez, pasifleştirilir (FK bütünlüğü); yapısal kayıtlarda bağımlı kayıt varsa silme engellenir.
