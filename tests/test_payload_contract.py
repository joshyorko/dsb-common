from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contract" / "dudley-payload.v1.json"
INSTALLER = ROOT / "scripts" / "install-payload.py"
SYSTEM_FILES = ROOT / "system_files"
DUDLEY_SYSTEM_FILES = SYSTEM_FILES / "dudley"
WALLPAPER_DIR = DUDLEY_SYSTEM_FILES / "usr/share/backgrounds/dudley"
WALLPAPER_CATALOG = (
    DUDLEY_SYSTEM_FILES / "usr/share/gnome-background-properties/dudley.xml"
)
FIRST_NEW_WALLPAPER = WALLPAPER_DIR / "dudley-os-clever-girl-golden-bedroom.png"
SECOND_NEW_WALLPAPER = WALLPAPER_DIR / "dudley-os-clever-girl-golden-study.png"
HOMEBREW_DIR = DUDLEY_SYSTEM_FILES / "usr/share/ublue-os/homebrew"
HOMEBREW_PROFILES = DUDLEY_SYSTEM_FILES / "usr/share/dudley/homebrew-profiles.json"


def brewfile_entries(path: Path, directive: str) -> set[str]:
    prefix = f'{directive} "'
    return {
        line.strip()[len(prefix) : -1]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(prefix) and line.strip().endswith('"')
    }


class PayloadContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.files = cls.contract["files"]

    def test_every_system_file_is_listed_once(self) -> None:
        actual = {
            str(path.relative_to(ROOT))
            for path in SYSTEM_FILES.rglob("*")
            if path.is_file()
        }
        declared_sources = [entry["source"] for entry in self.files]
        declared = set(declared_sources)
        duplicates = sorted(
            source for source in declared if declared_sources.count(source) > 1
        )

        self.assertEqual([], duplicates)
        self.assertEqual(len(declared_sources), len(declared))
        self.assertEqual(actual, declared)

    def test_declared_files_exist_and_have_valid_selectors(self) -> None:
        valid_selectors = {
            "portable",
            "bluefin",
            "fedora-family",
            "ubuntu",
            "gnome",
            "runtime-user",
            "build-only",
        }

        for entry in self.files:
            with self.subTest(source=entry["source"]):
                self.assertTrue((ROOT / entry["source"]).is_file())
                self.assertTrue(entry["target"].startswith("/"))
                self.assertIn(entry["kind"], {"file", "executable", "image", "config", "manifest"})
                selectors = set(entry["selectors"])
                self.assertTrue(selectors)
                self.assertLessEqual(selectors, valid_selectors)

    def test_fedora_only_payload_is_not_portable(self) -> None:
        chrome_repo = next(
            entry
            for entry in self.files
            if entry["source"].endswith("/etc/yum.repos.d/google-chrome.repo")
        )

        self.assertIn("fedora-family", chrome_repo["selectors"])
        self.assertIn("bluefin", chrome_repo["selectors"])
        self.assertNotIn("portable", chrome_repo["selectors"])
        self.assertNotIn("ubuntu", chrome_repo["selectors"])

    def test_dudley_homebrew_profiles_are_curated(self) -> None:
        brewfiles = {path.name for path in HOMEBREW_DIR.glob("*.Brewfile")}
        self.assertEqual(
            {"dudley-default.Brewfile", "dudley-ai.Brewfile"}, brewfiles
        )

        default = HOMEBREW_DIR / "dudley-default.Brewfile"
        formulae = brewfile_entries(default, "brew")
        casks = brewfile_entries(default, "cask")

        self.assertLessEqual(
            {
                "brunoborges/tap/ghx",
                "rtk",
                "awscli",
                "dagger",
                "k9s",
                "kubernetes-cli",
            },
            formulae,
        )
        self.assertTrue({"gh", "kubectl", "podman", "podman-compose"}.isdisjoint(formulae))
        self.assertLessEqual(
            {
                "joshyorko/tools/action-server",
                "joshyorko/tools/devpod-linux",
                "joshyorko/tools/devsy-desktop",
                "joshyorko/tools/rcc",
                "joshyorko/tools/vscode-insiders-linux",
            },
            casks,
        )

    def test_joshyorko_tools_profiles_follow_classification_policy(self) -> None:
        default = HOMEBREW_DIR / "dudley-default.Brewfile"
        ai = HOMEBREW_DIR / "dudley-ai.Brewfile"
        default_entries = brewfile_entries(default, "brew") | brewfile_entries(default, "cask")
        ai_entries = brewfile_entries(ai, "brew") | brewfile_entries(ai, "cask")
        prefix = "joshyorko/tools/"
        default_tools = {entry.removeprefix(prefix) for entry in default_entries if entry.startswith(prefix)}
        ai_tools = {entry.removeprefix(prefix) for entry in ai_entries if entry.startswith(prefix)}
        policy = json.loads(HOMEBREW_PROFILES.read_text(encoding="utf-8"))["joshyorko_tools"]
        expected_default = set(policy["default"])
        expected_ai = set(policy["ai"])
        excluded = set(policy["manual"])

        self.assertEqual(expected_default, default_tools)
        self.assertEqual(expected_ai, ai_tools)
        self.assertTrue(default_tools.isdisjoint(ai_tools))
        self.assertTrue((default_tools | ai_tools).isdisjoint(excluded))

    def test_bluefin_install_includes_current_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            subprocess.run(
                [sys.executable, str(INSTALLER), "--profile", "bluefin", "--dest", str(dest)],
                cwd=ROOT,
                check=True,
            )

            self.assertTrue((dest / "etc/yum.repos.d/google-chrome.repo").is_file())
            self.assertTrue((dest / "usr/bin/dudley-build-info").is_file())
            self.assertTrue(
                (
                    dest
                    / "usr/share/backgrounds/dudley/dudley-os-clever-girl-golden-bedroom.png"
                ).is_file()
            )
            self.assertTrue(
                (
                    dest
                    / "usr/share/backgrounds/dudley/dudley-os-clever-girl-golden-study.png"
                ).is_file()
            )
            self.assertTrue(
                (dest / "usr/share/gnome-background-properties/dudley.xml").is_file()
            )
            self.assertTrue((dest / "usr/share/ublue-os/just/60-dudley.just").is_file())

    def test_gnome_wallpaper_catalog_covers_dudley_payload(self) -> None:
        catalog = ET.parse(WALLPAPER_CATALOG)
        self.assertEqual("wallpapers", catalog.getroot().tag)

        catalog_paths = []
        primary_paths = []
        for wallpaper in catalog.findall("wallpaper"):
            with self.subTest(name=wallpaper.findtext("name")):
                name = (wallpaper.findtext("name") or "").strip()
                filename = (wallpaper.findtext("filename") or "").strip()
                filename_dark = (wallpaper.findtext("filename-dark") or "").strip()

                self.assertTrue(name)
                self.assertEqual("false", wallpaper.get("deleted"))
                self.assertEqual("zoom", wallpaper.findtext("options"))
                for path in (filename, filename_dark):
                    self.assertTrue(
                        path.startswith("/usr/share/backgrounds/dudley/")
                    )
                    self.assertTrue(
                        (DUDLEY_SYSTEM_FILES / path.lstrip("/")).is_file()
                    )
                    catalog_paths.append(path)
                primary_paths.append(filename)

        payload_paths = {
            f"/usr/share/backgrounds/dudley/{path.name}"
            for path in WALLPAPER_DIR.iterdir()
            if path.suffix.lower() in {".jpeg", ".jpg", ".png"}
        }
        self.assertEqual(len(primary_paths), len(set(primary_paths)))
        self.assertEqual(payload_paths, set(catalog_paths))

    def test_first_new_dudley_wallpaper_has_expected_png_integrity(self) -> None:
        data = FIRST_NEW_WALLPAPER.read_bytes()

        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual((1672, 941), struct.unpack(">II", data[16:24]))
        self.assertEqual(
            "95f246c47d62156351c2d491bbd80030b8fdd96e603a38cefc9375759928c2f9",
            hashlib.sha256(data).hexdigest(),
        )

    def test_second_new_dudley_wallpaper_has_expected_png_integrity(self) -> None:
        data = SECOND_NEW_WALLPAPER.read_bytes()

        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual((1672, 941), struct.unpack(">II", data[16:24]))
        self.assertEqual(
            "66465575278841d89f2a73ca39bdd0fbb81702c78daaab66978d8c971acba9c7",
            hashlib.sha256(data).hexdigest(),
        )

    def test_ubuntu_install_excludes_fedora_only_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            subprocess.run(
                [sys.executable, str(INSTALLER), "--profile", "ubuntu", "--dest", str(dest)],
                cwd=ROOT,
                check=True,
            )

            self.assertFalse((dest / "etc/yum.repos.d/google-chrome.repo").exists())
            self.assertTrue((dest / "usr/bin/dudley-build-info").is_file())
            self.assertTrue((dest / "usr/share/backgrounds/dudley/dudleys-second-bedroom-1.png").is_file())

    def test_dry_run_does_not_write_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            result = subprocess.run(
                [
                    sys.executable,
                    str(INSTALLER),
                    "--profile",
                    "ubuntu",
                    "--dest",
                    str(dest),
                    "--dry-run",
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["profile"], "ubuntu")
            self.assertGreater(payload["selected_count"], 0)
            self.assertFalse(any(dest.iterdir()))

    def test_bazaar_launcher_migration_removes_only_stale_rpm_launcher(self) -> None:
        hook = (
            ROOT
            / "system_files/dudley/usr/share/ublue-os/user-setup.hooks.d"
            / "15-dudley-bazaar-launcher.sh"
        )
        self.assertTrue(hook.is_file())

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            launcher = home / ".local/share/applications/io.github.kolunmi.Bazaar.desktop"
            launcher.parent.mkdir(parents=True)
            launcher.write_text(
                "[Desktop Entry]\nExec=bazaar window --auto-service %U\n",
                encoding="utf-8",
            )

            env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
            subprocess.run(["bash", str(hook)], cwd=ROOT, env=env, check=True)
            self.assertFalse(launcher.exists())

            launcher.write_text(
                "[Desktop Entry]\nExec=/usr/bin/flatpak run io.github.kolunmi.Bazaar\n",
                encoding="utf-8",
            )
            subprocess.run(["bash", str(hook)], cwd=ROOT, env=env, check=True)
            self.assertTrue(launcher.is_file())

    def test_desktop_parity_hook_restores_bluefin_panel_and_known_font_defaults(self) -> None:
        hook = (
            ROOT
            / "system_files/dudley/usr/share/ublue-os/user-setup.hooks.d"
            / "12-dudley-desktop-parity.sh"
        )
        self.assertTrue(hook.is_file())

        skel = json.loads(
            (
                ROOT
                / "system_files/dudley/etc/skel/.config/Code - Insiders/User/settings.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual("JetBrains Mono", skel["terminal.integrated.fontFamily"])
        self.assertEqual(16, skel["terminal.integrated.fontSize"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            fake_bin = root / "bin"
            settings = home / ".config/Code - Insiders/User/settings.json"
            log = root / "gnome-extensions.log"
            settings.parent.mkdir(parents=True)
            fake_bin.mkdir()
            settings.write_text(
                json.dumps(
                    {
                        "editor.fontFamily": "'monospace'",
                        "editor.fontSize": 14,
                        "terminal.integrated.fontFamily": "monospace",
                        "terminal.integrated.fontSize": 14,
                        "dudley.test": "preserved",
                    }
                ),
                encoding="utf-8",
            )

            fake_gnome_extensions = fake_bin / "gnome-extensions"
            fake_gnome_extensions.write_text(
                "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >>\"${GNOME_EXTENSIONS_LOG}\"\n",
                encoding="utf-8",
            )
            fake_gnome_extensions.chmod(0o755)

            env = {
                "HOME": str(home),
                "PATH": f"{fake_bin}:/usr/bin:/bin",
                "GNOME_EXTENSIONS_LOG": str(log),
            }
            subprocess.run(["bash", str(hook)], cwd=ROOT, env=env, check=True)

            migrated = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual("JetBrains Mono", migrated["terminal.integrated.fontFamily"])
            self.assertEqual(16, migrated["terminal.integrated.fontSize"])
            self.assertTrue(migrated["editor.fontFamily"].startswith("'JetBrains Mono'"))
            self.assertEqual(16, migrated["editor.fontSize"])
            self.assertEqual("preserved", migrated["dudley.test"])
            self.assertEqual(
                "enable custom-command-list@storageb.github.com",
                log.read_text(encoding="utf-8").strip(),
            )

            subprocess.run(["bash", str(hook)], cwd=ROOT, env=env, check=True)
            self.assertEqual(1, len(log.read_text(encoding="utf-8").splitlines()))


if __name__ == "__main__":
    unittest.main()
