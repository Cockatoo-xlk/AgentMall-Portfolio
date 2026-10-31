"""T01 identity, catalog and cart only; schema changes do not seed data."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def record_columns():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade():
    op.create_table(
        "users",
        *record_columns(),
        sa.Column("login", sa.String(100), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("store_id", sa.Uuid()),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("role IN ('buyer','merchant')", name="ck_users_role"),
        sa.CheckConstraint("role != 'merchant' OR store_id IS NOT NULL", name="ck_merchant_store"),
    )
    op.create_table(
        "products",
        *record_columns(),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("attributes", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("price_cents", sa.BigInteger(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("on_hand", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("catalog_version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("0 <= reserved AND reserved <= on_hand", name="ck_products_inventory"),
        sa.CheckConstraint("price_cents >= 0", name="ck_products_price"),
        sa.CheckConstraint("catalog_version >= 1", name="ck_products_version"),
        sa.CheckConstraint(
            "category IN ('keyboard','mouse','headphones')", name="ck_products_category"
        ),
        sa.UniqueConstraint("id", "store_id", name="uq_products_id_store"),
    )
    op.create_index(
        "ix_products_public_filter", "products", ["store_id", "active", "category", "price_cents"]
    )
    op.create_table(
        "carts",
        *record_columns(),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "store_id", name="uq_carts_user_store"),
        sa.UniqueConstraint("id", "store_id", name="uq_carts_id_store"),
        sa.CheckConstraint("version >= 0", name="ck_carts_version"),
    )
    op.create_table(
        "cart_items",
        *record_columns(),
        sa.Column("cart_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.UniqueConstraint("cart_id", "product_id", name="uq_cart_items_cart_product"),
        sa.CheckConstraint("quantity BETWEEN 1 AND 10", name="ck_cart_items_quantity"),
        sa.ForeignKeyConstraint(["cart_id", "store_id"], ["carts.id", "carts.store_id"]),
        sa.ForeignKeyConstraint(["product_id", "store_id"], ["products.id", "products.store_id"]),
    )


def downgrade():
    op.drop_table("cart_items")
    op.drop_table("carts")
    op.drop_table("products")
    op.drop_table("users")
