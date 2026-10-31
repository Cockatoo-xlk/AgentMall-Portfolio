"""T02 immutable proposals, confirmations and transactional orders."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "action_proposals",
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(length=30), nullable=False),
        sa.Column("canonical_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("origin_request_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_slot", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("action_type = 'CHECKOUT'", name="ck_proposal_action"),
        sa.CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','EXECUTED','EXPIRED')",
            name="ck_proposal_status",
        ),
        sa.CheckConstraint("schema_version = 1", name="ck_proposal_schema"),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_id", "origin_request_id", "proposal_slot", name="uq_proposal_request_slot"
        ),
        sa.UniqueConstraint("id", "actor_id", "store_id", name="uq_proposal_scope"),
    )
    op.create_table(
        "confirmations",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_ref", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("decision IN ('approve','reject')", name="ck_confirmation_decision"),
        sa.ForeignKeyConstraint(
            ["proposal_id", "actor_id", "store_id"],
            ["action_proposals.id", "action_proposals.actor_id", "action_proposals.store_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id", name="uq_confirmation_proposal"),
    )
    op.create_table(
        "idempotency_requests",
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=40), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("action_id", sa.Uuid(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "operation IN ('prepare_checkout','execute_checkout')", name="ck_idempotency_operation"
        ),
        sa.ForeignKeyConstraint(
            ["action_id", "actor_id", "store_id"],
            ["action_proposals.id", "action_proposals.actor_id", "action_proposals.store_id"],
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action_id", name="uq_idempotency_action"),
        sa.UniqueConstraint("store_id", "actor_id", "operation", "key", name="uq_idempotency_key"),
    )
    op.create_table(
        "orders",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("total_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("address_label", sa.String(length=30), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("policy_version", sa.String(length=40), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("address_label IN ('demo_dorm','demo_home')", name="ck_order_address"),
        sa.CheckConstraint("currency = 'CNY'", name="ck_order_currency"),
        sa.CheckConstraint("status = 'PENDING_PAYMENT'", name="ck_order_status"),
        sa.CheckConstraint("total_cents >= 0", name="ck_order_total"),
        sa.CheckConstraint("version >= 1", name="ck_order_version"),
        sa.ForeignKeyConstraint(
            ["proposal_id", "user_id", "store_id"],
            ["action_proposals.id", "action_proposals.actor_id", "action_proposals.store_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "store_id", name="uq_order_store"),
        sa.UniqueConstraint("proposal_id", name="uq_order_proposal"),
    )
    op.create_index("ix_orders_status_expires", "orders", ["status", "expires_at"], unique=False)
    op.create_index("ix_orders_user_created", "orders", ["user_id", "created_at"], unique=False)
    op.create_table(
        "business_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=30), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("payload_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["action_id"],
            ["action_proposals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["aggregate_id"],
            ["orders.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action_id", "event_type", name="uq_business_action_event"),
    )
    op.create_table(
        "order_items",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("unit_price_cents", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("attributes_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity BETWEEN 1 AND 10", name="ck_order_item_quantity"),
        sa.CheckConstraint("unit_price_cents >= 0", name="ck_order_item_price"),
        sa.ForeignKeyConstraint(
            ["order_id", "store_id"],
            ["orders.id", "orders.store_id"],
        ),
        sa.ForeignKeyConstraint(
            ["product_id", "store_id"],
            ["products.id", "products.store_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "product_id", name="uq_order_item_product"),
    )
    install_guards()


def downgrade():
    remove_guards()
    op.drop_table("order_items")
    op.drop_table("business_events")
    op.drop_index("ix_orders_user_created", table_name="orders")
    op.drop_index("ix_orders_status_expires", table_name="orders")
    op.drop_table("orders")
    op.drop_table("idempotency_requests")
    op.drop_table("confirmations")
    op.drop_table("action_proposals")


def install_guards():
    # Immutable snapshots cannot be overwritten even by accidental ORM updates.
    op.execute("""
    CREATE FUNCTION protect_checkout_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_TABLE_NAME = 'action_proposals' THEN
        IF (to_jsonb(OLD) - ARRAY['status','updated_at']) IS DISTINCT FROM
           (to_jsonb(NEW) - ARRAY['status','updated_at']) THEN
          RAISE EXCEPTION 'proposal snapshot is immutable' USING ERRCODE='23514';
        END IF;
      ELSIF TG_TABLE_NAME = 'confirmations' THEN
        IF (to_jsonb(OLD) - ARRAY['consumed_at','result_ref','updated_at']) IS DISTINCT FROM
           (to_jsonb(NEW) - ARRAY['consumed_at','result_ref','updated_at']) OR
           (OLD.consumed_at IS NOT NULL AND
             (OLD.consumed_at,OLD.result_ref) IS DISTINCT FROM
             (NEW.consumed_at,NEW.result_ref)) THEN
          RAISE EXCEPTION 'confirmation decision is immutable' USING ERRCODE='23514';
        END IF;
      ELSIF TG_TABLE_NAME = 'orders' THEN
        IF (to_jsonb(OLD) - ARRAY['status','version','updated_at']) IS DISTINCT FROM
           (to_jsonb(NEW) - ARRAY['status','version','updated_at']) THEN
          RAISE EXCEPTION 'order snapshot is immutable' USING ERRCODE='23514';
        END IF;
      ELSE
        RAISE EXCEPTION 'order items are immutable' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    """)
    for table in ("action_proposals", "confirmations", "orders", "order_items"):
        op.execute(
            f"CREATE TRIGGER immutable_snapshot BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_checkout_snapshot()"
        )
    # Key claims exist only inside a transaction; a commit must contain a completed receipt.
    op.execute("""
    CREATE FUNCTION require_completed_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF EXISTS (SELECT FROM idempotency_requests WHERE id=NEW.id AND
        (completed_at IS NULL OR result IS NULL OR jsonb_typeof(result) <> 'object')) THEN
        RAISE EXCEPTION 'incomplete idempotency receipt cannot commit' USING ERRCODE='23514';
      END IF;
      RETURN NULL;
    END $$;
    CREATE CONSTRAINT TRIGGER completed_receipt AFTER INSERT OR UPDATE ON idempotency_requests
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_completed_receipt();
    """)


def remove_guards():
    op.execute("DROP TRIGGER completed_receipt ON idempotency_requests")
    op.execute("DROP FUNCTION require_completed_receipt()")
    for table in ("action_proposals", "confirmations", "orders", "order_items"):
        op.execute(f"DROP TRIGGER immutable_snapshot ON {table}")
    op.execute("DROP FUNCTION protect_checkout_snapshot()")
