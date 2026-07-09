import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("APARTIO_SECRET_KEY", "dev-secret-change-me")
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'apartio.db'}")

SESSION_COOKIE = "apartio_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 gün

UPLOAD_DIR = BASE_DIR / "uploads"
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
