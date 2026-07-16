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
.venv/bin/alembic stamp head    # taze kurulumda şema günceldir; migration geçmişini işaretle
```

E-posta, ad soyad ve şifre sorulur; tablolar otomatik oluşur. `alembic stamp head`
yalnız sıfırdan kurulumda gerekir — sonraki şema değişikliklerini `update.sh`
içindeki `alembic upgrade head` uygular.

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

## Güncelleme (git + GitHub Actions ile otomatik)

Hedef: yerelde `git push` → GitHub Actions sunucuya SSH'lanır →
`deploy/update.sh` çalışır (git fetch/reset + pip install + **alembic upgrade** + restart).
Workflow dosyası repoda: `.github/workflows/deploy.yml`.

> Şema değişiklikleri Alembic migration'larıyla gelir (`migrations/versions/`);
> `update.sh` bunları `alembic upgrade head` ile PostgreSQL'e otomatik uygular.
> Mevcut (Alembic öncesi kurulmuş) veritabanında ilk `upgrade head` doğrudan
> çalışır — ilk migration eksik kolonu tespit edip ekler, tablo zaten
> güncelse kendini atlar.

### A. Sunucuyu repoya bağla (bir kez)

Mevcut `/projects/ApartIo` klasörü silinmeden repoya bağlanır;
`.env.prod` ve `uploads/` gitignore'da olduğu için etkilenmez:

```bash
apt install -y git
cd /projects/ApartIo
git init -b main
git remote add origin https://github.com/ozberkgunes/ApartIo.git
git config --global --add safe.directory /projects/ApartIo
git fetch origin
git reset --hard origin/main
```

> Repo **private** ise `https://...` yerine SSH kullanın: salt-okunur bir
> deploy key oluşturun — `ssh-keygen -t ed25519 -f /root/.ssh/apartio_deploy -N ""`
> deyip `.pub` içeriğini GitHub'da **Settings → Deploy keys**'e ekleyin
> ("Allow write access" işaretlemeyin), `/root/.ssh/config`'e
> `Host github.com` / `IdentityFile /root/.ssh/apartio_deploy` satırlarını
> yazın ve remote'u `git@github.com:ozberkgunes/ApartIo.git` yapın.

### B. deploy kullanıcısı + Actions'ın SSH erişimi (bir kez)

Actions sunucuya root ile değil, yetkisi tek işe indirilmiş `deploy`
kullanıcısıyla bağlanır: kod ve venv `deploy`'a aittir, `uploads/`
www-data'da kalır (uygulama yazar), sudo yalnız `systemctl restart apartio`
komutuna izinlidir. Anahtar sızsa bile shell yetkisi "deploy tetiklemek"le
sınırlı kalır.

```bash
# 1) Kullanıcı + SSH anahtarı
adduser --disabled-password --gecos "" deploy
usermod -aG systemd-journal deploy      # status çıktısında loglar görünsün
install -m 700 -o deploy -g deploy -d /home/deploy/.ssh
ssh-keygen -t ed25519 -f /root/.ssh/github_actions -N "" -C "github-actions-deploy"
install -m 600 -o deploy -g deploy /root/.ssh/github_actions.pub /home/deploy/.ssh/authorized_keys
cat /root/.ssh/github_actions           # private key — aşağıdaki SSH_KEY secret'ı

# 2) Sahiplik: kod deploy'un, uploads www-data'nın, .env.prod yalnız deploy okur
chown -R deploy:deploy /projects/ApartIo
chown -R www-data:www-data /projects/ApartIo/uploads
chown deploy:deploy /projects/ApartIo/.env.prod && chmod 600 /projects/ApartIo/.env.prod
sudo -u deploy git config --global --add safe.directory /projects/ApartIo

# 3) Sınırlı sudo: deploy yalnız apartio servisini yeniden başlatabilir
echo 'deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart apartio' > /etc/sudoers.d/apartio-deploy
chmod 440 /etc/sudoers.d/apartio-deploy
```

> `.env.prod`'u systemd (`EnvironmentFile`) root olarak okuduğundan servis
> etkilenmez; `update.sh` ise migration için dosyayı `deploy` olarak source
> eder. `git reset` sonrası yeni dosyalar umask gereği herkese okunur
> oluştuğundan www-data kodu okumaya devam eder — ayrıca `chown` gerekmez.

Test: `sudo -u deploy bash /projects/ApartIo/deploy/update.sh` elle çalışmalı.

GitHub'da **ApartIo → Settings → Secrets and variables → Actions →
New repository secret** ile üç secret ekleyin:

| Secret     | Değer                                                   |
| ---------- | ------------------------------------------------------- |
| `SSH_HOST` | sunucu IP'si                                            |
| `SSH_USER` | `deploy`                                                |
| `SSH_KEY`  | `/root/.ssh/github_actions` dosyasının TAMAMI (private) |

> İsteğe bağlı sıkılaştırma: artık root ile SSH gerekmediğinden
> `/etc/ssh/sshd_config`'de `PermitRootLogin no` yapılabilir — ama önce
> FileZilla/SSH erişiminizi `deploy` veya başka bir kullanıcıya taşıdığınızdan
> emin olun, yoksa sunucuya erişiminiz kapanır.

### C. Kullanım

Yerelde commit + `git push` yeterli. GitHub'da **Actions** sekmesinden
çalışmayı izleyin; yeşilse sunucu güncellenmiştir. Acil durumda elle:

```bash
sudo -u deploy bash /projects/ApartIo/deploy/update.sh
```

> Not: `update.sh` sunucudaki takipli dosyaları `git reset --hard` ile
> GitHub'daki hale eşitler — sunucuda koda elle dokunmayın, değişiklik
> her zaman yerelden push'lanmalı. `.env.prod` ve `uploads/` etkilenmez.

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

- Yedekleme: cron ile günlük `pg_dump apartio`
