"""Durable state storage for immutable Dudley theme generations."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1


class StateConflict(RuntimeError):
    """Raised when a state mutation cannot be performed safely."""


class StateStore:
    """Own the per-user state files for Dudley theme transactions."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.preferences_path = root / "preferences.json"
        self.baseline_path = root / "baseline"
        self.generations_path = root / "generations"
        self.transactions_path = root / "transactions"
        self.current_path = root / "current"
        self.previous_path = root / "previous"
        self.root.mkdir(parents=True, exist_ok=True)

        preferences = self._read_preferences()
        self.read_only = preferences.get("schema_version", SCHEMA_VERSION) > SCHEMA_VERSION
        if not self.preferences_path.exists():
            self._atomic_json(self.preferences_path, {"schema_version": SCHEMA_VERSION})
        if not self.read_only:
            for path in (
                self.baseline_path,
                self.generations_path,
                self.transactions_path,
            ):
                path.mkdir(exist_ok=True)

    def create_generation(self, generation_id: str, state: Mapping[str, Any]) -> Path:
        """Create one immutable generation state document."""
        self._require_writable()
        generation = self._validate_generation_id(generation_id)
        if generation.exists():
            raise StateConflict(f"generation already exists: {generation_id}")
        generation.mkdir()
        self._atomic_json(generation / "state.json", dict(state))
        self._fsync_directory(generation)
        self._fsync_directory(self.generations_path)
        return generation

    def commit_generation(self, generation_id: str) -> None:
        """Durably switch current and previous references to a generation."""
        self._require_writable()
        self._generation_path(generation_id)
        previous_id = self.recover_pointer()
        sequence = self._next_transaction_sequence()
        journal = self.transactions_path / f"{sequence:020d}-{generation_id}.json"
        record = {
            "generation_id": generation_id,
            "previous_generation_id": previous_id,
            "sequence": sequence,
            "state": "PREPARED",
        }
        self._atomic_json(journal, record)
        self._replace_pointer_pair(generation_id, previous_id)
        record["state"] = "COMMITTED"
        self._atomic_json(journal, record)

    def current_id(self) -> str | None:
        return self._reference_id(self.current_path)

    def previous_id(self) -> str | None:
        return self._reference_id(self.previous_path)

    def recover_pointer(self) -> str | None:
        """Repair references from the newest durable transaction intent."""
        current_id = self.current_id()
        if self.read_only or not self.transactions_path.is_dir():
            return current_id

        transaction = self._latest_transaction()
        if transaction is None:
            return current_id
        journal, record = transaction
        generation_id = record["generation_id"]
        previous_id = record["previous_generation_id"]
        self._replace_pointer_pair(generation_id, previous_id)
        if record["state"] == "PREPARED":
            record["state"] = "COMMITTED"
            self._atomic_json(journal, record)
        return generation_id

    def _read_preferences(self) -> dict[str, Any]:
        if not self.preferences_path.exists():
            return {}
        try:
            value = json.loads(self.preferences_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return value if isinstance(value, dict) else {}

    def _generation_path(self, generation_id: str) -> Path:
        candidate = self._validate_generation_id(generation_id)
        if not candidate.is_dir():
            raise StateConflict(f"unknown generation: {generation_id}")
        try:
            resolved = candidate.resolve(strict=True)
            generations = self.generations_path.resolve(strict=True)
        except OSError as error:
            raise StateConflict(f"unreadable generation: {generation_id}") from error
        if resolved.parent != generations:
            raise StateConflict(f"generation escapes store: {generation_id!r}")
        return candidate

    def _validate_generation_id(self, generation_id: str) -> Path:
        if not generation_id or Path(generation_id).name != generation_id:
            raise StateConflict(f"invalid generation id: {generation_id!r}")
        candidate = self.generations_path / generation_id
        try:
            candidate.relative_to(self.generations_path)
        except ValueError as error:
            raise StateConflict(f"generation escapes store: {generation_id!r}") from error
        return candidate

    def _reference_id(self, reference: Path) -> str | None:
        if not reference.is_symlink():
            return None
        try:
            target = reference.resolve(strict=True)
            target.relative_to(self.generations_path.resolve(strict=True))
        except (OSError, ValueError):
            return None
        if not target.is_dir() or target.parent != self.generations_path.resolve(strict=True):
            return None
        return target.name

    def _replace_reference(self, reference: Path, generation_id: str) -> None:
        self._generation_path(generation_id)
        temporary = self.root / f".{reference.name}.{next(tempfile._get_candidate_names())}"
        try:
            temporary.symlink_to(Path("generations") / generation_id)
            self._fsync_directory(self.root)
            os.replace(temporary, reference)
            self._fsync_directory(self.root)
        finally:
            if temporary.is_symlink():
                temporary.unlink()

    def _replace_pointer_pair(
        self, current_id: str, previous_id: str | None
    ) -> None:
        """Install a journal-authorized pointer pair and synchronize each step."""
        if previous_id is None:
            self._remove_reference(self.previous_path)
        else:
            self._replace_reference(self.previous_path, previous_id)
        self._replace_reference(self.current_path, current_id)

    def _next_transaction_sequence(self) -> int:
        transaction = self._latest_transaction()
        if transaction is None:
            return 1
        return transaction[1]["sequence"] + 1

    def _latest_transaction(self) -> tuple[Path, dict[str, Any]] | None:
        latest: tuple[Path, dict[str, Any]] | None = None
        for journal in self.transactions_path.glob("*.json"):
            try:
                record = json.loads(journal.read_text(encoding="utf-8"))
                generation_id = record["generation_id"]
                previous_id = record["previous_generation_id"]
                sequence = record["sequence"]
            except (json.JSONDecodeError, KeyError, OSError, TypeError):
                continue
            if (
                record.get("state") not in {"PREPARED", "COMMITTED"}
                or not isinstance(generation_id, str)
                or not isinstance(previous_id, str | type(None))
                or not isinstance(sequence, int)
            ):
                continue
            try:
                self._generation_path(generation_id)
                if previous_id is not None:
                    self._generation_path(previous_id)
            except StateConflict:
                continue
            if latest is None or sequence > latest[1]["sequence"]:
                latest = (journal, record)
        return latest

    def _remove_reference(self, reference: Path) -> None:
        if reference.exists() or reference.is_symlink():
            reference.unlink()
            self._fsync_directory(self.root)

    def _atomic_json(self, path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(value, output, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            self._fsync_directory(path.parent)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _require_writable(self) -> None:
        if self.read_only:
            raise StateConflict("state schema is newer than this engine supports")

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
