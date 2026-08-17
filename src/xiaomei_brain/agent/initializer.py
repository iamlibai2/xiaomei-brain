"""Canonical, repeatable initialization for one Agent's durable filesystem.

Agent creation owns stable files and directory boundaries only.  Database
schemas remain owned by their stores and are migrated when those services are
initialized during startup.  This keeps Agent creation independent from every
future table addition while still making a newly created Agent structurally
complete before its first run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from xiaomei_brain.execution.workspace_layout import AgentWorkspaceLayout


@dataclass(frozen=True)
class AgentInitializationResult:
    root: Path
    memory_db: Path
    workspace: AgentWorkspaceLayout


class AgentInitializer:
    """Ensure the current on-disk contract for an Agent.

    The operation is intentionally idempotent.  It can run when an Agent is
    created and again before every first build after an application upgrade.
    Existing files and user data are never replaced.
    """

    _DIRECTORIES = (
        "consciousness",
        "contacts",
        "contacts/faces",
        "contacts/voices",
        "debug",
        "integrations",
        "logs",
        "memory",
        "people/biometrics",
        "people/biometrics/faces",
        "people/biometrics/voices",
        "schedule",
        "secrets",
        "sessions",
        "skills",
    )

    @classmethod
    def ensure(cls, agent_root: str | Path) -> AgentInitializationResult:
        root = Path(agent_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        for relative in cls._DIRECTORIES:
            (root / relative).mkdir(parents=True, exist_ok=True)

        # Legacy IdentityManager remains a compatibility reader while Person
        # and identity bindings live in brain.db.  A new Agent must start with
        # no invented people; verified identities are added by the real
        # account/person flow later.
        legacy_identities = root / "contacts" / "identities.yaml"
        if not legacy_identities.exists():
            legacy_identities.write_text(
                "# Compatibility identity aliases; verified people are stored in brain.db.\n"
                "people: []\n",
                encoding="utf-8",
            )

        workspace = AgentWorkspaceLayout.create(root)
        return AgentInitializationResult(
            root=root,
            memory_db=root / "memory" / "brain.db",
            workspace=workspace,
        )
