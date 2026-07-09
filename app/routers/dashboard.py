from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import models, scoping
from ..auth import get_current_user
from ..database import get_db
from ..services import finance
from ..templating import templates

router = APIRouter()


@router.get("/")
def dashboard(
    request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    announcements = scoping.scoped_announcements(db, user)[:5]
    if user.role in models.MANAGER_ROLES:
        ctx = finance.manager_dashboard(db, user)
    else:
        ctx = finance.resident_dashboard(db, user)
    ctx.update({"user": user, "announcements": announcements})
    return templates.TemplateResponse(request, "dashboard.html", ctx)
