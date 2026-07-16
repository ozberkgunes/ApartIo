#!/usr/bin/env bash
# Sunucuda yeni sürümü çeker ve uygulamayı yeniden başlatır.
# Kullanım (sunucuda): bash /projects/ApartIo/deploy/update.sh
set -euo pipefail

cd /projects/ApartIo
git pull
.venv/bin/pip install -q -r requirements.txt
chown -R www-data:www-data /projects/ApartIo
systemctl restart apartio
systemctl --no-pager --lines=5 status apartio
