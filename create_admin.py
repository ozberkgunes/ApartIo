"""İlk site yöneticisi hesabını oluşturur. Çalıştırma: python create_admin.py

Tablolar yoksa oluşturur (create_all), ardından interaktif olarak e-posta,
ad soyad ve şifre sorup tek bir site yöneticisi kaydeder. Demo verisi basmaz.
"""

import getpass

from sqlalchemy import select

from app import models
from app.auth import hash_password
from app.database import Base, SessionLocal, engine


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        email = input("Yönetici e-posta: ").strip().lower()
        if not email or "@" not in email:
            print("Geçerli bir e-posta girin.")
            return
        if db.scalar(select(models.User).where(models.User.email == email)):
            print(f"{email} zaten kayıtlı, işlem yapılmadı.")
            return

        full_name = input("Ad Soyad: ").strip()
        password = getpass.getpass("Şifre: ")
        password2 = getpass.getpass("Şifre (tekrar): ")
        if password != password2:
            print("Şifreler eşleşmiyor, işlem yapılmadı.")
            return
        if len(password) < 8:
            print("Şifre en az 8 karakter olmalı.")
            return

        admin = models.User(
            email=email, full_name=full_name or "Site Yöneticisi",
            role=models.ROLE_SITE_MANAGER, password_hash=hash_password(password),
        )
        db.add(admin)
        db.commit()
        print(f"Site yöneticisi oluşturuldu: {email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
