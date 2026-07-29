"""Demo data — SHIP-001 in miniature.

Enough to make the API usable on a fresh clone: one workspace, one user, the
mock provider and two models. Grow this as the schema grows.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from nexus.api.deps import DEV_USER, DEV_WORKSPACE
from nexus.db.models import Model, Provider, User, Workspace, WorkspaceMembership
from nexus.db.session import sessionmaker


async def seed() -> None:
    async with sessionmaker() as session:
        existing = await session.scalar(select(Workspace).where(Workspace.id == DEV_WORKSPACE))
        if existing:
            print("already seeded")
            return

        workspace = Workspace(
            id=DEV_WORKSPACE,
            slug="demo",
            name="Demo Workspace",
            description="Local development workspace",
            logging_mode="full",
            monthly_budget_usd=50,
        )
        user = User(
            id=DEV_USER,
            email="dev@localhost",
            display_name="Local Developer",
            default_workspace_id=DEV_WORKSPACE,
            clearance="restricted",
        )
        membership = WorkspaceMembership(
            workspace_id=DEV_WORKSPACE, user_id=DEV_USER, joined_at=datetime.now(UTC)
        )

        provider_id = uuid.uuid4()
        provider = Provider(
            id=provider_id,
            slug="mock",
            name="Mock Provider",
            adapter_class="nexus.providers.mock.MockProvider",
            is_external=False,
            region="local",
        )
        models = [
            Model(
                slug="mock-fast",
                provider_id=provider_id,
                provider_model_name="mock-fast",
                tier="cheap",
                context_window=32_000,
                max_output_tokens=4_096,
            ),
            Model(
                slug="mock-strong",
                provider_id=provider_id,
                provider_model_name="mock-strong",
                tier="strong",
                context_window=200_000,
                max_output_tokens=8_192,
                supports_tools=True,
            ),
        ]

        session.add_all([workspace, user, membership, provider, *models])
        await session.commit()
        print("seeded: 1 workspace, 1 user, mock provider, 2 models")


if __name__ == "__main__":
    asyncio.run(seed())
