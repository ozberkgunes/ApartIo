import bcrypt
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from . import models
from .config import SECRET_KEY, SESSION_COOKIE, SESSION_MAX_AGE
from .database import get_db


class AuthRedirect(Exception):
    """Oturum yoksa /login'e yönlendirilir (main.py'deki handler yakalar)."""


_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="apartio-session")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_session_token(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def get_current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise AuthRedirect()
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise AuthRedirect()
    user = db.get(models.User, data.get("uid"))
    if user is None or not user.is_active:
        raise AuthRedirect()
    return user


def require_role(*roles: str):
    def dependency(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Bu sayfaya erişim yetkiniz yok.")
        return user

    return dependency
