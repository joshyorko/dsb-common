"""Deterministic palette-token rendering for validated Dudley themes."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .catalog import ThemeManifest


_TOKEN_PATTERN = re.compile(r"{{\s*([A-Za-z][A-Za-z0-9_.-]*)\s*}}")


class ThemeRenderError(ValueError):
    """Raised when a validated theme cannot be rendered safely."""


@dataclass(frozen=True)
class RenderResult:
    destination: Path
    hashes: dict[str, str]


def render_theme(theme: ThemeManifest, destination: Path) -> RenderResult:
    """Render every declared output atomically after all tokens resolve."""
    destination = Path(destination)
    rendered: dict[str, bytes] = {}
    for output in theme.render_outputs:
        source_path = theme.root / output.source
        source_bytes = source_path.read_bytes()
        provenance = theme.provenance[output.source]
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        if source_hash != provenance.shipped_sha256:
            raise ThemeRenderError(
                f"render source changed after validation: {output.source}"
            )
        try:
            source = source_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ThemeRenderError(
                f"render source is not UTF-8 text: {output.source}"
            ) from error
        rendered[output.path] = _render_text(
            source,
            theme=theme,
            source=output.source,
        ).encode("utf-8")

    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise ThemeRenderError(
                f"render destination must be a real directory: {destination}"
            )
    else:
        destination.mkdir(parents=True)

    hashes: dict[str, str] = {}
    for relative_path, data in sorted(rendered.items()):
        output_path = destination / relative_path
        _reject_symlink_parents(destination, output_path)
        if output_path.is_symlink():
            raise ThemeRenderError(
                f"render output cannot replace a symlink: {relative_path}"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(output_path, data)
        hashes[relative_path] = hashlib.sha256(data).hexdigest()
    return RenderResult(destination=destination, hashes=hashes)


def _render_text(source_text: str, *, theme: ThemeManifest, source: str) -> str:
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        value = theme.colors.get(token)
        if value is None:
            missing.add(token)
            return match.group(0)
        return value

    rendered = _TOKEN_PATTERN.sub(replace, source_text)
    if missing:
        raise ThemeRenderError(
            f"unresolved template tokens in {source}: " + ", ".join(sorted(missing))
        )
    if "{{" in rendered or "}}" in rendered:
        raise ThemeRenderError(f"unresolved template placeholder in {source}")
    return rendered


def _reject_symlink_parents(destination: Path, output: Path) -> None:
    relative = output.relative_to(destination)
    current = destination
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ThemeRenderError(
                f"render output parent cannot be a symlink: {relative}"
            )


def _atomic_write(path: Path, data: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
