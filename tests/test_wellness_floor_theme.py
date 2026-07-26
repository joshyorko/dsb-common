from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME_COMMAND = ROOT / "system_files/dudley/usr/bin/dudley-theme"
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

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.test_root = Path(self.temp_dir.name)
        self.home = self.test_root / "home"
        self.fake_bin = self.test_root / "bin"
        self.wallpaper_log = self.test_root / "wallpaper.log"
        self.home.mkdir()
        self.fake_bin.mkdir()

        fake_dconf = self.fake_bin / "dconf"
        fake_dconf.write_text(
            "#!/usr/bin/env bash\ncat >/dev/null\n",
            encoding="utf-8",
        )
        fake_dconf.chmod(0o755)

        self.fake_wallpaper = self.fake_bin / "dudley-wallpaper"
        self.fake_wallpaper.write_text(
            "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >\"${DUDLEY_WALLPAPER_LOG}\"\n",
            encoding="utf-8",
        )
        self.fake_wallpaper.chmod(0o755)

        self.env = os.environ.copy()
        self.env.update(
            {
                "DUDLEY_THEMES_DIR": str(THEME.parent),
                "DUDLEY_WALLPAPER_BIN": str(self.fake_wallpaper),
                "DUDLEY_WALLPAPER_LOG": str(self.wallpaper_log),
                "HOME": str(self.home),
                "PATH": f"{self.fake_bin}:/usr/bin:/bin",
            }
        )

    def apply_theme(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(THEME_COMMAND), "apply", "wellness-floor"],
            cwd=ROOT,
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        )

    def reset_theme(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(THEME_COMMAND), "reset"],
            cwd=ROOT,
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
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

    def test_apply_supports_portable_wallpaper_command_override(self) -> None:
        self.apply_theme()

        self.assertEqual(
            "set wellness-floor/wellness-room.png",
            self.wallpaper_log.read_text(encoding="utf-8").strip(),
        )

    def test_apply_preserves_and_updates_vscode_jsonc(self) -> None:
        settings = self.home / ".config/Code - Insiders/User/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            """{
  // Keep this user comment.
  "editor.fontSize": 15,
  "workbench.colorCustomizations": {
    // Keep this nested comment.
    "editor.background": "#000000",
    "dudley.test": "#abcdef",
  },
}
""",
            encoding="utf-8",
        )

        self.apply_theme()

        updated_text = settings.read_text(encoding="utf-8")
        self.assertIn("// Keep this user comment.", updated_text)
        self.assertIn("// Keep this nested comment.", updated_text)
        json_text = re.sub(r"//[^\n]*", "", updated_text)
        json_text = re.sub(r",(\s*[}\]])", r"\1", json_text)
        updated = json.loads(json_text)
        self.assertEqual(15, updated["editor.fontSize"])
        self.assertEqual(
            "#16242d",
            updated["workbench.colorCustomizations"]["editor.background"],
        )
        self.assertEqual(
            "#abcdef",
            updated["workbench.colorCustomizations"]["dudley.test"],
        )

    def test_apply_connects_generated_assets_to_each_application(self) -> None:
        self.apply_theme()

        config = self.home / ".config"
        generated = config / "dudley/generated"
        self.assertEqual(
            (generated / "kitty.conf").read_text(encoding="utf-8"),
            (config / "kitty/dudley-theme.conf").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "include dudley-theme.conf",
            (config / "kitty/kitty.conf").read_text(encoding="utf-8").splitlines(),
        )
        self.assertEqual(
            (generated / "ghostty.theme").read_text(encoding="utf-8"),
            (config / "ghostty/themes/dudley-theme").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "theme = dudley-theme",
            (config / "ghostty/config").read_text(encoding="utf-8").splitlines(),
        )
        self.assertEqual(
            (generated / "neovim.lua").read_text(encoding="utf-8"),
            (config / "nvim/plugin/dudley-theme.lua").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            (generated / "btop.theme").read_text(encoding="utf-8"),
            (config / "btop/themes/dudley-theme.theme").read_text(encoding="utf-8"),
        )
        self.assertIn(
            'color_theme = "dudley-theme"',
            (config / "btop/btop.conf").read_text(encoding="utf-8").splitlines(),
        )

    def test_apply_reapplies_when_receipt_theme_version_is_stale(self) -> None:
        self.apply_theme()
        receipt_path = self.home / ".config/dudley/theme-receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["theme_version"] = "0.0.0"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        generated_kitty = self.home / ".config/dudley/generated/kitty.conf"
        generated_kitty.write_text("stale\n", encoding="utf-8")

        result = self.apply_theme()

        self.assertIn("Applied wellness-floor", result.stdout)
        self.assertEqual(
            (THEME / self.manifest["assets"]["kitty"]).read_text(encoding="utf-8"),
            generated_kitty.read_text(encoding="utf-8"),
        )
        self.assertEqual(
            1,
            (
                self.home / ".config/kitty/kitty.conf"
            ).read_text(encoding="utf-8").splitlines().count(
                "include dudley-theme.conf"
            ),
        )

    def test_reset_disconnects_managed_application_assets(self) -> None:
        self.apply_theme()

        self.reset_theme()

        config = self.home / ".config"
        for managed_path in [
            config / "kitty/dudley-theme.conf",
            config / "ghostty/themes/dudley-theme",
            config / "nvim/plugin/dudley-theme.lua",
            config / "btop/themes/dudley-theme.theme",
        ]:
            with self.subTest(path=managed_path):
                self.assertFalse(managed_path.exists())
                self.assertFalse(managed_path.is_symlink())
        self.assertNotIn(
            "include dudley-theme.conf",
            (config / "kitty/kitty.conf").read_text(encoding="utf-8").splitlines(),
        )
        self.assertNotIn(
            "theme = dudley-theme",
            (config / "ghostty/config").read_text(encoding="utf-8").splitlines(),
        )
        self.assertNotIn(
            'color_theme = "dudley-theme"',
            (config / "btop/btop.conf").read_text(encoding="utf-8").splitlines(),
        )


if __name__ == "__main__":
    unittest.main()
