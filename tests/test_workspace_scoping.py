"""Workspace isolation, checked mechanically rather than remembered.

The reflection test is the point: it fails when someone adds a repository method
that queries without the workspace filter, which is a mistake that is otherwise
invisible until it leaks data across tenants.
"""

from __future__ import annotations

import inspect
import uuid

import pytest

from nexus.db.repository import WorkspaceScopedRepository


def _all_repositories() -> list[type]:
    subclasses: list[type] = []
    stack = list(WorkspaceScopedRepository.__subclasses__())
    while stack:
        cls = stack.pop()
        subclasses.append(cls)
        stack.extend(cls.__subclasses__())
    return subclasses


def test_repository_cannot_be_built_without_a_workspace() -> None:
    signature = inspect.signature(WorkspaceScopedRepository.__init__)
    assert "workspace_id" in signature.parameters
    with pytest.raises(TypeError):
        WorkspaceScopedRepository(db=None)  # type: ignore[call-arg,arg-type]


def test_every_repository_query_goes_through_the_scoped_builder() -> None:
    """Any public method that builds a query must start from `scoped()`.

    Reflection over source rather than behaviour is a blunt check, but it fails
    at the moment the mistake is written instead of the moment it is exploited.
    """
    offenders: list[str] = []
    for repo in _all_repositories():
        for name, method in inspect.getmembers(repo, inspect.isfunction):
            if name.startswith("_") or method.__qualname__.startswith("WorkspaceScoped"):
                continue
            try:
                source = inspect.getsource(method)
            except OSError:  # pragma: no cover
                continue
            if "select(" in source and "self.scoped()" not in source:
                offenders.append(f"{repo.__name__}.{name}")

    assert not offenders, (
        "these repository methods build a query without the workspace filter: "
        + ", ".join(offenders)
    )


def test_scoped_select_includes_the_workspace_predicate() -> None:
    from nexus.db.models.gateway import GatewayRequest

    class GatewayRequestRepository(WorkspaceScopedRepository[GatewayRequest]):
        model = GatewayRequest

    workspace_id = uuid.uuid4()
    repo = GatewayRequestRepository(db=None, workspace_id=workspace_id)  # type: ignore[arg-type]
    statement = str(repo.scoped())
    assert "workspace_id" in statement
    assert "WHERE" in statement
