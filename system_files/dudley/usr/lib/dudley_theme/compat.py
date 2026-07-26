"""One-release compatibility aliases for the experimental theme command."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompatibilityCommand:
    argv: tuple[str, ...]
    warning: str | None = None


def translate(argv: list[str]) -> CompatibilityCommand:
    if not argv:
        return CompatibilityCommand(())
    command, *arguments = argv
    aliases = {
        "apply": (
            "set",
            "dudley-theme apply is deprecated; use dudley-theme set",
        ),
        "current": (
            "status",
            "dudley-theme current is deprecated; use dudley-theme status",
        ),
        "reset": (
            "off",
            "dudley-theme reset is deprecated; use dudley-theme off",
        ),
    }
    replacement = aliases.get(command)
    if replacement is None:
        return CompatibilityCommand(tuple(argv))
    return CompatibilityCommand(
        (replacement[0], *arguments),
        replacement[1],
    )
