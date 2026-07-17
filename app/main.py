import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import models  # noqa: F401 — model tablolarının kaydı için
from .auth import AuthRedirect
from .config import REMINDERS_ENABLED
from .database import Base, SessionLocal, engine
from .services import reminders as reminder_service
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


def _run_reminders_once() -> None:
    db = SessionLocal()
    try:
        reminder_service.send_due_reminders(db)
    finally:
        db.close()


async def _reminder_loop() -> None:
    await asyncio.sleep(reminder_service.REMINDER_STARTUP_DELAY_SECONDS)
    while True:
        try:
            await asyncio.to_thread(_run_reminders_once)
        except Exception:  # zamanlayıcı tek hatayla ölmesin
            logging.getLogger("apartio.reminders").exception("Hatırlatma turu başarısız")
        await asyncio.sleep(reminder_service.REMINDER_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    reminder_task = asyncio.create_task(_reminder_loop()) if REMINDERS_ENABLED else None
    yield
    if reminder_task:
        reminder_task.cancel()
        with suppress(asyncio.CancelledError):
            await reminder_task


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
