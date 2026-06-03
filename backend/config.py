"""
config.py — top-level shim for tool modules.

Nan's tool modules use the import style:
    from config import settings

Since pyproject.toml puts `backend/` on sys.path, this file makes that
import resolve correctly to the canonical app.core.config.Settings instance.

Usage in any tool file:
    from config import settings
    path = settings.model_data_path
"""

from app.core.config import settings  # noqa: F401

__all__ = ["settings"]
