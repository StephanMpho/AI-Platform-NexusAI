"""Identity and access — INFRA-002 migration 001, AUTH-001, AUTH-002.

Creates domain 1 of the schema specification: workspaces, users, memberships,
roles, role assignments, API keys and sessions. Seeds the five system roles and
a default workspace so a fresh database is immediately usable.

Revision ID: 0002_identity_access
Revises: 0001_extensions
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_identity_access"
down_revision: str | None = "0001_extensions"
branch_labels = None
depends_on = None

SYSTEM_ROLES = {
    "owner": ["*"],
    "admin": [
        "gateway.*", "knowledge.*", "agents.*", "eval.*", "prompt.*", "obs.*",
        "governance.policy.read", "governance.audit.read", "admin.*",
    ],
    "engineer": [
        "gateway.chat.write", "gateway.request.read", "gateway.route.read",
        "knowledge.collection.read", "knowledge.collection.write", "knowledge.ask.write",
        "agents.agent.read", "agents.agent.write", "eval.*", "prompt.template.write",
        "obs.metrics.read", "obs.trace.read",
    ],
    "analyst": [
        "gateway.chat.write", "gateway.request.read", "knowledge.collection.read",
        "knowledge.ask.write", "eval.dataset.read", "obs.metrics.read", "obs.cost.read",
    ],
    "viewer": ["gateway.request.read", "knowledge.collection.read", "obs.metrics.read"],
}


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("slug", sa.String(60), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("logging_mode", sa.String(20), nullable=False, server_default="redacted"),
        sa.Column("monthly_budget_usd", sa.Numeric(12, 2)),
        sa.Column("data_residency", sa.String(20)),
        sa.Column("allow_external_providers", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_workspaces"),
        sa.UniqueConstraint("slug", name="uq_workspaces_slug"),
        sa.CheckConstraint(
            "logging_mode IN ('full','redacted','metadata_only')",
            name="ck_workspaces_logging_mode",
        ),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("external_subject", sa.String(255)),
        sa.Column("issuer", sa.String(255)),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("avatar_url", sa.String(500)),
        sa.Column("default_workspace_id", postgresql.UUID(as_uuid=True)),
        sa.Column("clearance", sa.String(20), nullable=False, server_default="internal"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("issuer", "external_subject", name="uq_users_subject"),
        sa.ForeignKeyConstraint(["default_workspace_id"], ["workspaces.id"], name="fk_users_default_workspace_id_workspaces"),
        sa.CheckConstraint(
            "clearance IN ('public','internal','confidential','restricted')",
            name="ck_users_clearance",
        ),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "workspace_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("joined_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_workspace_memberships"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE", name="fk_wm_workspace"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_wm_user"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_memberships_membership"),
    )

    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True)),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("permissions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE", name="fk_roles_workspace"),
    )
    # NULLS NOT DISTINCT so two system roles cannot share a name; without it,
    # Postgres treats every NULL workspace_id as unique and the seed can double.
    op.execute(
        "CREATE UNIQUE INDEX uq_roles_role_name ON roles (workspace_id, name) NULLS NOT DISTINCT"
    )

    op.create_table(
        "role_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True)),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_role_assignments"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE", name="fk_ra_workspace"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_ra_user"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_ra_role"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], name="fk_ra_granted_by"),
        sa.UniqueConstraint("workspace_id", "user_id", "role_id", name="uq_role_assignments_role_assignment"),
    )
    op.create_index(
        "ix_role_assignments_expiry", "role_assignments", ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("environment", sa.String(10), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String())),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_used_ip", postgresql.INET()),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("revoked_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE", name="fk_ak_workspace"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_ak_created_by"),
        sa.ForeignKeyConstraint(["revoked_by"], ["users.id"], name="fk_ak_revoked_by"),
        sa.CheckConstraint("environment IN ('live','test')", name="ck_api_keys_environment"),
    )
    op.create_index("ix_api_keys_revoked_at", "api_keys", ["revoked_at"])

    op.create_table(
        "user_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True)),
        sa.Column("ip_address", postgresql.INET()),
        sa.Column("user_agent", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("revoke_reason", sa.String(50)),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_active_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_user_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_us_user"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_us_workspace"),
        sa.CheckConstraint(
            "status IN ('active','expired','revoked','logged_out')",
            name="ck_user_sessions_status",
        ),
    )
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])

    # ---- seeds -------------------------------------------------------------
    op.execute(
        """
        INSERT INTO workspaces (slug, name, description, logging_mode)
        VALUES ('default', 'Default Workspace', 'Created by migration 0002', 'redacted')
        ON CONFLICT (slug) DO NOTHING
        """
    )
    for name, permissions in SYSTEM_ROLES.items():
        op.execute(
            sa.text(
                "INSERT INTO roles (workspace_id, name, description, permissions, is_system) "
                "VALUES (NULL, :name, :description, CAST(:permissions AS jsonb), true)"
            ).bindparams(
                name=name,
                description=f"System role: {name}",
                permissions=json.dumps(permissions),
            )
        )


def downgrade() -> None:
    for table in (
        "user_sessions", "api_keys", "role_assignments", "roles",
        "workspace_memberships", "users", "workspaces",
    ):
        op.drop_table(table)
