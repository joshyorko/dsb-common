"""Shared contracts for reversible theme adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from dudley_theme.model import ResourceRecord


@dataclass(frozen=True)
class ThemeContext:
    """Paths and rendered values available to one adapter transaction."""

    home: Path
    theme_root: Path | None = None
    values: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterStatus:
    status: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterResult:
    status: str
    details: tuple[str, ...] = ()


class Adapter(ABC):
    """Transactional boundary implemented by every curated surface adapter."""

    @abstractmethod
    def capture(self, context: ThemeContext) -> list[ResourceRecord]:
        raise NotImplementedError

    @abstractmethod
    def apply(
        self, context: ThemeContext, records: list[ResourceRecord]
    ) -> AdapterResult:
        raise NotImplementedError

    @abstractmethod
    def verify(self, context: ThemeContext) -> AdapterStatus:
        raise NotImplementedError

    @abstractmethod
    def restore(
        self, context: ThemeContext, records: list[ResourceRecord]
    ) -> AdapterResult:
        raise NotImplementedError
