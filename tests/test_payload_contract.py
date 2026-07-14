from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contract" / "dudley-payload.v1.json"
INSTALLER = ROOT / "scripts" / "install-payload.py"
SYSTEM_FILES = ROOT / "system_files"


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
            self.assertTrue((dest / "usr/share/ublue-os/just/60-dudley.just").is_file())

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
