"""Exact file, symlink, and owned-line capture and restoration."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .base import AdapterResult


@dataclass(frozen=True)
class FileResource:
    path: Path
    state: str
    data: bytes | None = None
    mode: int | None = None
    link_target: str | None = None

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        digest.update(self.state.encode("ascii"))
        digest.update(b"\0")
        if self.state == "file":
            digest.update(str(self.mode).encode("ascii"))
        digest.update(b"\0")
        digest.update(self.data or b"")
        digest.update(b"\0")
        digest.update(
            (self.link_target or "").encode("utf-8", errors="surrogateescape")
        )
        return digest.hexdigest()


@dataclass(frozen=True)
class LineResource:
    path: Path
    line: bytes
    before: FileResource
    existed: bool


def capture_file(path: Path) -> FileResource:
    """Capture a path without following symlinks."""
    path = Path(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return FileResource(path=path, state="absent")
    mode = stat.S_IMODE(metadata.st_mode)
    if stat.S_ISLNK(metadata.st_mode):
        return FileResource(
            path=path,
            state="symlink",
            mode=mode,
            link_target=os.readlink(path),
        )
    if stat.S_ISREG(metadata.st_mode):
        return FileResource(
            path=path,
            state="file",
            data=path.read_bytes(),
            mode=mode,
        )
    raise ValueError(f"unsupported resource type: {path}")


def write_managed_file(path: Path, data: bytes, *, mode: int = 0o644) -> FileResource:
    """Atomically install managed bytes and return the applied fingerprint."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
    return capture_file(path)


def write_managed_link(path: Path, target: str) -> FileResource:
    """Atomically install a managed symbolic link."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{next(tempfile._get_candidate_names())}"
    try:
        temporary.symlink_to(target)
        os.replace(temporary, path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
    return capture_file(path)


def expected_managed_link(path: Path, target: str) -> FileResource:
    """Describe the symlink fingerprint produced by ``write_managed_link``."""
    return FileResource(path=Path(path), state="symlink", link_target=target)


def restore_file(
    record: FileResource, *, expected: FileResource | bytes
) -> AdapterResult:
    """Restore captured state only while the managed fingerprint still matches."""
    current = capture_file(record.path)
    if current.fingerprint == record.fingerprint:
        return AdapterResult("unchanged")
    if isinstance(expected, bytes):
        matches_expected = current.state == "file" and current.data == expected
    else:
        matches_expected = current.fingerprint == expected.fingerprint
    if not matches_expected:
        return AdapterResult("conflicted", (str(record.path),))
    _install_resource(record)
    return AdapterResult("restored")


def capture_line(path: Path, line: bytes) -> LineResource:
    """Capture a file and whether an exact logical line already exists."""
    before = capture_file(path)
    if before.state not in {"absent", "file"}:
        raise ValueError(f"line resource must be a regular file or absent: {path}")
    lines = (before.data or b"").splitlines()
    return LineResource(
        path=Path(path), line=line, before=before, existed=line in lines
    )


def write_managed_line(record: LineResource) -> FileResource:
    """Add one exact line, retaining ownership only when Dudley introduced it."""
    if record.existed:
        return capture_file(record.path)
    current = capture_file(record.path)
    if current.fingerprint != record.before.fingerprint:
        raise RuntimeError(f"resource changed after capture: {record.path}")
    data = current.data or b""
    if data and not data.endswith(b"\n"):
        data += b"\n"
    data += record.line + b"\n"
    mode = current.mode if current.mode is not None else 0o644
    return write_managed_file(record.path, data, mode=mode)


def expected_managed_line(record: LineResource) -> FileResource:
    """Describe the regular-file fingerprint produced by ``write_managed_line``."""
    if record.existed:
        return record.before
    data = record.before.data or b""
    if data and not data.endswith(b"\n"):
        data += b"\n"
    data += record.line + b"\n"
    return FileResource(
        path=record.path,
        state="file",
        data=data,
        mode=record.before.mode if record.before.mode is not None else 0o644,
    )


def restore_line(record: LineResource, *, expected: FileResource) -> AdapterResult:
    """Restore only a line introduced by Dudley."""
    if record.existed:
        return AdapterResult("unchanged")
    return restore_file(record.before, expected=expected)


def _install_resource(record: FileResource) -> None:
    if record.state == "absent":
        if record.path.exists() or record.path.is_symlink():
            record.path.unlink()
        return
    if record.state == "file":
        write_managed_file(
            record.path,
            record.data or b"",
            mode=record.mode if record.mode is not None else 0o644,
        )
        return
    if record.state == "symlink":
        if record.link_target is None:
            raise ValueError(f"captured symlink has no target: {record.path}")
        write_managed_link(record.path, record.link_target)
        return
    raise ValueError(f"unsupported captured state: {record.state}")
