"""Serialized, reversible transactions for per-user Dudley themes."""

from __future__ import annotations

import base64
import fcntl
import json
import os
import shutil
import stat
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from .adapters.apps import (
    BtopAdapter,
    GhosttyAdapter,
    JsoncResource,
    KittyAdapter,
    NeovimAdapter,
    VSCodeAdapter,
)
from .adapters.base import Adapter, ThemeContext
from .adapters.files import FileResource, LineResource
from .adapters.gnome import (
    INTERFACE,
    USER_THEME,
    ExtensionResource,
    GnomeAdapter,
)
from .adapters.gsettings import SettingResource
from .catalog import ThemeManifest, discover_themes
from .model import ResourceRecord
from .render import RenderResult, render_theme
from .state import SCHEMA_VERSION, StateConflict, StateStore


EXIT_SUCCESS = 0
EXIT_USAGE = 2
EXIT_CONFLICT = 3
EXIT_ADAPTER_FAILURE = 4


@dataclass(frozen=True)
class Result:
    status: str
    message: str
    exit_code: int = EXIT_SUCCESS
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class StatusReport:
    state: str
    theme_id: str | None
    generation_id: str | None
    surfaces: Mapping[str, str]
    read_only: bool = False
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "theme_id": self.theme_id,
            "generation_id": self.generation_id,
            "surfaces": dict(self.surfaces),
            "read_only": self.read_only,
            "message": self.message,
        }


AdapterFactory = Callable[[ThemeManifest, ThemeContext], Adapter]
Renderer = Callable[[ThemeManifest, Path], RenderResult]
FaultHook = Callable[[str, str | None], None]


