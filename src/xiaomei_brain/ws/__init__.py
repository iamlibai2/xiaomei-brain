"""WebSocket service for xiaomei-brain."""

from .server import create_app, app

__all__ = ["create_app", "app"]
