"""SQLAlchemy models.

Add a module per schema domain as you work through INFRA-002 and INFRA-003, and
import it here so Alembic autogenerate can see it.
"""

from nexus.db.models.access import ApiKey, Role, RoleAssignment, UserSession
from nexus.db.models.gateway import GatewayRequest, Model, Provider
from nexus.db.models.identity import User, Workspace, WorkspaceMembership

__all__ = [
    "ApiKey",
    "GatewayRequest",
    "Model",
    "Provider",
    "Role",
    "RoleAssignment",
    "User",
    "UserSession",
    "Workspace",
    "WorkspaceMembership",
]
