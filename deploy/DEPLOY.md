# ApartIo — Linux VPS Kurulum Rehberi

Sunucu: Linux VPS (SSH erişimli), python3.13 + pip kurulu.
Hedef: nginx (port 80) → uvicorn (127.0.0.1:8010) → PostgreSQL (localhost).

> Tüm komutlar sunucuda, root (veya `sudo` ile) çalıştırılır.

## 1. Sistem paketleri

```bash
apt update
apt install -y postgresql nginx ufw python3-venv
```

## 2. PostgreSQL veritabanı

```bash
systemctl enable --now postgresql
sudo -u postgres psql -c "CREATE USER apartio WITH PASSWORD 'BURAYA_GUCLU_SIFRE';"
sudo -u postgres psql -c "CREATE DATABASE apartio OWNER apartio;"
```

Şifreyi bir yere not edin — `.env.prod` içine yazılacak.

## 3. Kodu FileZilla ile yükle

FileZilla ile bağlanın: **SFTP, port 22, SSH kullanıcı bilgileri**
(host = sunucu IP'si). Şu dosya ve klasörleri `/projects/ApartIo` altına
yükleyin:

- `app/` (tüm alt klasörleriyle)
- `requirements.txt`
- `create_admin.py`
- `deploy/`

> Yüklemeyin: `.venv/`, `apartio.db`, `uploads/`, `__pycache__/` —
> bunlar yerel/geçici dosyalardır, sunucuda gerekmez.

> İleride git'e geçilecek: repo GitHub'a push'landıktan sonra kod
> `git clone` ile çekilip güncellemeler `deploy/update.sh` (git pull +
> pip install + restart) ile tek komuta inecek.

## 4. Python ortamı

```bash
cd /projects/ApartIo
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 5. Ortam değişkenleri (.env.prod)

Secret key üret:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

`/projects/ApartIo/.env.prod` dosyasını oluştur:

```
APARTIO_SECRET_KEY=YUKARIDA_URETILEN_DEGER
DATABASE_URL=postgresql+psycopg://apartio:BURAYA_GUCLU_SIFRE@127.0.0.1/apartio
```

```bash
chmod 600 /projects/ApartIo/.env.prod
```

## 6. Tablolar + ilk yönetici hesabı

```bash
cd /projects/ApartIo
set -a && source .env.prod && set +a
.venv/bin/python create_admin.py
```

E-posta, ad soyad ve şifre sorulur; tablolar otomatik oluşur.

## 7. uploads klasörü ve sahiplik

```bash
mkdir -p /projects/ApartIo/uploads
chown -R www-data:www-data /projects/ApartIo
```

## 8. systemd servisi

```bash
cp /projects/ApartIo/deploy/apartio.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now apartio
systemctl status apartio    # "active (running)" görünmeli
```

## 9. nginx

```bash
cp /projects/ApartIo/deploy/nginx-apartio.conf /etc/nginx/sites-available/apartio
ln -s /etc/nginx/sites-available/apartio /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

## 10. Güvenlik duvarı

```bash
ufw allow OpenSSH
ufw allow 80
ufw allow 443
ufw enable
```

## 11. Doğrulama

```bash
curl -I http://127.0.0.1:8010    # sunucuda: HTTP yanıtı gelmeli
```

Tarayıcıdan `http://SUNUCU_IP` → login sayfası açılmalı; oluşturduğunuz
yönetici hesabıyla giriş yapın, bir kayıt ekleyin, sonra
`systemctl restart apartio` yapıp kaydın durduğunu doğrulayın.

## Sorun giderme

```bash
journalctl -u apartio -n 50 --no-pager   # uygulama logları
tail -50 /var/log/nginx/error.log        # nginx logları
```

## Güncelleme (yeni sürüm yükleme)

Şimdilik git kullanılmadığı için güncelleme FileZilla ile yapılır:

1. Değişen dosyaları FileZilla ile `/projects/ApartIo` altına yükleyin
   (genelde sadece `app/` içeriği; `.env.prod` ve `uploads/`'a dokunmayın).
2. Sunucuda:

```bash
cd /projects/ApartIo
.venv/bin/pip install -q -r requirements.txt   # sadece requirements.txt değiştiyse
chown -R www-data:www-data /projects/ApartIo
systemctl restart apartio
```

> Git'e geçildikten sonra bu adımların hepsi tek komut olacak:
> `bash /projects/ApartIo/deploy/update.sh` (git pull + pip install + restart).

## 12. Domain + HTTPS (Let's Encrypt)

Ön koşul: bir alan adı. Let's Encrypt çıplak IP'ye sertifika vermez.

1. Domain sağlayıcınızın DNS panelinde bir **A kaydı** oluşturun:
   `apartio.ornek.com → SUNUCU_IP` (kök domain de olur). Yayılmasını
   bekleyin; `ping apartio.ornek.com` sunucu IP'sini göstermeli.

2. Sunucuda nginx'e domain'i tanıtın —
   `/etc/nginx/sites-available/apartio` içindeki `server_name _;`
   satırını değiştirin:

```nginx
server_name apartio.ornek.com;
```

```bash
nginx -t && systemctl reload nginx
```

3. Sertifikayı alın:

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d apartio.ornek.com
```

   E-posta sorup kuralları onaylattıktan sonra certbot nginx yapılandırmasını
   kendisi düzenler: 443'ü sertifikayla dinletir, HTTP→HTTPS yönlendirmesini
   sorar (yönlendirmeyi **seçin**).

4. Doğrulayın:

```bash
curl -I https://apartio.ornek.com     # HTTP/2 200 görmelisiniz
systemctl list-timers | grep certbot  # otomatik yenileme zamanlayıcısı
certbot renew --dry-run               # yenileme provası
```

Sertifika 90 günlüktür; `certbot.timer` otomatik yeniler, elle işlem gerekmez.

> Not: ufw'de 443 zaten açık (adım 10). VPS sağlayıcının panel güvenlik
> duvarı varsa orada da TCP 443'e izin verilmeli — 80'de yaşanan zaman
> aşımı sorununun aynısı 443'te de olur.

## Sonrası (henüz yapılmadı)

- Git'e geçiş: repo GitHub'a push'lanınca kod `git clone` ile çekilecek,
  güncellemeler `deploy/update.sh` ile yapılacak
- Yedekleme: cron ile günlük `pg_dump apartio`
