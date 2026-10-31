"""T06 additive aftersales, mock refunds and support handoff."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_order_owner_store", "orders", ["id", "user_id", "store_id"])
    op.create_unique_constraint(
        "uq_payment_order_store", "payments", ["id", "order_id", "store_id"]
    )
    replace_checks(True)
    op.create_table(
        "aftersales_cases",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("policy_version", sa.String(length=40), nullable=False),
        sa.Column("eligibility_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("restockable", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_reason", sa.String(length=1000), nullable=True),
        sa.Column("received_by", sa.Uuid(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('REQUESTED','APPROVED','RECEIVED','REFUNDED','REJECTED','CANCELLED')",
            name="ck_case_status",
        ),
        sa.CheckConstraint("restockable = false", name="ck_case_no_restock"),
        sa.CheckConstraint("version >= 1", name="ck_case_version"),
        sa.ForeignKeyConstraint(
            ["order_id", "user_id", "store_id"],
            ["orders.id", "orders.user_id", "orders.store_id"],
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id", "user_id", "store_id"],
            ["action_proposals.id", "action_proposals.actor_id", "action_proposals.store_id"],
        ),
        sa.ForeignKeyConstraint(
            ["received_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "order_id", "store_id", name="uq_case_order_store"),
        sa.UniqueConstraint("proposal_id", name="uq_case_proposal"),
    )
    op.create_index(
        "uq_case_active_order",
        "aftersales_cases",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('REJECTED','CANCELLED')"),
    )
    op.create_table(
        "refunds",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("action_id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint("status = 'SUCCEEDED'", name="ck_refund_status"),
        sa.CheckConstraint("amount_cents >= 0", name="ck_refund_amount"),
        sa.ForeignKeyConstraint(
            ["action_id"],
            ["action_proposals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["case_id", "order_id", "store_id"],
            ["aftersales_cases.id", "aftersales_cases.order_id", "aftersales_cases.store_id"],
        ),
        sa.ForeignKeyConstraint(
            ["payment_id", "order_id", "store_id"],
            ["payments.id", "payments.order_id", "payments.store_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action_id", name="uq_refund_action"),
        sa.UniqueConstraint("case_id", name="uq_refund_case"),
        sa.UniqueConstraint("payment_id", name="uq_refund_payment"),
    )
    op.create_table(
        "support_tickets",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("case_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_scope", sa.String(length=40), nullable=True),
        sa.Column("blocked_action_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("resolution", sa.String(length=30), nullable=True),
        sa.Column("resolution_summary", sa.String(length=1000), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            "(order_id IS NOT NULL AND conversation_scope IS NULL) OR "
            "(order_id IS NULL AND case_id IS NULL "
            "AND conversation_scope IS NOT NULL "
            "AND conversation_scope = 'after_sales_question')",
            name="ck_ticket_scope",
        ),
        sa.CheckConstraint(
            "resolution IS NULL OR resolution IN ('EXPLAINED','DECLINED','RETRY_ALLOWED')",
            name="ck_ticket_resolution",
        ),
        sa.CheckConstraint("status IN ('OPEN','IN_PROGRESS','RESOLVED')", name="ck_ticket_status"),
        sa.CheckConstraint("version >= 1", name="ck_ticket_version"),
        sa.ForeignKeyConstraint(
            ["assigned_to"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["case_id", "order_id", "store_id"],
            ["aftersales_cases.id", "aftersales_cases.order_id", "aftersales_cases.store_id"],
        ),
        sa.ForeignKeyConstraint(
            ["order_id", "user_id", "store_id"],
            ["orders.id", "orders.user_id", "orders.store_id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "store_id", "request_id", name="uq_ticket_request"),
    )
    op.create_index(
        "ix_ticket_order_status", "support_tickets", ["order_id", "status"], unique=False
    )
    op.alter_column("business_events", "action_id", existing_type=sa.UUID(), nullable=True)
    op.drop_constraint(
        op.f("business_events_aggregate_id_fkey"), "business_events", type_="foreignkey"
    )
    install_guards()


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT FROM aftersales_cases) OR EXISTS (SELECT FROM refunds) OR
         EXISTS (SELECT FROM support_tickets) OR
         EXISTS (SELECT FROM action_proposals WHERE action_type IN
                 ('RETURN_REQUEST','RETURN_CANCEL','MOCK_REFUND')) OR
         EXISTS (SELECT FROM business_events WHERE action_id IS NULL OR
                 aggregate_type <> 'order') OR
         EXISTS (SELECT FROM orders WHERE status='REFUNDED') THEN
        RAISE EXCEPTION 'T06 history prevents downgrade';
      END IF;
    END $$;""")
    op.drop_table("support_tickets")
    op.drop_table("refunds")
    op.drop_table("aftersales_cases")
    op.execute("DROP FUNCTION protect_aftersales_snapshot()")
    op.drop_constraint("uq_payment_order_store", "payments", type_="unique")
    op.drop_constraint("uq_order_owner_store", "orders", type_="unique")
    op.create_foreign_key(
        "business_events_aggregate_id_fkey", "business_events", "orders", ["aggregate_id"], ["id"]
    )
    op.alter_column("business_events", "action_id", existing_type=sa.UUID(), nullable=False)
    replace_checks(False)


