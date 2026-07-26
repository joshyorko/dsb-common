from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "system_files/dudley/usr/lib"
sys.path.insert(0, str(LIBRARY))

from dudley_theme.adapters.files import (  # noqa: E402
    capture_file,
    capture_line,
    restore_file,
    restore_line,
    write_managed_file,
    write_managed_line,
    write_managed_link,
)
from dudley_theme.adapters.base import ThemeContext  # noqa: E402


class MemorySettingsBackend:
    def __init__(self, values: dict[tuple[str, str], str] | None = None) -> None:
        self.values = dict(values or {})

    def read(self, schema: str, key: str) -> str | None:
        return self.values.get((schema, key))

    def write(self, schema: str, key: str, value: str) -> None:
        self.values[(schema, key)] = value

    def reset(self, schema: str, key: str) -> None:
        self.values.pop((schema, key), None)


class CanonicalizingSettingsBackend(MemorySettingsBackend):
    def write(self, schema: str, key: str, value: str) -> None:
        canonical = "[]" if value == "@as []" else value
        super().write(schema, key, canonical)


def load_gsettings_api() -> tuple[Any, ...]:
    try:
        from dudley_theme.adapters.gsettings import (
            GSettingsAdapter,
            capture_setting,
            restore_setting,
            write_managed_setting,
        )
    except ImportError as error:
        raise AssertionError("typed gsettings adapter is missing") from error
    return GSettingsAdapter, capture_setting, restore_setting, write_managed_setting


def load_app_api() -> tuple[Any, ...]:
    try:
        from dudley_theme.adapters.apps import (
            BtopAdapter,
            GhosttyAdapter,
            KittyAdapter,
            NeovimAdapter,
            VSCodeAdapter,
            capture_jsonc_value,
            restore_jsonc_value,
            write_jsonc_value,
        )
    except ModuleNotFoundError as error:
        raise AssertionError("curated application adapters are missing") from error
    return (
        BtopAdapter,
        GhosttyAdapter,
        KittyAdapter,
        NeovimAdapter,
        VSCodeAdapter,
        capture_jsonc_value,
        restore_jsonc_value,
        write_jsonc_value,
    )


class FileResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def test_restore_preserves_user_edit(self) -> None:
        target = self.root / "settings"
        target.write_text("before", encoding="utf-8")
        record = capture_file(target)
        applied = write_managed_file(target, b"applied")
        target.write_text("user edit", encoding="utf-8")

        result = restore_file(record, expected=applied)

        self.assertEqual("conflicted", result.status)
        self.assertEqual("user edit", target.read_text(encoding="utf-8"))

    def test_restore_recreates_preexisting_symlink(self) -> None:
        target = self.root / "settings"
        target.symlink_to("original.conf")
        record = capture_file(target)
        applied = write_managed_file(target, b"applied")

        result = restore_file(record, expected=applied)

        self.assertEqual("restored", result.status)
        self.assertTrue(target.is_symlink())
        self.assertEqual("original.conf", os.readlink(target))

    def test_restore_removes_managed_symlink_from_absent_path(self) -> None:
        target = self.root / "theme.conf"
        record = capture_file(target)
        applied = write_managed_link(target, "themes/wellness.conf")

        result = restore_file(record, expected=applied)

        self.assertEqual("restored", result.status)
        self.assertFalse(target.exists())
        self.assertFalse(target.is_symlink())

    def test_preexisting_include_is_not_owned_or_removed(self) -> None:
        target = self.root / "kitty.conf"
        target.write_bytes(b"font_size 12\ninclude dudley-theme.conf\n")
        record = capture_line(target, b"include dudley-theme.conf")

        applied = write_managed_line(record)
        result = restore_line(record, expected=applied)

        self.assertEqual("unchanged", result.status)
        self.assertEqual(
            b"font_size 12\ninclude dudley-theme.conf\n", target.read_bytes()
        )

    def test_owned_include_restores_original_file_exactly(self) -> None:
        target = self.root / "kitty.conf"
        target.write_bytes(b"font_size 12\n")
        record = capture_line(target, b"include dudley-theme.conf")
        applied = write_managed_line(record)

        result = restore_line(record, expected=applied)

        self.assertEqual("restored", result.status)
        self.assertEqual(b"font_size 12\n", target.read_bytes())


