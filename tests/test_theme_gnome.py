from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "system_files/dudley/usr/lib"
THEME = ROOT / "system_files/dudley/usr/share/dudley/themes/wellness-floor"
sys.path.insert(0, str(LIBRARY))

from dudley_theme.adapters.base import ThemeContext  # noqa: E402
from dudley_theme.adapters.gsettings import SettingResource  # noqa: E402
from dudley_theme.catalog import load_theme  # noqa: E402
from dudley_theme.render import render_theme  # noqa: E402


class FakeSettingsBackend:
    def __init__(self, values: dict[tuple[str, str], str | None]) -> None:
        self.values = dict(values)

    def read(self, schema: str, key: str) -> str | None:
        return self.values[(schema, key)]

    def write(self, schema: str, key: str, value: str) -> None:
        self.values[(schema, key)] = value

    def reset(self, schema: str, key: str) -> None:
        self.values[(schema, key)] = None


class FakeExtensionBackend:
    def __init__(self, enabled: bool) -> None:
        self.is_enabled = enabled

    def enabled(self, extension_id: str) -> bool:
        del extension_id
        return self.is_enabled

    def enable(self, extension_id: str) -> None:
        del extension_id
        self.is_enabled = True

    def disable(self, extension_id: str) -> None:
        del extension_id
        self.is_enabled = False


class GnomeThemeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.rendered = self.root / "rendered"
        self.home.mkdir()
        render_theme(load_theme(THEME), self.rendered)
        self.context = ThemeContext(
            home=self.home,
            theme_root=self.rendered,
            values={
                "wallpaper": str((THEME / "wallpapers/wellness-room.png").resolve())
            },
        )

    def test_rendered_shell_and_gtk_css_cover_owned_gnome_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            rendered = render_theme(load_theme(THEME), destination)

            shell = (destination / "gnome-shell.css").read_text(encoding="utf-8")
            gtk = (destination / "gtk-3.0.css").read_text(encoding="utf-8")

        self.assertEqual(
            {"gnome-shell.css", "gtk-3.0.css"},
            {"gnome-shell.css", "gtk-3.0.css"} & rendered.hashes.keys(),
        )
        for selector in (
            "#panel",
            "#overview",
            ".quick-settings",
            ".notification-banner",
            ".modal-dialog",
            ".osd-window",
            ".workspace-indicator",
            ".screen-shield",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, shell)
        self.assertIn("button", gtk)
        self.assertIn("entry", gtk)
        self.assertNotIn("{{", shell + gtk)

    def test_apply_verify_and_restore_preserve_typed_and_unset_state(self) -> None:
        try:
            from dudley_theme.adapters.gnome import GnomeAdapter
        except ImportError as error:
            self.fail(f"GNOME adapter is missing: {error}")

        adapter_probe = GnomeAdapter()
        baseline = {
            setting: (None if index % 2 == 0 else "'Baseline'")
            for index, setting in enumerate(adapter_probe.settings)
        }
        settings = FakeSettingsBackend(baseline)
        extensions = FakeExtensionBackend(False)
        adapter = GnomeAdapter(
            settings_backend=settings,
            extension_backend=extensions,
        )
        records = adapter.capture(self.context)
        result = adapter.apply(self.context, records)

        self.assertEqual("applied", result.status)
        self.assertTrue(extensions.is_enabled)
        self.assertEqual("verified", adapter.verify(self.context).status)
        self.assertEqual(
            "'Yaru-blue'",
            settings.values[("org.gnome.desktop.interface", "icon-theme")],
        )
        self.assertEqual(
            "'Adwaita'",
            settings.values[("org.gnome.desktop.interface", "cursor-theme")],
        )
        wallpaper = (THEME / "wallpapers/wellness-room.png").resolve().as_uri()
        self.assertEqual(
            {f"'{wallpaper}'"},
            {
                settings.values[("org.gnome.desktop.background", "picture-uri")],
                settings.values[("org.gnome.desktop.background", "picture-uri-dark")],
                settings.values[("org.gnome.desktop.screensaver", "picture-uri")],
            },
        )
        setting_records = [
            record for record in records if isinstance(record.before, SettingResource)
        ]
        self.assertEqual(len(adapter.settings), len(setting_records))
        self.assertTrue(any(record.before.unset for record in setting_records))
        self.assertTrue(any(not record.before.unset for record in setting_records))

        restored = adapter.restore(self.context, records)

        self.assertEqual("restored", restored.status)
        self.assertEqual(baseline, settings.values)
        self.assertFalse(extensions.is_enabled)

    def test_verify_reports_extension_drift(self) -> None:
        try:
            from dudley_theme.adapters.gnome import GnomeAdapter
        except ImportError as error:
            self.fail(f"GNOME adapter is missing: {error}")

        adapter_probe = GnomeAdapter()
        settings = FakeSettingsBackend(
            {setting: None for setting in adapter_probe.settings}
        )
        extensions = FakeExtensionBackend(False)
        adapter = GnomeAdapter(
            settings_backend=settings,
            extension_backend=extensions,
        )
        records = adapter.capture(self.context)
        adapter.apply(self.context, records)
        extensions.is_enabled = False

        status = adapter.verify(self.context)

        self.assertEqual("drifted", status.status)
        self.assertIn(adapter.extension_id, status.details)

    def test_apply_and_restore_connect_rendered_css_to_user_theme(self) -> None:
        from dudley_theme.adapters.gnome import GnomeAdapter

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            rendered = root / "rendered"
            home.mkdir()
            render_theme(load_theme(THEME), rendered)
            adapter_probe = GnomeAdapter()
            settings = FakeSettingsBackend(
                {setting: None for setting in adapter_probe.settings}
            )
            extensions = FakeExtensionBackend(False)
            adapter = GnomeAdapter(
                settings_backend=settings,
                extension_backend=extensions,
            )
            context = ThemeContext(
                home=home,
                theme_root=rendered,
                values={
                    "wallpaper": str((THEME / "wallpapers/wellness-room.png").resolve())
                },
            )

            records = adapter.capture(context)
            applied = adapter.apply(context, records)
            shell = home / ".themes/Dudley-Wellness-Floor/gnome-shell/gnome-shell.css"
            gtk = home / ".themes/Dudley-Wellness-Floor/gtk-3.0/gtk.css"

            self.assertEqual("applied", applied.status)
            self.assertEqual(rendered / "gnome-shell.css", shell.resolve())
            self.assertEqual(rendered / "gtk-3.0.css", gtk.resolve())

            restored = adapter.restore(context, records)

            self.assertEqual("restored", restored.status)
            self.assertFalse(shell.exists())
            self.assertFalse(gtk.exists())


if __name__ == "__main__":
    unittest.main()
