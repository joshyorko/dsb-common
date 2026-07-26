"""Reversible GNOME theme settings and User Themes extension adapter."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Protocol

from dudley_theme.model import ResourceRecord

from .base import Adapter, AdapterResult, AdapterStatus, ThemeContext
from .files import (
    FileResource,
    capture_file,
    expected_managed_link,
    restore_file,
    write_managed_link,
)
from .gsettings import (
    CommandSettingsBackend,
    SettingResource,
    SettingsBackend,
    capture_setting,
    restore_setting,
)


USER_THEMES_EXTENSION = "user-theme@gnome-shell-extensions.gcampax.github.com"
THEME_NAME = "Dudley-Wellness-Floor"

INTERFACE = "org.gnome.desktop.interface"
BACKGROUND = "org.gnome.desktop.background"
SCREENSAVER = "org.gnome.desktop.screensaver"
USER_THEME = "org.gnome.shell.extensions.user-theme"


class ExtensionBackend(Protocol):
    def enabled(self, extension_id: str) -> bool: ...

    def enable(self, extension_id: str) -> None: ...

    def disable(self, extension_id: str) -> None: ...


class GnomeCommandSettingsBackend(CommandSettingsBackend):
    """Capture explicit values while validating their canonical GVariant form."""

    def read(self, schema: str, key: str) -> str | None:
        explicit = super().read(schema, key)
        if explicit is None:
            return None
        result = subprocess.run(
            ["gsettings", "get", schema, key],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()


class CommandExtensionBackend:
    """Control one installed GNOME Shell extension with gnome-extensions."""

    def enabled(self, extension_id: str) -> bool:
        result = subprocess.run(
            ["gnome-extensions", "list", "--enabled"],
            check=True,
            capture_output=True,
            text=True,
        )
        return extension_id in result.stdout.splitlines()

    def enable(self, extension_id: str) -> None:
        subprocess.run(
            ["gnome-extensions", "enable", extension_id],
            check=True,
            capture_output=True,
            text=True,
        )

    def disable(self, extension_id: str) -> None:
        subprocess.run(
            ["gnome-extensions", "disable", extension_id],
            check=True,
            capture_output=True,
            text=True,
        )


@dataclass(frozen=True)
class ExtensionResource:
    extension_id: str
    enabled: bool


class GnomeAdapter(Adapter):
    """Apply the qualified Dudley GNOME surface without bundling icon art."""

    settings = (
        (INTERFACE, "color-scheme"),
        (INTERFACE, "accent-color"),
        (INTERFACE, "gtk-theme"),
        (INTERFACE, "icon-theme"),
        (INTERFACE, "cursor-theme"),
        (USER_THEME, "name"),
        (BACKGROUND, "picture-uri"),
        (BACKGROUND, "picture-uri-dark"),
        (SCREENSAVER, "picture-uri"),
    )

    def __init__(
        self,
        *,
        settings_backend: SettingsBackend | None = None,
        extension_backend: ExtensionBackend | None = None,
        extension_id: str = USER_THEMES_EXTENSION,
        values: Mapping[tuple[str, str], str] | None = None,
    ) -> None:
        self.settings_backend = settings_backend or GnomeCommandSettingsBackend()
        self.extension_backend = extension_backend or CommandExtensionBackend()
        self.extension_id = extension_id
        self.values = dict(values or {})
        self._applied: dict[
            str, SettingResource | ExtensionResource | FileResource
        ] = {}

    def capture(self, context: ThemeContext) -> list[ResourceRecord]:
        desired = self._desired_settings(context)
        records = [
            ResourceRecord(
                adapter="gnome",
                resource=f"{schema} {key}",
                before=capture_setting(self.settings_backend, schema, key),
                applied=self._applied.get(
                    f"{schema} {key}",
                    SettingResource(schema, key, desired[(schema, key)], False),
                ),
            )
            for schema, key in self.settings
        ]
        before_extension = ExtensionResource(
            self.extension_id,
            self.extension_backend.enabled(self.extension_id),
        )
        records.append(
            ResourceRecord(
                adapter="gnome",
                resource=self.extension_id,
                before=before_extension,
                applied=self._applied.get(
                    self.extension_id,
                    ExtensionResource(self.extension_id, True),
                ),
            )
        )
        for link, source in self._theme_links(context).items():
            records.append(
                ResourceRecord(
                    adapter="gnome",
                    resource=str(link),
                    before=capture_file(link),
                    applied=self._applied.get(
                        str(link),
                        expected_managed_link(link, str(source)),
                    ),
                )
            )
        return records

    def apply(
        self, context: ThemeContext, records: list[ResourceRecord]
    ) -> AdapterResult:
        del context
        conflicts = self._preflight(records)
        if conflicts:
            return AdapterResult("conflicted", tuple(conflicts))

        for index, record in enumerate(records):
            if isinstance(record.before, SettingResource):
                current = capture_setting(
                    self.settings_backend,
                    record.before.schema,
                    record.before.key,
                )
                if current != record.applied:
                    self.settings_backend.write(
                        record.applied.schema,
                        record.applied.key,
                        record.applied.value,
                    )
                    current = capture_setting(
                        self.settings_backend,
                        record.before.schema,
                        record.before.key,
                    )
                records[index] = replace(record, applied=current)
                self._applied[record.resource] = current
            elif isinstance(record.before, FileResource):
                current_file = capture_file(record.before.path)
                if current_file.fingerprint != record.applied.fingerprint:
                    current_file = write_managed_link(
                        record.before.path,
                        str(record.applied.link_target),
                    )
                records[index] = replace(record, applied=current_file)
                self._applied[record.resource] = current_file
            else:
                current_extension = ExtensionResource(
                    self.extension_id,
                    self.extension_backend.enabled(self.extension_id),
                )
                if not current_extension.enabled:
                    self.extension_backend.enable(self.extension_id)
                applied_extension = ExtensionResource(
                    self.extension_id,
                    self.extension_backend.enabled(self.extension_id),
                )
                records[index] = replace(record, applied=applied_extension)
                self._applied[record.resource] = applied_extension
        return AdapterResult("applied")

    def verify(self, context: ThemeContext) -> AdapterStatus:
        records = self.capture(context)
        drift = []
        for record in records:
            if isinstance(record.before, SettingResource):
                current = capture_setting(
                    self.settings_backend,
                    record.before.schema,
                    record.before.key,
                )
            elif isinstance(record.before, FileResource):
                current = capture_file(record.before.path)
            else:
                current = ExtensionResource(
                    self.extension_id,
                    self.extension_backend.enabled(self.extension_id),
                )
            if current != record.applied:
                drift.append(record.resource)
        return (
            AdapterStatus("drifted", tuple(drift))
            if drift
            else AdapterStatus("verified")
        )

    def restore(
        self, context: ThemeContext, records: list[ResourceRecord]
    ) -> AdapterResult:
        del context
        results: list[AdapterResult] = []
        for record in reversed(records):
            if isinstance(record.before, SettingResource):
                results.append(
                    restore_setting(
                        record.before,
                        expected=record.applied,
                        backend=self.settings_backend,
                    )
                )
            elif isinstance(record.before, FileResource):
                results.append(restore_file(record.before, expected=record.applied))
            else:
                results.append(self._restore_extension(record))
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

    def _preflight(self, records: list[ResourceRecord]) -> list[str]:
        conflicts = []
        for record in records:
            if isinstance(record.before, SettingResource):
                current: SettingResource | ExtensionResource | FileResource = (
                    capture_setting(
                        self.settings_backend,
                        record.before.schema,
                        record.before.key,
                    )
                )
            elif isinstance(record.before, FileResource):
                current = capture_file(record.before.path)
            else:
                current = ExtensionResource(
                    self.extension_id,
                    self.extension_backend.enabled(self.extension_id),
                )
            if isinstance(current, FileResource):
                matches = current.fingerprint in {
                    record.before.fingerprint,
                    record.applied.fingerprint,
                }
            else:
                matches = current in {record.before, record.applied}
            if not matches:
                conflicts.append(record.resource)
        return conflicts

    def _theme_links(self, context: ThemeContext) -> dict[Path, Path]:
        if context.theme_root is None:
            raise ValueError("GNOME adapter requires a rendered theme root")
        theme_home = context.home / ".themes" / THEME_NAME
        return {
            theme_home / "gnome-shell/gnome-shell.css": (
                context.theme_root / "gnome-shell.css"
            ),
            theme_home / "gtk-3.0/gtk.css": (context.theme_root / "gtk-3.0.css"),
        }

    def _restore_extension(self, record: ResourceRecord) -> AdapterResult:
        current = ExtensionResource(
            self.extension_id,
            self.extension_backend.enabled(self.extension_id),
        )
        if current == record.before:
            return AdapterResult("unchanged")
        if current != record.applied:
            return AdapterResult("conflicted", (record.resource,))
        if record.before.enabled:
            self.extension_backend.enable(self.extension_id)
        else:
            self.extension_backend.disable(self.extension_id)
        return AdapterResult("restored")

    def _desired_settings(self, context: ThemeContext) -> dict[tuple[str, str], str]:
        wallpaper_uri = self._wallpaper_uri(context)
        defaults = {
            (INTERFACE, "color-scheme"): "'prefer-dark'",
            (INTERFACE, "accent-color"): "'blue'",
            (INTERFACE, "gtk-theme"): f"'{THEME_NAME}'",
            (INTERFACE, "icon-theme"): "'Yaru-blue'",
            (INTERFACE, "cursor-theme"): "'Adwaita'",
            (USER_THEME, "name"): f"'{THEME_NAME}'",
            (BACKGROUND, "picture-uri"): f"'{wallpaper_uri}'",
            (BACKGROUND, "picture-uri-dark"): f"'{wallpaper_uri}'",
            (SCREENSAVER, "picture-uri"): f"'{wallpaper_uri}'",
        }
        defaults.update(self.values)
        return defaults

    @staticmethod
    def _wallpaper_uri(context: ThemeContext) -> str:
        configured = context.values.get("wallpaper")
        if configured is not None:
            value = str(configured)
            return value if value.startswith("file://") else Path(value).as_uri()
        if context.theme_root is None:
            raise ValueError("GNOME adapter requires a theme root or wallpaper value")
        return (context.theme_root / "wallpapers/wellness-room.png").resolve().as_uri()
