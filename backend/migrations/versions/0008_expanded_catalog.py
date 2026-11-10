"""Admit the explicit expanded synthetic catalogue without rewriting legacy rows."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# Freeze migration vocabulary here; future application changes cannot alter history.
LEGACY = "'keyboard','mouse','headphones'"
EXPANDED = (
    LEGACY
    + ","
    + (
        "'smartphone','laptop','tablet','monitor','camera','smartwatch','speaker',"
        "'cycling','fitness','home_appliance'"
    )
)


def upgrade():
    op.drop_constraint("ck_products_category", "products", type_="check")
    op.create_check_constraint("ck_products_category", "products", f"category IN ({EXPANDED})")


def downgrade():
    # PostgreSQL will reject, atomically, if expanded rows still exist. Never delete them.
    connection = op.get_bind()
    if connection.scalar(
        sa.text(f"SELECT EXISTS(SELECT 1 FROM products WHERE category NOT IN ({LEGACY}))")
    ):
        raise RuntimeError("Expanded products exist; downgrade requires an explicit data migration")
    op.drop_constraint("ck_products_category", "products", type_="check")
    op.create_check_constraint("ck_products_category", "products", f"category IN ({LEGACY})")
