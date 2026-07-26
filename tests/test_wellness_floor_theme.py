from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "system_files/dudley/usr/lib"
sys.path.insert(0, str(LIBRARY))

from dudley_theme.catalog import (  # noqa: E402
    ThemeCatalogError,
    discover_themes,
    load_theme,
)
from dudley_theme.render import ThemeRenderError, render_theme  # noqa: E402


THEME_COMMAND = ROOT / "system_files/dudley/usr/bin/dudley-theme"
THEME = ROOT / "system_files/dudley/usr/share/dudley/themes/wellness-floor"


class WellnessFloorThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((THEME / "manifest.json").read_text(encoding="utf-8"))
        cls.colors = tomllib.loads((THEME / "colors.toml").read_text(encoding="utf-8"))

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
            '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >"${DUDLEY_WALLPAPER_LOG}"\n',
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
        self.assertEqual(2, self.manifest["schema_version"])
        self.assertEqual("wellness-floor", self.manifest["id"])
        self.assertEqual("Dudley Wellness Floor", self.manifest["name"])
        self.assertEqual("gnome", self.manifest["platform"]["desktop"])
        self.assertEqual(["bluefin", "ubuntu"], self.manifest["platform"]["profiles"])

    def test_catalog_requires_colors_and_provenance(self) -> None:
        with self.subTest(field="schema_version"):
            self.assertEqual(2, self.manifest["schema_version"])
        with self.subTest(field="colors"):
            self.assertEqual("colors.toml", self.manifest.get("colors"))
        with self.subTest(file="provenance.json"):
            self.assertTrue((THEME / "provenance.json").is_file())

    def test_manifest_assets_exist(self) -> None:
        for relative_path in [
            self.manifest["colors"],
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

    def test_colors_have_required_tokens(self) -> None:
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
                self.assertIn(key, self.colors)

    def test_catalog_loads_normalized_theme_with_wallpaper_generation_metadata(
        self,
    ) -> None:
        theme = load_theme(THEME)

        self.assertEqual("wellness-floor", theme.id)
        self.assertEqual(
            {
                "btop",
                "ghostty",
                "gnome",
                "kitty",
                "neovim",
                "vscode",
            },
            set(theme.required_adapters),
        )
        wallpaper = theme.provenance["wallpapers/wellness-room.png"]
        self.assertEqual("gpt-image", wallpaper.generation["software"])
        self.assertEqual("2.0", wallpaper.generation["version"])
        self.assertEqual(
            "trainedAlgorithmicMedia",
            wallpaper.generation["digital_source_type"],
        )

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
            (self.home / ".config/kitty/kitty.conf")
            .read_text(encoding="utf-8")
            .splitlines()
            .count("include dudley-theme.conf"),
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


class CatalogRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def create_theme(self, directory_name: str = "test-theme") -> Path:
        theme = self.root / directory_name
        (theme / "templates").mkdir(parents=True)
        (theme / "wallpapers").mkdir()
        files = {
            "colors.toml": b'background = "#16242d"\nforeground = "#d6e2ee"\n',
            "templates/app.conf": b"background = {{ background }}\n",
            "wallpapers/wall.png": b"test wallpaper bytes\n",
        }
        for relative_path, data in files.items():
            (theme / relative_path).write_bytes(data)

        records = {}
        for relative_path, data in files.items():
            digest = hashlib.sha256(data).hexdigest()
            records[relative_path] = {
                "source": "Dudley project test fixture",
                "author": "Dudley project",
                "license": "MIT",
                "original_sha256": digest,
                "shipped_sha256": digest,
                "modification_status": "project-work",
                "required_attribution": "None",
            }
        provenance = {
            "schema_version": 1,
            "theme_id": "test-theme",
            "records": records,
        }
        manifest = {
            "schema_version": 2,
            "id": "test-theme",
            "name": "Test Theme",
            "version": "1.0.0",
            "colors": "colors.toml",
            "provenance": "provenance.json",
            "fidelity_profiles": {
                "standard": {
                    "required_adapters": ["kitty"],
                    "optional_adapters": [],
                }
            },
            "render": {
                "version": 1,
                "outputs": [
                    {
                        "path": "app.conf",
                        "source": "templates/app.conf",
                    }
                ],
            },
            "assets": {
                "wallpapers": ["wallpapers/wall.png"],
                "default_wallpaper": "wallpapers/wall.png",
            },
        }
        (theme / "provenance.json").write_text(
            json.dumps(provenance, indent=2) + "\n",
            encoding="utf-8",
        )
        (theme / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        return theme

    def read_json(self, path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, indent=2) + "\n",
            encoding="utf-8",
        )

    def update_provenance_hash(self, theme: Path, relative_path: str) -> None:
        provenance_path = theme / "provenance.json"
        provenance = self.read_json(provenance_path)
        record = provenance["records"][relative_path]
        digest = hashlib.sha256((theme / relative_path).read_bytes()).hexdigest()
        record["original_sha256"] = digest
        record["shipped_sha256"] = digest
        self.write_json(provenance_path, provenance)

    def test_discover_themes_returns_validated_catalog(self) -> None:
        theme_path = self.create_theme()

        themes = discover_themes(self.root)

        self.assertEqual(["test-theme"], list(themes))
        self.assertEqual(theme_path, themes["test-theme"].root)

    def test_catalog_rejects_missing_declared_file(self) -> None:
        theme_path = self.create_theme()
        (theme_path / "templates/app.conf").unlink()

        with self.assertRaisesRegex(
            ThemeCatalogError,
            "missing declared file.*templates/app.conf",
        ):
            load_theme(theme_path)

    def test_catalog_rejects_duplicate_palette_and_colors_files(self) -> None:
        theme_path = self.create_theme()
        (theme_path / "palette.toml").write_bytes(
            (theme_path / "colors.toml").read_bytes()
        )

        with self.assertRaisesRegex(
            ThemeCatalogError,
            "both palette.toml and colors.toml",
        ):
            load_theme(theme_path)

    def test_catalog_rejects_unknown_required_adapter(self) -> None:
        theme_path = self.create_theme()
        manifest_path = theme_path / "manifest.json"
        manifest = self.read_json(manifest_path)
        manifest["fidelity_profiles"]["standard"]["required_adapters"] = [
            "unknown-surface"
        ]
        self.write_json(manifest_path, manifest)

        with self.assertRaisesRegex(
            ThemeCatalogError,
            "unknown required adapter.*unknown-surface",
        ):
            load_theme(theme_path)

    def test_catalog_rejects_asset_without_provenance(self) -> None:
        theme_path = self.create_theme()
        provenance_path = theme_path / "provenance.json"
        provenance = self.read_json(provenance_path)
        del provenance["records"]["wallpapers/wall.png"]
        self.write_json(provenance_path, provenance)

        with self.assertRaisesRegex(
            ThemeCatalogError,
            "missing provenance.*wallpapers/wall.png",
        ):
            load_theme(theme_path)

    def test_catalog_rejects_shipped_hash_mismatch(self) -> None:
        theme_path = self.create_theme()
        provenance_path = theme_path / "provenance.json"
        provenance = self.read_json(provenance_path)
        provenance["records"]["colors.toml"]["shipped_sha256"] = "0" * 64
        self.write_json(provenance_path, provenance)

        with self.assertRaisesRegex(
            ThemeCatalogError,
            "shipped hash mismatch.*colors.toml",
        ):
            load_theme(theme_path)

    def test_catalog_rejects_output_path_traversal(self) -> None:
        theme_path = self.create_theme()
        manifest_path = theme_path / "manifest.json"
        manifest = self.read_json(manifest_path)
        manifest["render"]["outputs"][0]["path"] = "../escape.conf"
        self.write_json(manifest_path, manifest)

        with self.assertRaisesRegex(
            ThemeCatalogError,
            "unsafe render output path",
        ):
            load_theme(theme_path)

    def test_renderer_is_deterministic_and_hashes_every_output(self) -> None:
        theme = load_theme(self.create_theme())
        first_destination = self.root / "first"
        second_destination = self.root / "second"

        first = render_theme(theme, first_destination)
        second = render_theme(theme, second_destination)

        expected = b"background = #16242d\n"
        self.assertEqual(expected, (first_destination / "app.conf").read_bytes())
        self.assertEqual(expected, (second_destination / "app.conf").read_bytes())
        self.assertEqual(
            {
                "app.conf": (
                    "0090cfdff713015d82a1b060e7deab4cdd55595d8bd8d0e3097973f43182ebcf"
                )
            },
            first.hashes,
        )
        self.assertEqual(first.hashes, second.hashes)

    def test_renderer_rejects_unresolved_placeholder_without_partial_output(
        self,
    ) -> None:
        theme_path = self.create_theme()
        (theme_path / "templates/app.conf").write_text(
            "background = {{ missing }}\n",
            encoding="utf-8",
        )
        self.update_provenance_hash(theme_path, "templates/app.conf")
        theme = load_theme(theme_path)
        destination = self.root / "rendered"

        with self.assertRaisesRegex(
            ThemeRenderError,
            "unresolved template token.*missing",
        ):
            render_theme(theme, destination)

        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
