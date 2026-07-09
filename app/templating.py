from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.templating import Jinja2Templates

from . import models

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def format_tl(value) -> str:
    if value is None:
        value = 0
    s = f"{Decimal(value):,.2f}"
    # 1,234.56 -> 1.234,56 (Türkçe biçim)
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} ₺"


templates.env.filters["tl"] = format_tl
templates.env.globals.update(
    ROLE_LABELS=models.ROLE_LABELS,
    OCC_TYPE_LABELS=models.OCC_TYPE_LABELS,
    DEBT_STATUS_LABELS=models.DEBT_STATUS_LABELS,
    PAYMENT_METHOD_LABELS=models.PAYMENT_METHOD_LABELS,
    today=lambda: date.today().isoformat(),
)
