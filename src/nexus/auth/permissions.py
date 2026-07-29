"""Permissions and the system roles that bundle them.

Permissions are namespaced strings: `<module>.<resource>.<action>`. They live in
`roles.permissions` as JSONB so a role can be extended without a migration,
which matters because new modules keep arriving through the task list.

Wildcards are supported at segment boundaries: `gateway.*` grants everything
under gateway, `*` grants everything. Matching is explicit rather than clever —
see `Principal.has`.
"""

from __future__ import annotations

from typing import Final

Permission = str

PERMISSIONS: Final[dict[str, str]] = {
    # gateway
    "gateway.chat.write": "Send requests through the gateway",
    "gateway.request.read": "View request history and metadata",
    "gateway.content.read": "View prompt and completion content",
    "gateway.route.read": "View routing policies",
    "gateway.route.write": "Create and edit routing policies",
    # knowledge
    "knowledge.collection.read": "View collections and their documents",
    "knowledge.collection.write": "Create collections and upload documents",
    "knowledge.collection.grant": "Grant others access to a collection",
    "knowledge.ask.write": "Ask questions against a collection",
    # agents
    "agents.agent.read": "View agents and their run history",
    "agents.agent.write": "Create and edit agents",
    "agents.tool.grant": "Grant a tool to an agent",
    "agents.approval.decide": "Approve or reject a paused agent action",
    # evaluation
    "eval.dataset.read": "View evaluation datasets",
    "eval.dataset.write": "Create and edit evaluation datasets",
    "eval.run.write": "Start evaluation runs",
    "prompt.template.write": "Create and edit prompts, and move labels",
    # observability
    "obs.metrics.read": "View dashboards and metrics",
    "obs.trace.read": "View traces",
    "obs.cost.read": "View cost breakdowns",
    # governance
    "governance.policy.read": "View policies and violations",
    "governance.policy.write": "Create and edit policies",
    "governance.audit.read": "Read and export the audit log",
    "governance.pii.reveal": "Reveal redacted values via the token vault",
    # administration
    "admin.workspace.write": "Edit workspace settings and budgets",
    "admin.member.write": "Add, remove and re-role members",
    "admin.apikey.write": "Create and revoke API keys",
    "admin.provider.write": "Configure providers, models and pricing",
}

SYSTEM_ROLES: Final[dict[str, list[Permission]]] = {
    # Everything, including the ability to hand out everything.
    "owner": ["*"],
    "admin": [
        "gateway.*",
        "knowledge.*",
        "agents.*",
        "eval.*",
        "prompt.*",
        "obs.*",
        "governance.policy.read",
        "governance.audit.read",
        "admin.*",
    ],
    "engineer": [
        "gateway.chat.write",
        "gateway.request.read",
        "gateway.route.read",
        "knowledge.collection.read",
        "knowledge.collection.write",
        "knowledge.ask.write",
        "agents.agent.read",
        "agents.agent.write",
        "eval.*",
        "prompt.template.write",
        "obs.metrics.read",
        "obs.trace.read",
    ],
    "analyst": [
        "gateway.chat.write",
        "gateway.request.read",
        "knowledge.collection.read",
        "knowledge.ask.write",
        "eval.dataset.read",
        "obs.metrics.read",
        "obs.cost.read",
    ],
    "viewer": [
        "gateway.request.read",
        "knowledge.collection.read",
        "obs.metrics.read",
    ],
}

# What a service API key gets by default. Deliberately narrow: an application
# calling the gateway has no business reading the audit log.
DEFAULT_SERVICE_SCOPES: Final[list[Permission]] = [
    "gateway.chat.write",
    "knowledge.ask.write",
]


def matches(granted: Permission, required: Permission) -> bool:
    """Does a granted permission satisfy a required one?

    `*` matches everything. `gateway.*` matches `gateway.chat.write`. A trailing
    wildcard only matches at a segment boundary, so `gateway.*` does not match a
    hypothetical `gateways.something` — a nice property to get for free from
    comparing on the dot.
    """
    if granted == "*" or granted == required:
        return True
    if granted.endswith(".*"):
        return required.startswith(granted[:-1])
    return False
