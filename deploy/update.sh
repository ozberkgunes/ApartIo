#!/usr/bin/env bash
# Sunucuda yeni sürümü çeker ve uygulamayı yeniden başlatır.
# GitHub Actions her main push'unda 'deploy' kullanıcısıyla bunu çalıştırır; elle:
#   sudo -u deploy bash /projects/ApartIo/deploy/update.sh
set -euo pipefail

cd /projects/ApartIo
git fetch origin main
git reset --hard origin/main   # sunucudaki takipli dosyaları GitHub'daki halin aynısı yapar
.venv/bin/pip install -q -r requirements.txt
set -a; source .env.prod; set +a   # DATABASE_URL — migration PostgreSQL'e uygulanır
.venv/bin/alembic upgrade head
sudo /usr/bin/systemctl restart apartio   # sudoers yalnız bu komuta izin verir
systemctl --no-pager --lines=5 status apartio
