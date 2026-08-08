"""Persistent Agent-generated workspaces."""

from .models import Surface, Workspace, WorkspaceConflictError, WorkspacePermissionError
from .service import ALLOWED_COMPONENT_TYPES, SurfaceService, WorkspaceService
from .store import WorkspaceStore, new_surface_id, new_workspace_id
from .tools import create_workspace_tools

__all__ = [
    "ALLOWED_COMPONENT_TYPES",
    "Surface",
    "SurfaceService",
    "Workspace",
    "WorkspaceConflictError",
    "WorkspacePermissionError",
    "WorkspaceService",
    "WorkspaceStore",
    "create_workspace_tools",
    "new_workspace_id",
    "new_surface_id",
]
