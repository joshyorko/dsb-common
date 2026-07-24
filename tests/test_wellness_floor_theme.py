from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = (
    ROOT
    / "system_files/dudley/usr/share/dudley/themes/wellness-floor"
)


class WellnessFloorThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(
            (THEME / "manifest.json").read_text(encoding="utf-8")
        )
        cls.palette = tomllib.loads(
            (THEME / "palette.toml").read_text(encoding="utf-8")
        )

    def test_manifest_required_fields(self) -> None:
        self.assertEqual(1, self.manifest["schema_version"])
        self.assertEqual("wellness-floor", self.manifest["id"])
        self.assertEqual("Dudley Wellness Floor", self.manifest["name"])
        self.assertEqual("gnome", self.manifest["platform"]["desktop"])
        self.assertEqual(["bluefin", "ubuntu"], self.manifest["platform"]["profiles"])

    def test_manifest_assets_exist(self) -> None:
        for relative_path in [
            self.manifest["palette"],
            self.manifest["gnome"]["dconf"],
            self.manifest["assets"]["kitty"],
            self.manifest["assets"]["ghostty"],
            self.manifest["assets"]["vscode"],
            self.manifest["assets"]["neovim"],
            self.manifest["assets"]["btop"],
            *self.manifest["assets"]["wallpapers"],
        ]:
            with self.subTest(path=relative_path):
                self.assertTrue((THEME / relative_path).is_file())

    def test_default_wallpaper_is_declared(self) -> None:
        self.assertIn(
            self.manifest["assets"]["default_wallpaper"],
            self.manifest["assets"]["wallpapers"],
        )

    def test_palette_has_required_tokens(self) -> None:
        for key in [
            "background",
            "foreground",
            "accent",
            "selection_background",
            "selection_foreground",
            "color0",
            "color15",
        ]:
            with self.subTest(key=key):
                self.assertIn(key, self.palette)


if __name__ == "__main__":
    unittest.main()
