from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..auth import create_session_token, verify_password
from ..config import SESSION_COOKIE, SESSION_MAX_AGE
from ..database import get_db
from ..templating import templates

router = APIRouter()


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"user": None, "error": None})


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(models.User).where(models.User.email == email.strip().lower()))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"user": None, "error": "E-posta veya parola hatalı."},
            status_code=401,
        )
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user.id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
