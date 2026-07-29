"""The one object routers see, whatever authenticated.

A browser session and a service API key resolve to the same shape. Routers must
never need to know which one they got — the moment a handler branches on
credential type, a permission rule has escaped into business logic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from nexus.auth.permissions import Permission, matches

PrincipalType = Literal["user", "service"]


@dataclass(slots=True, frozen=True)
class Principal:
    type: PrincipalType
    workspace_id: uuid.UUID
    permissions: frozenset[Permission]
    user_id: uuid.UUID | None = None
    api_key_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    roles: tuple[str, ...] = ()
    # Matched against document sensitivity during retrieval (KB-005).
    clearance: str = "internal"
    display_name: str = ""

    def has(self, required: Permission) -> bool:
        return any(matches(granted, required) for granted in self.permissions)

    def require(self, required: Permission) -> None:
        if not self.has(required):
            raise PermissionError(required)

    @property
    def audit_actor(self) -> tuple[str, uuid.UUID | None]:
        """(actor_type, actor_id) as written to audit_log."""
        if self.type == "service":
            return "api_key", self.api_key_id
        return "user", self.user_id


@dataclass(slots=True)
class DelegatedPrincipal:
    """An agent acting on behalf of a person.

    Tools execute with the delegating user's permissions, never the agent's own
    and never a service account's. An agent that can retrieve more than the user
    it acts for is a hole straight through every permission check in the
    platform, so the delegation is modelled explicitly rather than assumed.
    """

    principal: Principal
    agent_run_id: uuid.UUID
    agent_definition_id: uuid.UUID
    tool_grants: frozenset[str] = field(default_factory=frozenset)

    def may_use_tool(self, tool_slug: str) -> bool:
        return tool_slug in self.tool_grants

    def has(self, required: Permission) -> bool:
        return self.principal.has(required)