class ThemeEngine:
    """Coordinate catalog, adapters, journals, and immutable generations."""

    def __init__(
        self,
        *,
        state_root: Path,
        runtime_dir: Path,
        home: Path,
        catalog_root: Path | None = None,
        themes: Mapping[str, ThemeManifest] | None = None,
        adapter_factories: Mapping[str, AdapterFactory | Adapter] | None = None,
        renderer: Renderer = render_theme,
        default_theme: str = "wellness-floor",
        fault_hook: FaultHook | None = None,
    ) -> None:
        self.home = Path(home)
        self.state_root = Path(state_root)
        self.runtime_dir = Path(runtime_dir)
        self.store = StateStore(self.state_root)
        self.themes = dict(
            themes
            if themes is not None
            else discover_themes(Path(catalog_root or "/usr/share/dudley/themes"))
        )
        self.adapter_factories = dict(
            adapter_factories or self._default_adapter_factories()
        )
        self.renderer = renderer
        self.default_theme = default_theme
        self.fault_hook = fault_hook or (lambda _phase, _adapter: None)
        self.lock_path = self.runtime_dir / "dudley-theme.lock"
        self.engine_journal_prefix = "engine-"

    def on(self) -> Result:
        return self._mutate(
            lambda: self._set_locked(
                str(self._preferences().get("last_theme") or self.default_theme),
                reason="on",
            )
        )

    def set(self, theme_id: str) -> Result:
        return self._mutate(lambda: self._set_locked(theme_id, reason="set"))

    def undo(self) -> Result:
        def operation() -> Result:
            previous_id = self.store.previous_id()
            if previous_id is None:
                return Result(
                    "conflicted",
                    "no previous committed theme generation",
                    EXIT_CONFLICT,
                )
            previous = self._generation_state(previous_id)
            if previous.get("state") != "ACTIVE" or not previous.get("theme_id"):
                return Result(
                    "conflicted",
                    "previous generation is not an active theme",
                    EXIT_CONFLICT,
                )
            return self._set_locked(str(previous["theme_id"]), reason="undo")

        return self._mutate(operation)

    def off(self) -> Result:
        return self._mutate(self._off_locked)

    def repair(self, adopt_current_baseline: bool = False) -> Result:
        def operation() -> Result:
            preferences = self._preferences()
            if preferences.get("legacy_conflict"):
                if not adopt_current_baseline:
                    return Result(
                        "conflicted",
                        "experimental state has no restorable baseline; "
                        "use --adopt-current-baseline to accept the current desktop",
                        EXIT_CONFLICT,
                    )
                preferences["legacy_conflict"] = False
                preferences["adopted_current_baseline"] = True
                preferences["enabled"] = None
                self._write_preferences(preferences)
                return Result(
                    "verified",
                    "current desktop accepted as the new unmanaged baseline",
                )

            current_id = self.store.current_id()
            if current_id is None:
                return Result("verified", "no managed generation requires repair")
            state = self._generation_state(current_id)
            if state.get("state") != "ACTIVE":
                return Result("verified", "no active theme requires repair")
            theme = self.themes.get(str(state.get("theme_id")))
            if theme is None:
                return Result(
                    "conflicted",
                    "active theme is no longer installed",
                    EXIT_CONFLICT,
                )
            context = self._context_from_state(state)
            adapters = self._adapters(theme, context, tuple(state["adapters"]))
            preflight = self._preflight_adapters(adapters, context)
            if preflight is not None:
                return preflight
            repair_ids: list[str] = []
            for adapter_id in state["adapters"]:
                adapter = adapters[adapter_id]
                try:
                    status = adapter.verify(context)
                except Exception as error:
                    return Result(
                        "conflicted",
                        f"repair preflight failed on {adapter_id}: {error}",
                        EXIT_CONFLICT,
                    )
                if status.status == "verified":
                    continue
                repair_ids.append(adapter_id)
            if not repair_ids:
                return Result("verified", "active generation verified")
            try:
                repair_records = {
                    adapter_id: adapters[adapter_id].capture(context)
                    for adapter_id in repair_ids
                }
            except Exception as error:
                return Result(
                    "conflicted",
                    f"repair capture failed before mutation: {error}",
                    EXIT_CONFLICT,
                )
            journal = self._create_engine_journal(
                {
                    "operation": "repair",
                    "source_generation_id": current_id,
                    "theme_id": theme.id,
                    "adapters": repair_ids,
                    "applied": [],
                    "records": self._encode_records(repair_records),
                    "phase": "REPAIRING",
                }
            )
            repaired: list[str] = []
            for adapter_id in repair_ids:
                repaired.append(adapter_id)
                self._update_engine_journal(journal, applied=repaired)
                try:
                    result = adapters[adapter_id].apply(
                        context, repair_records[adapter_id]
                    )
                except Exception as error:
                    return self._rollback_repair(
                        journal,
                        adapters,
                        context,
                        repair_records,
                        repaired,
                        adapter_id,
                        details=(str(error),),
                    )
                if result.status == "conflicted":
                    return self._rollback_repair(
                        journal,
                        adapters,
                        context,
                        repair_records,
                        repaired,
                        adapter_id,
                        conflict=True,
                        details=result.details,
                    )
                if result.status not in {"applied", "unchanged"}:
                    return self._rollback_repair(
                        journal,
                        adapters,
                        context,
                        repair_records,
                        repaired,
                        adapter_id,
                        details=result.details,
                    )
                try:
                    verification = adapters[adapter_id].verify(context)
                except Exception as error:
                    return self._rollback_repair(
                        journal,
                        adapters,
                        context,
                        repair_records,
                        repaired,
                        adapter_id,
                        details=(str(error),),
                    )
                if verification.status != "verified":
                    return self._rollback_repair(
                        journal,
                        adapters,
                        context,
                        repair_records,
                        repaired,
                        adapter_id,
                        conflict=verification.status == "conflicted",
                        details=verification.details,
                    )
            journal.unlink()
            return Result(
                "verified",
                "repaired: " + ", ".join(repaired),
            )

        return self._mutate(operation, allow_legacy_conflict=adopt_current_baseline)

    def status(self) -> StatusReport:
        if self.store.read_only:
            return self._status_report(
                read_only=True,
                message="state schema is newer than this engine supports",
            )
        try:
            with self._runtime_lock():
                preparation = self._prepare_locked()
                if preparation is not None and preparation.exit_code != EXIT_SUCCESS:
                    report = self._status_report(message=preparation.message)
                    if preparation.exit_code == EXIT_CONFLICT:
                        return replace(report, state="CONFLICTED")
                    return report
                return self._status_report()
        except StateConflict as error:
            return self._status_report(message=str(error))

    def list_themes(self) -> tuple[tuple[str, str], ...]:
        return tuple((theme.id, theme.name) for theme in self.themes.values())

    def _mutate(
        self,
        operation: Callable[[], Result],
        *,
        allow_legacy_conflict: bool = False,
    ) -> Result:
        if self.store.read_only:
            return Result(
                "read-only",
                "state schema is newer than this engine supports",
                EXIT_CONFLICT,
            )
        try:
            with self._runtime_lock():
                preparation = self._prepare_locked(
                    allow_legacy_conflict=allow_legacy_conflict
                )
                if preparation is not None:
                    return preparation
                return operation()
        except StateConflict as error:
            return Result("conflicted", str(error), EXIT_CONFLICT)

    def _prepare_locked(self, *, allow_legacy_conflict: bool = False) -> Result | None:
        self._detect_legacy_state()
        if self._preferences().get("legacy_conflict") and not allow_legacy_conflict:
            return Result(
                "conflicted",
                "experimental theme state was archived; adopt the current "
                "desktop explicitly before activating a managed theme",
                EXIT_CONFLICT,
            )
        recovery = self._recover_engine_journal()
        if recovery is not None and recovery.exit_code != EXIT_SUCCESS:
            return recovery
        self.store.recover_pointer()
        return None

    def _set_locked(self, theme_id: str, *, reason: str) -> Result:
        theme = self.themes.get(theme_id)
        if theme is None:
            return Result("conflicted", f"unknown theme: {theme_id}", EXIT_CONFLICT)
        missing = [
            adapter_id
            for adapter_id in theme.required_adapters
            if adapter_id not in self.adapter_factories
        ]
        if missing:
            return Result(
                "conflicted",
                "required adapters are unavailable: " + ", ".join(missing),
                EXIT_CONFLICT,
            )

        generation_id = self._generation_id()
        candidate = self.state_root / f".candidate-{generation_id}"
        if candidate.exists():
            raise StateConflict(f"candidate already exists: {candidate.name}")
        rendered = self.renderer(theme, candidate)
        adapter_ids = tuple(
            adapter_id
            for adapter_id in theme.required_adapters + theme.optional_adapters
            if adapter_id in self.adapter_factories
        )
        final_render = self.store.generations_path / generation_id / "rendered"
        values = self._context_values(theme, rendered.destination, final_render)
        context = ThemeContext(
            home=self.home,
            theme_root=final_render,
            values=values,
        )
        adapters = self._adapters(theme, context, adapter_ids)
        preflight = self._preflight_adapters(adapters, context)
        if preflight is not None:
            shutil.rmtree(candidate)
            return preflight
        apply_records = {
            adapter_id: adapters[adapter_id].capture(context)
            for adapter_id in adapter_ids
        }
        self._ensure_baseline(apply_records)
        state = {
            "schema_version": SCHEMA_VERSION,
            "state": "PREPARING",
            "generation_id": generation_id,
            "theme_id": theme.id,
            "theme_version": theme.version,
            "reason": reason,
            "adapters": list(adapter_ids),
            "context": self._json_value(values),
            "render_hashes": dict(rendered.hashes),
            "records": self._encode_records(apply_records),
            "surfaces": {adapter_id: "excluded" for adapter_id in adapter_ids},
        }
        generation = self.store.create_generation(generation_id, state)
        os.replace(candidate, generation / "rendered")
        self._fsync_directory(generation)

        journal = self._create_engine_journal(
            {
                "operation": "set",
                "generation_id": generation_id,
                "previous_generation_id": self.store.current_id(),
                "theme_id": theme.id,
                "adapters": list(adapter_ids),
                "applied": [],
                "phase": "APPLYING",
            }
        )
        applied: list[str] = []
        try:
            for adapter_id in adapter_ids:
                try:
                    result = adapters[adapter_id].apply(
                        context, apply_records[adapter_id]
                    )
                except Exception as error:
                    applied.append(adapter_id)
                    self._update_engine_journal(journal, applied=applied)
                    return self._rollback_apply(
                        journal,
                        adapters,
                        context,
                        apply_records,
                        applied,
                        adapter_id,
                        conflict=False,
                        details=(str(error),),
                    )
                applied.append(adapter_id)
                self._update_engine_journal(journal, applied=applied)
                self.fault_hook("after_adapter", adapter_id)
                if result.status == "conflicted":
                    return self._rollback_apply(
                        journal,
                        adapters,
                        context,
                        apply_records,
                        applied,
                        adapter_id,
                        conflict=True,
                        details=result.details,
                    )
                if result.status not in {"applied", "unchanged"}:
                    return self._rollback_apply(
                        journal,
                        adapters,
                        context,
                        apply_records,
                        applied,
                        adapter_id,
                        conflict=False,
                        details=result.details,
                    )
            surfaces: dict[str, str] = {}
            for adapter_id in adapter_ids:
                try:
                    verification = adapters[adapter_id].verify(context)
                except Exception as error:
                    return self._rollback_apply(
                        journal,
                        adapters,
                        context,
                        apply_records,
                        applied,
                        adapter_id,
                        conflict=False,
                        details=(str(error),),
                    )
                surfaces[adapter_id] = verification.status
                if verification.status != "verified":
                    return self._rollback_apply(
                        journal,
                        adapters,
                        context,
                        apply_records,
                        applied,
                        adapter_id,
                        conflict=verification.status == "conflicted",
                        details=verification.details,
                    )
            self._update_engine_journal(journal, phase="VERIFIED")
            self.fault_hook("after_verify", None)
            committed_records = self._with_baseline(apply_records)
            state["state"] = "ACTIVE"
            state["records"] = self._encode_records(committed_records)
            state["surfaces"] = surfaces
            self._write_generation_state(generation_id, state)
            self.store.commit_generation(generation_id)
            preferences = self._preferences()
            preferences.update(enabled=True, last_theme=theme.id)
            self._write_preferences(preferences)
            journal.unlink()
            return Result("verified", f"applied {theme.id}")
        finally:
            if candidate.exists():
                shutil.rmtree(candidate)

    def _off_locked(self) -> Result:
        current_id = self.store.current_id()
        if current_id is None:
            preferences = self._preferences()
            preferences["enabled"] = False
            self._write_preferences(preferences)
            return Result("verified", "theme already disabled")
        current = self._generation_state(current_id)
        if current.get("state") == "DISABLED":
            preferences = self._preferences()
            preferences["enabled"] = False
            self._write_preferences(preferences)
            return Result("verified", "theme already disabled")
        if current.get("state") != "ACTIVE":
            return Result(
                "conflicted",
                f"cannot disable generation in {current.get('state')} state",
                EXIT_CONFLICT,
            )
        theme = self.themes.get(str(current.get("theme_id")))
        if theme is None:
            return Result(
                "conflicted",
                "active theme is no longer installed",
                EXIT_CONFLICT,
            )
        adapter_ids = tuple(current["adapters"])
        context = self._context_from_state(current)
        adapters = self._adapters(theme, context, adapter_ids)
        records = self._decode_records(current["records"])
        journal = self._create_engine_journal(
            {
                "operation": "off",
                "source_generation_id": current_id,
                "theme_id": theme.id,
                "adapters": list(adapter_ids),
                "applied": [],
                "phase": "RESTORING",
            }
        )
        restored: list[str] = []
        for adapter_id in reversed(adapter_ids):
            attempted = [*restored, adapter_id]
            self._update_engine_journal(journal, applied=attempted)
            try:
                result = adapters[adapter_id].restore(context, records[adapter_id])
            except Exception as error:
                rollback_conflicts = self._reapply_restored(
                    adapters, context, records, reversed(attempted)
                )
                if rollback_conflicts:
                    return Result(
                        "conflicted",
                        "off failure could not restore the active generation",
                        EXIT_CONFLICT,
                        tuple(rollback_conflicts),
                    )
                journal.unlink()
                return Result(
                    "rolled-back",
                    f"off failure on {adapter_id} was rolled back",
                    EXIT_ADAPTER_FAILURE,
                    (str(error),),
                )
            if result.status == "conflicted":
                rollback_conflicts = self._reapply_restored(
                    adapters, context, records, reversed(restored)
                )
                if not rollback_conflicts:
                    journal.unlink()
                return Result(
                    "conflicted",
                    f"off preserved external changes on {adapter_id}",
                    EXIT_CONFLICT,
                    result.details + tuple(rollback_conflicts),
                )
            if result.status not in {"restored", "unchanged"}:
                rollback_conflicts = self._reapply_restored(
                    adapters, context, records, reversed(attempted)
                )
                if rollback_conflicts:
                    return Result(
                        "conflicted",
                        "off failure could not restore the active generation",
                        EXIT_CONFLICT,
                        tuple(rollback_conflicts),
                    )
                journal.unlink()
                return Result(
                    "rolled-back",
                    f"off failed on {adapter_id}",
                    EXIT_ADAPTER_FAILURE,
                    result.details,
                )
            restored.append(adapter_id)
            self._update_engine_journal(journal, applied=restored)
        disabled_id = self._generation_id()
        self.store.create_generation(
            disabled_id,
            {
                "schema_version": SCHEMA_VERSION,
                "state": "DISABLED",
                "generation_id": disabled_id,
                "theme_id": None,
                "adapters": [],
                "context": {},
                "records": {},
                "surfaces": {},
            },
        )
        self.store.commit_generation(disabled_id)
        preferences = self._preferences()
        preferences.update(enabled=False, last_theme=theme.id)
        self._write_preferences(preferences)
        journal.unlink()
        return Result("verified", "Dudley theme disabled")

    def _rollback_apply(
        self,
        journal: Path,
        adapters: Mapping[str, Adapter],
        context: ThemeContext,
        records: Mapping[str, list[ResourceRecord]],
        applied: list[str],
        failed_adapter: str,
        *,
        conflict: bool,
        details: tuple[str, ...],
    ) -> Result:
        rollback_conflicts = self._restore_applied(
            adapters, context, records, reversed(applied)
        )
        if not rollback_conflicts:
            journal.unlink()
        if rollback_conflicts:
            return Result(
                "conflicted",
                "adapter rollback failed to restore the prior state safely",
                EXIT_CONFLICT,
                tuple(rollback_conflicts),
            )
        if conflict:
            return Result(
                "conflicted",
                f"external changes blocked {failed_adapter}",
                EXIT_CONFLICT,
                details,
            )
        return Result(
            "rolled-back",
            f"adapter failure on {failed_adapter} was rolled back",
            EXIT_ADAPTER_FAILURE,
            details,
        )

    def _rollback_repair(
        self,
        journal: Path,
        adapters: Mapping[str, Adapter],
        context: ThemeContext,
        records: Mapping[str, list[ResourceRecord]],
        applied: list[str],
        failed_adapter: str,
        *,
        conflict: bool = False,
        details: tuple[str, ...] = (),
    ) -> Result:
        rollback_conflicts = self._restore_applied(
            adapters, context, records, reversed(applied)
        )
        if rollback_conflicts:
            return Result(
                "conflicted",
                "repair failure could not restore pre-repair state",
                EXIT_CONFLICT,
                tuple(rollback_conflicts),
            )
        journal.unlink()
        if conflict:
            return Result(
                "conflicted",
                f"repair preserved external changes on {failed_adapter}",
                EXIT_CONFLICT,
                details,
            )
        return Result(
            "rolled-back",
            f"repair failure on {failed_adapter} was rolled back",
            EXIT_ADAPTER_FAILURE,
            details,
        )

    @staticmethod
    def _preflight_adapters(
        adapters: Mapping[str, Adapter], context: ThemeContext
    ) -> Result | None:
        for adapter_id, adapter in adapters.items():
            preflight = getattr(adapter, "preflight", None)
            if preflight is None:
                continue
            try:
                status = preflight(context)
            except Exception as error:
                return Result(
                    "conflicted",
                    f"adapter preflight failed on {adapter_id}: {error}",
                    EXIT_CONFLICT,
                )
            if status.status not in {"ready", "supported", "verified"}:
                return Result(
                    "conflicted",
                    f"adapter preflight rejected {adapter_id}: {status.status}",
                    EXIT_CONFLICT,
                    getattr(status, "details", ()),
                )
        return None

    @staticmethod
    def _restore_applied(
        adapters: Mapping[str, Adapter],
        context: ThemeContext,
        records: Mapping[str, list[ResourceRecord]],
        adapter_ids: Iterator[str],
    ) -> list[str]:
        conflicts: list[str] = []
        for adapter_id in adapter_ids:
            try:
                result = adapters[adapter_id].restore(context, records[adapter_id])
            except Exception as error:
                conflicts.append(f"{adapter_id}: {error}")
                continue
            if result.status == "conflicted":
                conflicts.extend(result.details or (adapter_id,))
            elif result.status not in {"restored", "unchanged"}:
                conflicts.extend(result.details or (adapter_id,))
        return conflicts

    def _recover_engine_journal(self) -> Result | None:
        journals = sorted(
            self.store.transactions_path.glob(f"{self.engine_journal_prefix}*.json")
        )
        if not journals:
            return None
        if len(journals) != 1:
            return Result(
                "conflicted",
                "multiple incomplete theme transactions require inspection",
                EXIT_CONFLICT,
            )
        journal = journals[0]
        try:
            record = json.loads(journal.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return Result(
                "conflicted",
                "theme transaction journal is unreadable",
                EXIT_CONFLICT,
            )
        if record.get("operation") == "off":
            return self._recover_off_journal(journal, record)
        if record.get("operation") != "set":
            return Result(
                "conflicted",
                "theme transaction journal has an unknown operation",
                EXIT_CONFLICT,
            )
        generation_id = record.get("generation_id")
        if not isinstance(generation_id, str):
            return Result(
                "conflicted",
                "theme transaction journal is missing its generation",
                EXIT_CONFLICT,
            )
        try:
            state = self._generation_state(generation_id)
        except StateConflict as error:
            return Result("conflicted", str(error), EXIT_CONFLICT)
        theme = self.themes.get(str(record.get("theme_id")))
        if theme is None:
            return Result(
                "conflicted",
                "interrupted transaction theme is no longer installed",
                EXIT_CONFLICT,
            )
        adapter_ids = tuple(record.get("adapters", ()))
        context = self._context_from_state(state)
        adapters = self._adapters(theme, context, adapter_ids)
        records = self._decode_records(state["records"])
        applied = [
            adapter_id
            for adapter_id in record.get("applied", ())
            if adapter_id in adapters
        ]
        if record.get("phase") == "VERIFIED" and applied == list(adapter_ids):
            try:
                verified = all(
                    adapters[adapter_id].verify(context).status == "verified"
                    for adapter_id in adapter_ids
                )
            except Exception as error:
                return Result(
                    "conflicted",
                    f"interrupted activation verify failure: {error}",
                    EXIT_CONFLICT,
                )
            if verified:
                state["state"] = "ACTIVE"
                state["records"] = self._encode_records(self._with_baseline(records))
                state["surfaces"] = {
                    adapter_id: "verified" for adapter_id in adapter_ids
                }
                self._write_generation_state(generation_id, state)
                self.store.commit_generation(generation_id)
                preferences = self._preferences()
                preferences.update(enabled=True, last_theme=theme.id)
                self._write_preferences(preferences)
                journal.unlink()
                return Result(
                    "verified",
                    f"completed interrupted activation of {theme.id}",
                )
        conflicts = self._restore_applied(adapters, context, records, reversed(applied))
        if conflicts:
            return Result(
                "conflicted",
                "interrupted activation could not be restored safely",
                EXIT_CONFLICT,
                tuple(conflicts),
            )
        journal.unlink()
        return Result("verified", "rolled back interrupted theme activation")

    def _recover_off_journal(self, journal: Path, record: Mapping[str, Any]) -> Result:
        source_id = record.get("source_generation_id")
        if not isinstance(source_id, str):
            return Result(
                "conflicted", "off journal is missing its source", EXIT_CONFLICT
            )
        state = self._generation_state(source_id)
        theme = self.themes.get(str(record.get("theme_id")))
        if theme is None:
            return Result(
                "conflicted",
                "interrupted off theme is no longer installed",
                EXIT_CONFLICT,
            )
        adapter_ids = tuple(state["adapters"])
        context = self._context_from_state(state)
        adapters = self._adapters(theme, context, adapter_ids)
        records = self._decode_records(state["records"])
        completed = [
            adapter_id
            for adapter_id in record.get("applied", ())
            if adapter_id in adapters
        ]
        conflicts = self._reapply_restored(
            adapters, context, records, reversed(completed)
        )
        if conflicts:
            return Result(
                "conflicted",
                "interrupted off could not restore the active generation",
                EXIT_CONFLICT,
                tuple(conflicts),
            )
        journal.unlink()
        return Result("verified", "rolled back interrupted theme disable")

    def _reapply_restored(
        self,
        adapters: Mapping[str, Adapter],
        context: ThemeContext,
        records: Mapping[str, list[ResourceRecord]],
        adapter_ids: Iterator[str],
    ) -> list[str]:
        conflicts: list[str] = []
        for adapter_id in adapter_ids:
            try:
                result = adapters[adapter_id].apply(context, records[adapter_id])
            except Exception as error:
                conflicts.append(f"{adapter_id}: {error}")
                continue
            if result.status not in {"applied", "unchanged"}:
                conflicts.extend(result.details or (adapter_id,))
        return conflicts

    def _status_report(
        self, *, read_only: bool = False, message: str = ""
    ) -> StatusReport:
        preferences = self._preferences()
        if preferences.get("legacy_conflict"):
            return StatusReport(
                "CONFLICTED",
                None,
                None,
                {},
                read_only=read_only,
                message=message or "experimental state has no restorable baseline",
            )
        current_id = self.store.current_id()
        if current_id is None:
            state = "DISABLED" if preferences.get("enabled") is False else "UNMANAGED"
            return StatusReport(
                state, None, None, {}, read_only=read_only, message=message
            )
        try:
            generation = self._generation_state(current_id)
        except StateConflict as error:
            return StatusReport(
                "CONFLICTED",
                None,
                None,
                {},
                read_only=read_only,
                message=message or str(error),
            )
        state = str(generation.get("state", "CONFLICTED"))
        theme_id = generation.get("theme_id")
        surfaces = dict(generation.get("surfaces", {}))
        if state == "ACTIVE" and theme_id in self.themes and not read_only:
            context = self._context_from_state(generation)
            adapters = self._adapters(
                self.themes[str(theme_id)],
                context,
                tuple(generation.get("adapters", ())),
            )
            surfaces = {}
            verify_errors: list[str] = []
            for adapter_id in generation.get("adapters", ()):
                try:
                    surfaces[adapter_id] = adapters[adapter_id].verify(context).status
                except Exception as error:
                    surfaces[adapter_id] = "conflicted"
                    verify_errors.append(f"{adapter_id}: {error}")
            if verify_errors and not message:
                message = "adapter verify failure: " + "; ".join(verify_errors)
            if any(value == "conflicted" for value in surfaces.values()):
                state = "CONFLICTED"
        return StatusReport(
            state,
            str(theme_id) if theme_id is not None else None,
            current_id,
            surfaces,
            read_only=read_only,
            message=message,
        )

    def _adapters(
        self,
        theme: ThemeManifest,
        context: ThemeContext,
        adapter_ids: tuple[str, ...],
    ) -> dict[str, Adapter]:
        adapters: dict[str, Adapter] = {}
        for adapter_id in adapter_ids:
            factory = self.adapter_factories.get(adapter_id)
            if factory is None:
                raise StateConflict(f"adapter is unavailable: {adapter_id}")
            adapters[adapter_id] = (
                factory if isinstance(factory, Adapter) else factory(theme, context)
            )
        return adapters

    def _context_values(
        self,
        theme: ThemeManifest,
        rendered_root: Path,
        final_render: Path,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {"theme_id": theme.id}
        outputs = {output.source: output.path for output in theme.render_outputs}
        assets = theme.manifest.get("assets", {})
        if isinstance(assets, Mapping):
            for adapter_id in ("kitty", "ghostty", "neovim", "btop"):
                source = assets.get(adapter_id)
                if isinstance(source, str) and source in outputs:
                    values[adapter_id] = str(final_render / outputs[source])
            vscode_source = assets.get("vscode")
            if isinstance(vscode_source, str) and vscode_source in outputs:
                values["vscode"] = json.loads(
                    (rendered_root / outputs[vscode_source]).read_text(encoding="utf-8")
                )
            wallpaper_source = assets.get("default_wallpaper")
            if isinstance(wallpaper_source, str):
                source = (theme.root / wallpaper_source).resolve()
                try:
                    source.relative_to(theme.root.resolve())
                except ValueError as error:
                    raise StateConflict(
                        "default wallpaper escapes the installed theme"
                    ) from error
                destination = rendered_root / "assets" / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                values["wallpaper"] = str(final_render / "assets" / source.name)
        return values

    def _default_adapter_factories(
        self,
    ) -> dict[str, AdapterFactory]:
        app_types = {
            "kitty": KittyAdapter,
            "ghostty": GhosttyAdapter,
            "neovim": NeovimAdapter,
            "btop": BtopAdapter,
            "vscode": VSCodeAdapter,
        }
        factories: dict[str, AdapterFactory] = {
            adapter_id: (lambda _theme, _context, cls=cls: cls())
            for adapter_id, cls in app_types.items()
        }

        def gnome(theme: ThemeManifest, _context: ThemeContext) -> Adapter:
            settings = theme.manifest.get("gnome", {})
            values = {
                (INTERFACE, "color-scheme"): repr(
                    str(settings.get("color_scheme", "prefer-dark"))
                ),
                (INTERFACE, "accent-color"): repr(str(settings.get("accent", "blue"))),
                (INTERFACE, "gtk-theme"): repr(
                    str(settings.get("gtk_theme", "Dudley-Wellness-Floor"))
                ),
                (INTERFACE, "icon-theme"): repr(
                    str(settings.get("icon_theme", "Yaru-blue"))
                ),
                (INTERFACE, "cursor-theme"): repr(
                    str(settings.get("cursor_theme", "Adwaita"))
                ),
                (USER_THEME, "name"): repr(
                    str(settings.get("shell_theme", "Dudley-Wellness-Floor"))
                ),
            }
            return GnomeAdapter(
                extension_id=str(
                    settings.get(
                        "user_themes_extension",
                        "user-theme@gnome-shell-extensions.gcampax.github.com",
                    )
                ),
                values=values,
            )

        factories["gnome"] = gnome
        return factories

    def _ensure_baseline(self, records: Mapping[str, list[ResourceRecord]]) -> None:
        path = self.store.baseline_path / "records.json"
        if path.exists():
            return
        self._atomic_json(path, {"records": self._encode_records(records)})

    def _baseline_records(self) -> dict[str, list[ResourceRecord]]:
        path = self.store.baseline_path / "records.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return self._decode_records(value["records"])
        except (OSError, json.JSONDecodeError, KeyError) as error:
            raise StateConflict("theme baseline is unreadable") from error

    def _with_baseline(
        self, records: Mapping[str, list[ResourceRecord]]
    ) -> dict[str, list[ResourceRecord]]:
        baseline = self._baseline_records()
        baseline_by_resource = {
            (adapter_id, record.resource): record
            for adapter_id, adapter_records in baseline.items()
            for record in adapter_records
        }
        committed: dict[str, list[ResourceRecord]] = {}
        for adapter_id, adapter_records in records.items():
            committed[adapter_id] = []
            for record in adapter_records:
                original = baseline_by_resource.get(
                    (adapter_id, record.resource), record
                )
                committed[adapter_id].append(replace(record, before=original.before))
        return committed

    def _detect_legacy_state(self) -> None:
        if self.store.current_id() is not None:
            return
        preferences = self._preferences()
        if preferences.get("legacy_checked"):
            return
        legacy_paths = (
            self.home / ".config/dudley/theme",
            self.home / ".config/dudley/theme-receipt.json",
        )
        existing = [path for path in legacy_paths if path.exists()]
        if existing:
            archive = self.state_root / "legacy"
            archive.mkdir(exist_ok=True)
            for path in existing:
                destination = archive / path.name
                if destination.exists():
                    destination = archive / f"{path.name}-{uuid.uuid4().hex}"
                os.replace(path, destination)
            preferences["legacy_conflict"] = True
        preferences["legacy_checked"] = True
        self._write_preferences(preferences)

    def _preferences(self) -> dict[str, Any]:
        try:
            value = json.loads(self.store.preferences_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        return value if isinstance(value, dict) else {}

    def _write_preferences(self, preferences: Mapping[str, Any]) -> None:
        value = dict(preferences)
        value.setdefault("schema_version", SCHEMA_VERSION)
        self._atomic_json(self.store.preferences_path, value)

    def _generation_state(self, generation_id: str) -> dict[str, Any]:
        path = self.store.generations_path / generation_id / "state.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise StateConflict(
                f"generation state is unreadable: {generation_id}"
            ) from error
        if not isinstance(value, dict):
            raise StateConflict(f"generation state is invalid: {generation_id}")
        return value

    def _write_generation_state(
        self, generation_id: str, state: Mapping[str, Any]
    ) -> None:
        path = self.store.generations_path / generation_id / "state.json"
        self._atomic_json(path, state)

    def _context_from_state(self, state: Mapping[str, Any]) -> ThemeContext:
        generation_id = str(state["generation_id"])
        return ThemeContext(
            home=self.home,
            theme_root=self.store.generations_path / generation_id / "rendered",
            values=state.get("context", {}),
        )

    def _create_engine_journal(self, value: Mapping[str, Any]) -> Path:
        path = (
            self.store.transactions_path
            / f"{self.engine_journal_prefix}{uuid.uuid4().hex}.json"
        )
        self._atomic_json(path, value)
        return path

    def _update_engine_journal(self, path: Path, **updates: Any) -> None:
        value = json.loads(path.read_text(encoding="utf-8"))
        value.update(updates)
        self._atomic_json(path, value)

    def _encode_records(
        self, records: Mapping[str, list[ResourceRecord]]
    ) -> dict[str, Any]:
        return {
            adapter_id: [self._encode_value(record) for record in adapter_records]
            for adapter_id, adapter_records in records.items()
        }

    def _decode_records(
        self, records: Mapping[str, Any]
    ) -> dict[str, list[ResourceRecord]]:
        return {
            adapter_id: [self._decode_value(record) for record in adapter_records]
            for adapter_id, adapter_records in records.items()
        }

    def _encode_value(self, value: Any) -> Any:
        dataclass_types = {
            ResourceRecord: "ResourceRecord",
            FileResource: "FileResource",
            LineResource: "LineResource",
            JsoncResource: "JsoncResource",
            SettingResource: "SettingResource",
            ExtensionResource: "ExtensionResource",
        }
        for value_type, name in dataclass_types.items():
            if isinstance(value, value_type):
                return {
                    "__type__": name,
                    "fields": {
                        field.name: self._encode_value(getattr(value, field.name))
                        for field in fields(value)
                    },
                }
        if isinstance(value, Path):
            return {"__type__": "Path", "value": str(value)}
        if isinstance(value, bytes):
            return {
                "__type__": "bytes",
                "value": base64.b64encode(value).decode("ascii"),
            }
        if isinstance(value, tuple):
            return {
                "__type__": "tuple",
                "items": [self._encode_value(item) for item in value],
            }
        if isinstance(value, list):
            return [self._encode_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._encode_value(item) for key, item in value.items()}
        return value

    def _decode_value(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self._decode_value(item) for item in value]
        if not isinstance(value, dict):
            return value
        value_type = value.get("__type__")
        if value_type == "Path":
            return Path(value["value"])
        if value_type == "bytes":
            return base64.b64decode(value["value"])
        if value_type == "tuple":
            return tuple(self._decode_value(item) for item in value["items"])
        dataclass_types = {
            "ResourceRecord": ResourceRecord,
            "FileResource": FileResource,
            "LineResource": LineResource,
            "JsoncResource": JsoncResource,
            "SettingResource": SettingResource,
            "ExtensionResource": ExtensionResource,
        }
        if value_type in dataclass_types:
            fields = {
                key: self._decode_value(item) for key, item in value["fields"].items()
            }
            return dataclass_types[value_type](**fields)
        return {key: self._decode_value(item) for key, item in value.items()}

    def _json_value(self, value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, Mapping):
            return {key: self._json_value(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return [self._json_value(item) for item in value]
        if isinstance(value, list):
            return [self._json_value(item) for item in value]
        return value

    @contextmanager
    def _runtime_lock(self) -> Iterator[None]:
        try:
            metadata = self.runtime_dir.lstat()
        except FileNotFoundError as error:
            raise StateConflict(
                "trusted per-user runtime directory is absent"
            ) from error
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise StateConflict(
                "trusted per-user runtime directory has unsafe ownership or permissions"
            )
        descriptor = os.open(
            self.lock_path,
            os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _atomic_json(self, path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
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

    @staticmethod
    def _generation_id() -> str:
        return f"{time.time_ns():020d}-{uuid.uuid4().hex}"

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
