from alembic import context
from sqlalchemy import create_engine

from app import models  # noqa: F401 — model tablolarının metadata'ya kaydı için
from app.config import DATABASE_URL
from app.database import Base

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=DATABASE_URL, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        # render_as_batch: SQLite'ta ALTER kısıtları için tablo yeniden yazımı
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