class SettingResourceTests(unittest.TestCase):
    def test_restore_resets_setting_that_was_initially_unset(self) -> None:
        _, capture_setting, restore_setting, write_managed_setting = (
            load_gsettings_api()
        )
        backend = MemorySettingsBackend()
        record = capture_setting(backend, "org.gnome.desktop.interface", "color-scheme")

        applied = write_managed_setting(record, "'prefer-dark'", backend)
        result = restore_setting(record, expected=applied, backend=backend)

        self.assertEqual("restored", result.status)
        self.assertIsNone(backend.read("org.gnome.desktop.interface", "color-scheme"))

    def test_restore_preserves_typed_setting_user_edit(self) -> None:
        _, capture_setting, restore_setting, write_managed_setting = (
            load_gsettings_api()
        )
        backend = MemorySettingsBackend(
            {("org.gnome.desktop.interface", "accent-color"): "'red'"}
        )
        record = capture_setting(backend, "org.gnome.desktop.interface", "accent-color")

        applied = write_managed_setting(record, "'blue'", backend)
        backend.write("org.gnome.desktop.interface", "accent-color", "'slate'")
        result = restore_setting(record, expected=applied, backend=backend)

        self.assertEqual("conflicted", result.status)
        self.assertEqual(
            "'slate'",
            backend.read("org.gnome.desktop.interface", "accent-color"),
        )

    def test_gsettings_adapter_implements_transaction_contract(self) -> None:
        GSettingsAdapter, _, _, _ = load_gsettings_api()
        backend = MemorySettingsBackend()
        adapter = GSettingsAdapter(
            {
                ("org.gnome.desktop.interface", "color-scheme"): "'prefer-dark'",
                ("org.gnome.desktop.interface", "accent-color"): "'blue'",
            },
            backend=backend,
        )
        context = ThemeContext(home=Path("/unused"))
        records = adapter.capture(context)

        applied = adapter.apply(context, records)
        verified = adapter.verify(context)
        restored = adapter.restore(context, records)

        self.assertEqual("applied", applied.status)
        self.assertEqual("verified", verified.status)
        self.assertEqual("restored", restored.status)
        self.assertEqual(2, len(records))
        self.assertEqual({}, backend.values)

    def test_gsettings_adapter_records_canonical_post_write_value(self) -> None:
        GSettingsAdapter, _, _, _ = load_gsettings_api()
        backend = CanonicalizingSettingsBackend()
        adapter = GSettingsAdapter(
            {("org.example.theme", "palette"): "@as []"},
            backend=backend,
        )
        context = ThemeContext(home=Path("/unused"))
        records = adapter.capture(context)

        adapter.apply(context, records)

        self.assertEqual("[]", records[0].applied.value)
        self.assertEqual("verified", adapter.verify(context).status)
        self.assertEqual("restored", adapter.restore(context, records).status)
        self.assertEqual({}, backend.values)


class JsoncResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def test_restore_updates_each_vscode_key_independently(self) -> None:
        (
            _,
            _,
            _,
            _,
            _,
            capture_jsonc_value,
            restore_jsonc_value,
            write_jsonc_value,
        ) = load_app_api()
        target = self.root / "settings.json"
        target.write_text(
            """{
  // Keep this user comment.
  "workbench.colorCustomizations": {
    // Keep this nested comment.
    "editor.background": "#000000",
    "dudley.user": "#abcdef",
  },
}
""",
            encoding="utf-8",
        )
        background = capture_jsonc_value(
            target, ("workbench.colorCustomizations", "editor.background")
        )
        foreground = capture_jsonc_value(
            target, ("workbench.colorCustomizations", "editor.foreground")
        )

        applied_background = write_jsonc_value(background, "#16242d")
        applied_foreground = write_jsonc_value(foreground, "#f4ead7")
        write_jsonc_value(
            capture_jsonc_value(
                target, ("workbench.colorCustomizations", "editor.background")
            ),
            "#112233",
        )
        background_result = restore_jsonc_value(background, expected=applied_background)
        foreground_result = restore_jsonc_value(foreground, expected=applied_foreground)

        updated = target.read_text(encoding="utf-8")
        self.assertEqual("conflicted", background_result.status)
        self.assertEqual("restored", foreground_result.status)
        self.assertIn('"editor.background": "#112233"', updated)
        self.assertNotIn('"editor.foreground"', updated)
        self.assertIn('"dudley.user": "#abcdef"', updated)
        self.assertIn("// Keep this user comment.", updated)
        self.assertIn("// Keep this nested comment.", updated)

    def test_capture_accepts_comments_and_trailing_commas_inside_values(self) -> None:
        (
            _,
            _,
            _,
            _,
            _,
            capture_jsonc_value,
            _,
            _,
        ) = load_app_api()
        target = self.root / "settings.json"
        target.write_text(
            """{
  "editor.rulers": [
    80,
    // Keep this ruler comment.
    100,
  ],
}
""",
            encoding="utf-8",
        )

        try:
            record = capture_jsonc_value(target, ("editor.rulers",))
        except ValueError as error:
            self.fail(f"valid JSONC value was rejected: {error}")

        self.assertEqual([80, 100], record.value)

    def test_restore_new_last_member_preserves_original_bytes(self) -> None:
        (
            _,
            _,
            _,
            _,
            _,
            capture_jsonc_value,
            restore_jsonc_value,
            write_jsonc_value,
        ) = load_app_api()
        target = self.root / "settings.json"
        original = b"""{
  "editor.fontSize": 15,
  // Preserve this trailing-comma comment exactly.
}
"""
        target.write_bytes(original)
        record = capture_jsonc_value(target, ("workbench.colorTheme",))

        applied = write_jsonc_value(record, "Dudley Wellness Floor")
        result = restore_jsonc_value(record, expected=applied)

        self.assertEqual("restored", result.status)
        self.assertEqual(original, target.read_bytes())


class CuratedAppAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.home = Path(self.temporary_directory.name)

    def test_native_app_adapters_use_owned_links_and_includes(self) -> None:
        (
            BtopAdapter,
            GhosttyAdapter,
            KittyAdapter,
            NeovimAdapter,
            _,
            _,
            _,
            _,
        ) = load_app_api()
        cases = [
            (
                KittyAdapter,
                "kitty",
                ".config/kitty/dudley-theme.conf",
                ".config/kitty/kitty.conf",
                b"include dudley-theme.conf",
            ),
            (
                GhosttyAdapter,
                "ghostty",
                ".config/ghostty/themes/dudley-theme",
                ".config/ghostty/config",
                b"theme = dudley-theme",
            ),
            (
                NeovimAdapter,
                "neovim",
                ".config/nvim/plugin/dudley-theme.lua",
                None,
                None,
            ),
            (
                BtopAdapter,
                "btop",
                ".config/btop/themes/dudley-theme.theme",
                ".config/btop/btop.conf",
                b'color_theme = "dudley-theme"',
            ),
        ]
        for adapter_type, key, link_path, include_path, include_line in cases:
            with self.subTest(adapter=adapter_type.__name__):
                target = f".config/dudley/generated/{key}"
                context = ThemeContext(home=self.home, values={key: target})
                adapter = adapter_type()
                records = adapter.capture(context)

                result = adapter.apply(context, records)

                link = self.home / link_path
                self.assertEqual("applied", result.status)
                self.assertTrue(link.is_symlink())
                self.assertEqual(target, os.readlink(link))
                if include_path is not None:
                    self.assertIn(
                        include_line,
                        (self.home / include_path).read_bytes().splitlines(),
                    )

                restore = adapter.restore(context, records)
                self.assertEqual("restored", restore.status)
                self.assertFalse(link.exists())
                self.assertFalse(link.is_symlink())

    def test_vscode_adapter_covers_stable_and_insiders_native_paths(self) -> None:
        *_, VSCodeAdapter, _, _, _ = load_app_api()
        paths = [
            self.home / ".config/Code/User/settings.json",
            self.home / ".config/Code - Insiders/User/settings.json",
        ]
        for path in paths:
            path.parent.mkdir(parents=True)
            path.write_text('{\n  "editor.fontSize": 15,\n}\n', encoding="utf-8")
        context = ThemeContext(
            home=self.home,
            values={
                "vscode": {
                    "workbench.colorTheme": "Dudley Wellness Floor",
                    "workbench.colorCustomizations": {"editor.background": "#16242d"},
                }
            },
        )
        adapter = VSCodeAdapter()
        records = adapter.capture(context)

        result = adapter.apply(context, records)

        self.assertEqual("applied", result.status)
        self.assertEqual(4, len(records))
        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertIn('"editor.fontSize": 15', text)
            self.assertIn('"workbench.colorTheme": "Dudley Wellness Floor"', text)
            self.assertIn('"editor.background": "#16242d"', text)

    def test_vscode_adapter_creates_and_restores_absent_settings_files(self) -> None:
        *_, VSCodeAdapter, _, _, _ = load_app_api()
        paths = [
            self.home / ".config/Code/User/settings.json",
            self.home / ".config/Code - Insiders/User/settings.json",
        ]
        context = ThemeContext(
            home=self.home,
            values={"vscode": {"workbench.colorTheme": "Dudley Wellness Floor"}},
        )
        adapter = VSCodeAdapter()
        records = adapter.capture(context)

        applied = adapter.apply(context, records)
        restored = adapter.restore(context, records)

        self.assertEqual("applied", applied.status)
        self.assertEqual("restored", restored.status)
        self.assertEqual(2, len(records))
        self.assertTrue(all(not record.before.file_existed for record in records))
        for path in paths:
            self.assertFalse(path.exists())

    def test_vscode_adapter_conflicts_if_absent_settings_file_appears(self) -> None:
        *_, VSCodeAdapter, _, _, _ = load_app_api()
        context = ThemeContext(
            home=self.home,
            values={"vscode": {"workbench.colorTheme": "Dudley Wellness Floor"}},
        )
        adapter = VSCodeAdapter()
        records = adapter.capture(context)
        stable = self.home / ".config/Code/User/settings.json"
        stable.parent.mkdir(parents=True)
        original = b'{\n  "editor.fontSize": 16,\n}\n'
        stable.write_bytes(original)

        result = adapter.apply(context, records)

        self.assertEqual("conflicted", result.status)
        self.assertEqual(original, stable.read_bytes())


if __name__ == "__main__":
    unittest.main()
