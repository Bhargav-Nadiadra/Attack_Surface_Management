"""initial schema

Revision ID: 5153c75e7b74
Revises:
Create Date: 2026-11-11 14:36:53.714972

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5153c75e7b74"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_role = postgresql.ENUM("ADMIN", "ANALYST", "VIEWER", name="user_role", create_type=False)
scan_status = postgresql.ENUM(
    "PENDING", "RUNNING", "COMPLETED", "FAILED", name="scan_status", create_type=False
)
record_type = postgresql.ENUM("A", "AAAA", "NS", "MX", name="record_type", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    user_role.create(bind, checkfirst=True)
    scan_status.create(bind, checkfirst=True)
    record_type.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "domains",
        sa.Column("name", sa.String(length=253), nullable=False),
        sa.Column("status", scan_status, nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_domains_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_domains")),
        sa.UniqueConstraint("name", name=op.f("uq_domains_name")),
    )
    op.create_table(
        "scans",
        sa.Column("domain_id", sa.Uuid(), nullable=False),
        sa.Column("status", scan_status, nullable=False),
        sa.Column("triggered_by", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["domain_id"],
            ["domains.id"],
            name=op.f("fk_scans_domain_id_domains"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["triggered_by"],
            ["users.id"],
            name=op.f("fk_scans_triggered_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scans")),
    )
    op.create_index(op.f("ix_scans_domain_id"), "scans", ["domain_id"], unique=False)
    op.create_index("ix_scans_status_created_at", "scans", ["status", "created_at"], unique=False)
    op.create_index(
        "uq_scans_one_active_per_domain",
        "scans",
        ["domain_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'RUNNING')"),
    )
    op.create_table(
        "assets",
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("domain_id", sa.Uuid(), nullable=False),
        sa.Column("type", record_type, nullable=False),
        sa.Column("value", sa.String(length=512), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["domain_id"],
            ["domains.id"],
            name=op.f("fk_assets_domain_id_domains"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scans.id"], name=op.f("fk_assets_scan_id_scans"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
        sa.UniqueConstraint("scan_id", "type", "value", name=op.f("uq_assets_scan_id_type_value")),
    )
    op.create_index("ix_assets_domain_id_type", "assets", ["domain_id", "type"], unique=False)
    op.create_index(op.f("ix_assets_scan_id"), "assets", ["scan_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_assets_scan_id"), table_name="assets")
    op.drop_index("ix_assets_domain_id_type", table_name="assets")
    op.drop_table("assets")
    op.drop_index("uq_scans_one_active_per_domain", table_name="scans")
    op.drop_index("ix_scans_status_created_at", table_name="scans")
    op.drop_index(op.f("ix_scans_domain_id"), table_name="scans")
    op.drop_table("scans")
    op.drop_table("domains")
    op.drop_table("users")

    bind = op.get_bind()
    record_type.drop(bind, checkfirst=True)
    scan_status.drop(bind, checkfirst=True)
    user_role.drop(bind, checkfirst=True)