def replace_checks(expanded):
    actions = "'CHECKOUT','MOCK_PAYMENT','CANCEL_ORDER'"
    operations = (
        "'prepare_checkout','execute_checkout','prepare_mock_payment',"
        "'prepare_cancel_order','execute_mock_payment','execute_cancel_order'"
    )
    statuses = "'PENDING_PAYMENT','PAID','CANCELLED','EXPIRED','SHIPPED','DELIVERED'"
    if expanded:
        actions += ",'RETURN_REQUEST','RETURN_CANCEL','MOCK_REFUND'"
        operations += (
            ",'prepare_return_request','execute_return_request','prepare_return_cancel',"
            "'execute_return_cancel','prepare_mock_refund','execute_mock_refund',"
            "'create_support_ticket'"
        )
        statuses += ",'REFUNDED'"
    for table, name, column, values in (
        ("orders", "ck_order_status", "status", statuses),
        ("action_proposals", "ck_proposal_action", "action_type", actions),
        ("idempotency_requests", "ck_idempotency_operation", "operation", operations),
    ):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"{column} IN ({values})")


def install_guards():
    op.execute("""
    CREATE FUNCTION protect_aftersales_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' OR TG_TABLE_NAME = 'refunds' THEN
        RAISE EXCEPTION 'aftersales history is immutable' USING ERRCODE='23514';
      ELSIF TG_TABLE_NAME = 'aftersales_cases' THEN
        IF (to_jsonb(OLD) - ARRAY['status','version','updated_at','reviewed_by','reviewed_at',
             'review_reason','received_by','received_at','refunded_at','cancelled_at'])
           IS DISTINCT FROM
           (to_jsonb(NEW) - ARRAY['status','version','updated_at','reviewed_by','reviewed_at',
             'review_reason','received_by','received_at','refunded_at','cancelled_at']) THEN
          RAISE EXCEPTION 'case snapshot is immutable' USING ERRCODE='23514';
        END IF;
      ELSE
        IF (to_jsonb(OLD) - ARRAY['status','version','updated_at','assigned_to','resolution',
            'resolution_summary','resolved_at']) IS DISTINCT FROM
           (to_jsonb(NEW) - ARRAY['status','version','updated_at','assigned_to','resolution',
            'resolution_summary','resolved_at']) THEN
          RAISE EXCEPTION 'ticket scope is immutable' USING ERRCODE='23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    """)
    for table in ("aftersales_cases", "refunds", "support_tickets"):
        op.execute(
            f"CREATE TRIGGER immutable_aftersales BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_aftersales_snapshot()"
        )
