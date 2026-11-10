"""Immutable bundle variants extend existing thread-owned candidate sets."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "agent_candidate_sets",
        sa.Column("kind", sa.String(16), nullable=False, server_default="product"),
    )
    op.add_column(
        "agent_candidate_sets", sa.Column("details", JSONB(), nullable=False, server_default="{}")
    )
    op.create_check_constraint(
        "ck_candidate_kind", "agent_candidate_sets", "kind IN ('product','bundle')"
    )
    op.create_check_constraint(
        "ck_candidate_details", "agent_candidate_sets", "jsonb_typeof(details)='object'"
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM agent_candidate_sets WHERE kind='bundle')")
    ):
        raise RuntimeError(
            "Bundle snapshots exist; explicit data migration required before downgrade"
        )
    op.drop_constraint("ck_candidate_details", "agent_candidate_sets", type_="check")
    op.drop_constraint("ck_candidate_kind", "agent_candidate_sets", type_="check")
    op.drop_column("agent_candidate_sets", "details")
    op.drop_column("agent_candidate_sets", "kind")
