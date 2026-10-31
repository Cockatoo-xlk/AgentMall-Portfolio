"""T05 additive order lifecycle and unique successful mock payments."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def check(table, name, expression):
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, expression)


def upgrade():
    check(
        "orders",
        "ck_order_status",
        "status IN ('PENDING_PAYMENT','PAID','CANCELLED','EXPIRED','SHIPPED','DELIVERED')",
    )
    check(
        "action_proposals",
        "ck_proposal_action",
        "action_type IN ('CHECKOUT','MOCK_PAYMENT','CANCEL_ORDER')",
    )
    check(
        "idempotency_requests",
        "ck_idempotency_operation",
        "operation IN ('prepare_checkout','execute_checkout','prepare_mock_payment',"
        "'prepare_cancel_order','execute_mock_payment','execute_cancel_order')",
    )
    for name in ("paid_at", "shipped_at", "delivered_at"):
        op.add_column("orders", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("action_id", sa.Uuid(), sa.ForeignKey("action_proposals.id"), nullable=False),
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
        sa.ForeignKeyConstraint(["order_id", "store_id"], ["orders.id", "orders.store_id"]),
        sa.UniqueConstraint("order_id", name="uq_payment_order"),
        sa.UniqueConstraint("action_id", name="uq_payment_action"),
        sa.CheckConstraint("amount_cents >= 0", name="ck_payment_amount"),
        sa.CheckConstraint("status = 'SUCCEEDED'", name="ck_payment_status"),
        sa.CheckConstraint("provider = 'mock'", name="ck_payment_provider"),
    )
    # Preserve the original T02 immutable snapshot rules; allow only lifecycle timestamps.
    op.execute("""
    CREATE OR REPLACE FUNCTION protect_checkout_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_TABLE_NAME = 'action_proposals' THEN
        IF (to_jsonb(OLD) - ARRAY['status','updated_at']) IS DISTINCT FROM
           (to_jsonb(NEW) - ARRAY['status','updated_at']) THEN
          RAISE EXCEPTION 'proposal snapshot is immutable' USING ERRCODE='23514';
        END IF;
      ELSIF TG_TABLE_NAME = 'confirmations' THEN
        IF (to_jsonb(OLD) - ARRAY['consumed_at','result_ref','updated_at']) IS DISTINCT FROM
           (to_jsonb(NEW) - ARRAY['consumed_at','result_ref','updated_at']) OR
           (OLD.consumed_at IS NOT NULL AND (OLD.consumed_at,OLD.result_ref) IS DISTINCT FROM
            (NEW.consumed_at,NEW.result_ref)) THEN
          RAISE EXCEPTION 'confirmation decision is immutable' USING ERRCODE='23514';
        END IF;
      ELSIF TG_TABLE_NAME = 'orders' THEN
        IF (to_jsonb(OLD) - ARRAY['status','version','updated_at',
            'paid_at','shipped_at','delivered_at']) IS DISTINCT FROM
           (to_jsonb(NEW) - ARRAY['status','version','updated_at',
            'paid_at','shipped_at','delivered_at']) OR
           (OLD.paid_at IS NOT NULL AND OLD.paid_at IS DISTINCT FROM NEW.paid_at) OR
           (OLD.shipped_at IS NOT NULL AND OLD.shipped_at IS DISTINCT FROM NEW.shipped_at) OR
           (OLD.delivered_at IS NOT NULL AND
            OLD.delivered_at IS DISTINCT FROM NEW.delivered_at) THEN
          RAISE EXCEPTION 'order snapshot is immutable' USING ERRCODE='23514';
        END IF;
      ELSE
        RAISE EXCEPTION 'order items are immutable' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    """)


def downgrade():
    # Refuse lossy downgrade after lifecycle use, rather than deleting business history.
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT FROM payments) OR
         EXISTS (SELECT FROM orders WHERE status <> 'PENDING_PAYMENT')
         OR EXISTS (SELECT FROM action_proposals WHERE action_type <> 'CHECKOUT') THEN
        RAISE EXCEPTION 'T05 business data prevents downgrade';
      END IF;
    END $$;""")
    op.drop_table("payments")
    for name in ("delivered_at", "shipped_at", "paid_at"):
        op.drop_column("orders", name)
    check("orders", "ck_order_status", "status = 'PENDING_PAYMENT'")
    check("action_proposals", "ck_proposal_action", "action_type = 'CHECKOUT'")
    check(
        "idempotency_requests",
        "ck_idempotency_operation",
        "operation IN ('prepare_checkout','execute_checkout')",
    )
    # Restore the exact preceding trigger functions from the preceding migration.
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    spec = spec_from_file_location(
        "agentmall_t02_migration", Path(__file__).with_name("0002_actions_orders.py")
    )
    previous = module_from_spec(spec)
    spec.loader.exec_module(previous)
    previous.remove_guards()
    previous.install_guards()
