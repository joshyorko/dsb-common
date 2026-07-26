"""Immutable records used by the Dudley theme transaction engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ThemeState:
    schema_version: int
    state: str
    theme_id: str | None = None


@dataclass(frozen=True)
class ResourceRecord:
    adapter: str
    resource: str
    before: Any
    applied: Any
    fingerprint: str | None = None


@dataclass(frozen=True)
class TransactionRecord:
    transaction_id: str
    generation_id: str
    state: str
    previous_generation_id: str | None = None
