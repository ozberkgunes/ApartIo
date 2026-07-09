from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import models  # noqa: F401 — model tablolarının kaydı için
from .auth import AuthRedirect
from .database import Base, engine
from .routers import (
    announcements,
    auth,
    dashboard,
    documents,
    dues,
    finance,
    messages,
    notifications,
    reports,
    residents,
    staff,
    structure,
    tasks,
    tickets,
    users,
)
from .templating import templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="ApartIo", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(users.router)
app.include_router(structure.router)
app.include_router(residents.router)
app.include_router(dues.router)
app.include_router(finance.router)
app.include_router(announcements.router)
app.include_router(tickets.router)
app.include_router(staff.router)
app.include_router(tasks.router)
app.include_router(messages.router)
app.include_router(notifications.router)
app.include_router(documents.router)
app.include_router(reports.router)


@app.exception_handler(AuthRedirect)
async def auth_redirect_handler(request: Request, exc: AuthRedirect):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return templates.TemplateResponse(
        request,
        "error.html",
        {"user": None, "status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )
