"""debt_reminders — otomatik borç hatırlatma kayıtları (İş #56)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-17
"""
from alembic import context, op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # create_all ile açılmış taze kurulumlarda tablo zaten var — atla.
    # Offline modda (--sql) bağlantı olmadığından denetim yapılmaz, DDL olduğu gibi yazılır.
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        if "debt_reminders" in inspector.get_table_names():
            return
    op.create_table(
        "debt_reminders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("debt_id", sa.Integer(), sa.ForeignKey("debts.id"), nullable=False),
        sa.Column("period_key", sa.String(16), nullable=False),
        sa.Column("sent_on", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("debt_id", "period_key", name="uq_debt_reminders_debt_period"),
    )
    op.create_index("ix_debt_reminders_debt_id", "debt_reminders", ["debt_id"])


def downgrade() -> None:
    op.drop_index("ix_debt_reminders_debt_id", table_name="debt_reminders")
    op.drop_table("debt_reminders")
