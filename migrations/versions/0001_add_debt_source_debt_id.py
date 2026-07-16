"""debts.source_debt_id — gecikme tazminatı borçlarının anaparaya bağlantısı

Revision ID: 0001
Revises:
Create Date: 2026-07-16
"""
from alembic import context, op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Boş veritabanında tabloları create_all açar; taze kurulumda kolon zaten var — atla.
    # Offline modda (--sql) bağlantı olmadığından denetim yapılmaz, DDL olduğu gibi yazılır.
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        if "debts" not in inspector.get_table_names():
            return
        if any(col["name"] == "source_debt_id" for col in inspector.get_columns("debts")):
            return
    with op.batch_alter_table("debts") as batch_op:
        batch_op.add_column(sa.Column("source_debt_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_debts_source_debt_id", "debts", ["source_debt_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("debts") as batch_op:
        batch_op.drop_constraint("fk_debts_source_debt_id", type_="foreignkey")
        batch_op.drop_column("source_debt_id")
