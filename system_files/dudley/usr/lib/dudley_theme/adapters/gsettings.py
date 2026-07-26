"""Typed, conflict-aware GSettings capture and restoration."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Mapping, Protocol

from dudley_theme.model import ResourceRecord

from .base import Adapter, AdapterResult, AdapterStatus, ThemeContext


class SettingsBackend(Protocol):
    """Minimal backend contract that keeps GVariant values typed."""

    def read(self, schema: str, key: str) -> str | None: ...

    def write(self, schema: str, key: str, value: str) -> None: ...

    def reset(self, schema: str, key: str) -> None: ...


@dataclass(frozen=True)
class SettingResource:
    schema: str
    key: str
    value: str | None
    unset: bool


class CommandSettingsBackend:
    """Use dconf for user-value capture and gsettings for typed writes."""

    def read(self, schema: str, key: str) -> str | None:
        result = subprocess.run(
            ["dconf", "read", self._dconf_path(schema, key)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode not in {0, 1}:
            raise RuntimeError(result.stderr.strip() or "dconf read failed")
        value = result.stdout.strip()
        return value or None

    def write(self, schema: str, key: str, value: str) -> None:
        subprocess.run(
            ["gsettings", "set", schema, key, value],
            check=True,
            capture_output=True,
            text=True,
        )

    def reset(self, schema: str, key: str) -> None:
        subprocess.run(
            ["gsettings", "reset", schema, key],
            check=True,
            capture_output=True,
            text=True,
        )

    @staticmethod
    def _dconf_path(schema: str, key: str) -> str:
        return f"/{schema.replace('.', '/')}/{key}"


def capture_setting(backend: SettingsBackend, schema: str, key: str) -> SettingResource:
    value = backend.read(schema, key)
    return SettingResource(schema=schema, key=key, value=value, unset=value is None)


def write_managed_setting(
    record: SettingResource, value: str, backend: SettingsBackend
) -> SettingResource:
    current = capture_setting(backend, record.schema, record.key)
    if current != record:
        raise RuntimeError(
            f"setting changed after capture: {record.schema} {record.key}"
        )
    backend.write(record.schema, record.key, value)
    return capture_setting(backend, record.schema, record.key)


def verify_setting(
    expected: SettingResource, backend: SettingsBackend
) -> AdapterStatus:
    current = capture_setting(backend, expected.schema, expected.key)
    if current == expected:
        return AdapterStatus("verified")
    return AdapterStatus("drifted", (f"{expected.schema} {expected.key}",))


def restore_setting(
    record: SettingResource,
    *,
    expected: SettingResource,
    backend: SettingsBackend,
) -> AdapterResult:
    current = capture_setting(backend, record.schema, record.key)
    if current == record:
        return AdapterResult("unchanged")
    if current != expected:
        return AdapterResult("conflicted", (f"{record.schema} {record.key}",))
    if record.unset:
        backend.reset(record.schema, record.key)
    elif record.value is not None:
        backend.write(record.schema, record.key, record.value)
    return AdapterResult("restored")


class GSettingsAdapter(Adapter):
    """Apply a curated mapping of typed GVariant values transactionally."""

    def __init__(
        self,
        settings: Mapping[tuple[str, str], str],
        *,
        backend: SettingsBackend | None = None,
    ) -> None:
        self.settings = dict(settings)
        self.backend = backend or CommandSettingsBackend()

    def capture(self, context: ThemeContext) -> list[ResourceRecord]:
        del context
        records: list[ResourceRecord] = []
        for (schema, key), value in self.settings.items():
            before = capture_setting(self.backend, schema, key)
            records.append(
                ResourceRecord(
                    adapter="gsettings",
                    resource=f"{schema} {key}",
                    before=before,
                    applied=SettingResource(
                        schema=schema,
                        key=key,
                        value=value,
                        unset=False,
                    ),
                )
            )
        return records

    def apply(
        self, context: ThemeContext, records: list[ResourceRecord]
    ) -> AdapterResult:
        del context
        conflicts = [
            record.resource
            for record in records
            if capture_setting(self.backend, record.before.schema, record.before.key)
            not in {record.before, record.applied}
        ]
        if conflicts:
            return AdapterResult("conflicted", tuple(conflicts))
        for record in records:
            current = capture_setting(
                self.backend, record.before.schema, record.before.key
            )
            if current != record.applied:
                self.backend.write(
                    record.applied.schema,
                    record.applied.key,
                    record.applied.value,
                )
        return AdapterResult("applied")

    def verify(self, context: ThemeContext) -> AdapterStatus:
        records = self.capture(context)
        drift = [
            record.resource
            for record in records
            if capture_setting(self.backend, record.before.schema, record.before.key)
            != record.applied
        ]
        return (
            AdapterStatus("drifted", tuple(drift))
            if drift
            else AdapterStatus("verified")
        )

    def restore(
        self, context: ThemeContext, records: list[ResourceRecord]
    ) -> AdapterResult:
        del context
        results = [
            restore_setting(
                record.before,
                expected=record.applied,
                backend=self.backend,
            )
            for record in records
        ]
        conflicts = tuple(
            detail
            for result in results
            if result.status == "conflicted"
            for detail in result.details
        )
        if conflicts:
            return AdapterResult("conflicted", conflicts)
        if any(result.status == "restored" for result in results):
            return AdapterResult("restored")
        return AdapterResult("unchanged")
