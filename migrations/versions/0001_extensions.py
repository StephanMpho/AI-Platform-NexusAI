"""Postgres extensions — INFRA-001, migration 000.

vector    embeddings and similarity search
pgcrypto  gen_random_uuid() and column encryption
pg_trgm   trigram matching for the keyword half of hybrid retrieval

Revision ID: 0001_extensions
Revises:
"""
from __future__ import annotations

from alembic import op

revision: str = "0001_extensions"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    # Deliberately not dropped: other schemas in the same database may rely on them.
    pass
