"""Conflict-aware resource adapters for Dudley-managed themes."""

from .base import Adapter, AdapterResult, AdapterStatus, ThemeContext
from .files import FileResource, LineResource
from .gsettings import GSettingsAdapter, SettingResource

__all__ = [
    "Adapter",
    "AdapterResult",
    "AdapterStatus",
    "FileResource",
    "GSettingsAdapter",
    "LineResource",
    "SettingResource",
    "ThemeContext",
]
