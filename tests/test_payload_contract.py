from __future__ import annotations

import hashlib
import json
import re
import shlex
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
PARITY_MANIFEST = ROOT / "contract" / "dudley-parity.v1.json"
INSTALLER = ROOT / "scripts" / "install-payload.py"
SYSTEM_FILES = ROOT / "system_files"
DUDLEY_SYSTEM_FILES = SYSTEM_FILES / "dudley"
SHARED_SYSTEM_FILES = SYSTEM_FILES / "shared"
WALLPAPER_DIR = DUDLEY_SYSTEM_FILES / "usr/share/backgrounds/dudley"
WALLPAPER_CATALOG = (
    DUDLEY_SYSTEM_FILES / "usr/share/gnome-background-properties/dudley.xml"
)
FIRST_NEW_WALLPAPER = WALLPAPER_DIR / "dudley-os-clever-girl-golden-bedroom.png"
SECOND_NEW_WALLPAPER = WALLPAPER_DIR / "dudley-os-clever-girl-golden-study.png"
HOMEBREW_DIR = DUDLEY_SYSTEM_FILES / "usr/share/ublue-os/homebrew"
HOMEBREW_PROFILES = DUDLEY_SYSTEM_FILES / "usr/share/dudley/homebrew-profiles.json"
DUDLEY_JUST = DUDLEY_SYSTEM_FILES / "usr/share/ublue-os/just/60-dudley.just"
NO_ASK_HELPER = DUDLEY_SYSTEM_FILES / "usr/libexec/dudley/configure-homebrew-no-ask"
ENSURE_BREW = DUDLEY_SYSTEM_FILES / "usr/libexec/dudley/ensure-homebrew"
DUDLEY_BUILD_INFO = DUDLEY_SYSTEM_FILES / "usr/bin/dudley-build-info"
TERMINAL_CONTRACT = DUDLEY_SYSTEM_FILES / "usr/share/dudley/terminal-contract.json"
GHOSTTY_CONFIG = DUDLEY_SYSTEM_FILES / "usr/share/dudley/terminal/ghostty.conf"
PTYXIS_CONFIG = DUDLEY_SYSTEM_FILES / "usr/share/dudley/terminal/ptyxis.dconf"


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
            {
                "dudley-ai.Brewfile",
                "dudley-cli.Brewfile",
                "dudley-default.Brewfile",
                "dudley-dev.Brewfile",
                "dudley-fonts.Brewfile",
                "dudley-ide.Brewfile",
                "dudley-k8s.Brewfile",
            },
            brewfiles,
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

    def test_dudley_just_exposes_one_setup_dispatcher(self) -> None:
        recipe = DUDLEY_JUST.read_text(encoding="utf-8")
        recipe_names = set(
            re.findall(r"^([a-z0-9_-]+)(?:\s+[^:]*)?:$", recipe, re.MULTILINE)
        )
        self.assertIn('dudley action="" target="" mode="":', recipe)
        self.assertIn('run_bundle "dudley-default.Brewfile"', recipe)
        self.assertIn('run_bundle "dudley-ai.Brewfile"', recipe)
        tools_block = recipe.split("        tools)\n", 1)[1].split(
            "        extensions)", 1
        )[0]
        self.assertIn('run_bundle "dudley-default.Brewfile"', tools_block)
        self.assertNotIn('run_bundle "dudley-ai.Brewfile"', tools_block)
        for target in ("cli", "dev", "ide", "fonts", "k8s", "all"):
            self.assertIn(target, recipe)
        self.assertIn("DUDLEY_BREW_HELPER", recipe)
        self.assertIn("DUDLEY_BREW_DIR", recipe)
        self.assertIn('/usr/bin/dudley-build-info', recipe)
        self.assertIn("toggle-user-motd:", recipe)
        self.assertEqual(
            {"dudley"},
            {name for name in recipe_names if name.startswith("dudley")},
        )

    def test_parity_manifest_has_explicit_bluefin_and_dakota_ownership(self) -> None:
        manifest = json.loads(PARITY_MANIFEST.read_text(encoding="utf-8"))
        statuses = set(manifest["status_labels"])
        self.assertEqual({"bluefin", "dakota"}, set(manifest["consumers"]))
        self.assertTrue(manifest["entries"])

        for entry in manifest["entries"]:
            with self.subTest(name=entry["name"]):
                self.assertIn(entry["status"], statuses)
                self.assertIn(entry["bluefin"], statuses)
                self.assertIn(entry["dakota"], statuses)
                self.assertTrue(entry["source"])

        names = {entry["name"] for entry in manifest["entries"]}
        self.assertIn("dudley brew cli|dev|ide|fonts|k8s|all", names)
        self.assertIn("Ghostty native adapter", names)
        self.assertIn("uwelcome configuration and umotd tags", names)

    def test_terminal_contract_is_rendered_for_both_emulators(self) -> None:
        contract = json.loads(TERMINAL_CONTRACT.read_text(encoding="utf-8"))
        defaults = contract["defaults"]
        self.assertEqual({"columns": 120, "rows": 40}, defaults["initial_size"])
        self.assertEqual("JetBrains Mono", defaults["font"]["family"])
        self.assertEqual(16, defaults["font"]["size"])
        self.assertEqual("allow", defaults["clipboard"]["read"])
        self.assertEqual("allow", defaults["clipboard"]["write"])

        ghostty = GHOSTTY_CONFIG.read_text(encoding="utf-8")
        self.assertIn("font-family = JetBrains Mono", ghostty)
        self.assertIn("font-size = 16", ghostty)
        self.assertIn("window-width = 120", ghostty)
        self.assertIn("window-height = 40", ghostty)
        self.assertIn("shell-integration = detect", ghostty)
        self.assertNotIn("ptyxis", ghostty.lower())

        ptyxis = PTYXIS_CONFIG.read_text(encoding="utf-8")
        self.assertIn("font-name='JetBrains Mono 16'", ptyxis)
        self.assertIn("palette='catppuccin-dynamic'", ptyxis)

    def test_shared_motd_payload_matches_upstream_contract(self) -> None:
        config = json.loads(
            (SHARED_SYSTEM_FILES / "etc/uwelcome/config.json").read_text(
                encoding="utf-8"
            )
        )
        tags = json.loads(
            (SHARED_SYSTEM_FILES / "etc/ublue-os/tags.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(["umotd"], config["motd"]["commands"])
        self.assertEqual(
            {
                "https://issues.projectbluefin.io/",
                "https://ask.projectbluefin.io/",
                "https://docs.projectbluefin.io/",
            },
            {link["url"] for link in config["links"]},
        )
        self.assertEqual(
            {"bluefin", "gnome", "vscode", "containers"}, set(tags["tags"])
        )
        hook = (SHARED_SYSTEM_FILES / "etc/profile.d/uwelcome.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("uwelcome", hook)
        self.assertIn("no-show-user-motd", hook)

    def test_dudley_build_info_is_nonfatal_before_final_assembly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["bash", str(DUDLEY_BUILD_INFO)],
                cwd=ROOT,
                env={"DUDLEY_BUILD_MANIFEST": str(Path(tmp) / "missing.json")},
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode)
            self.assertIn("metadata is unavailable", result.stdout)

    def test_dudley_just_bootstraps_brew_in_a_clean_home(self) -> None:
        just = shutil.which("just")
        if just is None:
            self.skipTest("just is not installed locally")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            justfile = DUDLEY_JUST
            probe = subprocess.run(
                [just, "--justfile", str(justfile), "--list"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            if "Unknown attribute `group`" in probe.stderr:
                # Ubuntu's packaged Just can lag the setup-just version used
                # by CI. Keep the recipe body testable without changing the
                # production recipe's grouping metadata.
                justfile = root / "60-dudley.just"
                justfile.write_text(
                    re.sub(
                        r"^\[group\('Dudley'\)\]\n",
                        "",
                        DUDLEY_JUST.read_text(),
                        flags=re.MULTILINE,
                    ),
                    encoding="utf-8",
                )
            home = root / "home"
            brew_dir = root / "homebrew"
            brew_bin = root / "brew-bin"
            log = root / "brew.log"
            bootstrap_log = root / "bootstrap.log"
            home.mkdir()
            brew_dir.mkdir()
            brew_bin.mkdir()
            (brew_dir / "dudley-cli.Brewfile").write_text(
                'cask "demo-linux"\n', encoding="utf-8"
            )
            bootstrap_log_path = shlex.quote(str(bootstrap_log))
            brew_log_path = shlex.quote(str(log))

            bootstrap = root / "bootstrap"
            bootstrap.write_text(
                f"""#!/usr/bin/env bash
set -euo pipefail
printf 'bootstrapped\\n' >> {bootstrap_log_path}
cat > "$DUDLEY_BREW_BIN/brew" <<'BREW'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${{DUDLEY_BREW_LOG}}"
case "$1" in
    list) exit 1 ;;
    bundle|install) exit 0 ;;
    *) exit 0 ;;
esac
BREW
chmod +x "$DUDLEY_BREW_BIN/brew"
""",
                encoding="utf-8",
            )
            bootstrap.chmod(0o755)

            extensions = root / "extensions"
            extensions.write_text(
                f"""#!/usr/bin/env bash
printf 'extensions\\n' >> {brew_log_path}
""",
                encoding="utf-8",
            )
            extensions.chmod(0o755)

            env = {
                "HOME": str(home),
                "PATH": "/usr/bin:/bin",
                "DUDLEY_BREW_DIR": str(brew_dir),
                "DUDLEY_BREW_BIN": str(brew_bin),
                "DUDLEY_BREW_BOOTSTRAP": str(bootstrap),
                "DUDLEY_BREW_LOG": str(log),
                "DUDLEY_EXTENSIONS_HOOK": str(extensions),
                "DUDLEY_NO_ASK_HELPER": str(NO_ASK_HELPER),
                "DUDLEY_BREW_HELPER": str(ENSURE_BREW),
            }
            result = subprocess.run(
                [just, "--justfile", str(justfile), "dudley", "brew", "cli"],
                cwd=ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("bootstrapped", bootstrap_log.read_text(encoding="utf-8"))
            brew_log = log.read_text(encoding="utf-8")
            self.assertIn(f"bundle --file={brew_dir}/dudley-cli.Brewfile", brew_log)
            self.assertIn("list --cask demo-linux", brew_log)
            self.assertIn("install --cask demo-linux", brew_log)
            self.assertIn("HOMEBREW_NO_ASK=1", (home / ".homebrew/brew.env").read_text())

    def test_homebrew_no_ask_helper_preserves_settings_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            env_file = home / ".homebrew/brew.env"
            env_file.parent.mkdir(parents=True)
            env_file.write_text(
                "HOMEBREW_NO_ANALYTICS=1\nHOMEBREW_NO_ASK=0\n",
                encoding="utf-8",
            )
            env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}

            subprocess.run(["bash", str(NO_ASK_HELPER)], cwd=ROOT, env=env, check=True)
            first = env_file.read_text(encoding="utf-8")
            subprocess.run(["bash", str(NO_ASK_HELPER)], cwd=ROOT, env=env, check=True)
            second = env_file.read_text(encoding="utf-8")

            self.assertEqual(first, second)
            self.assertEqual(1, first.count("HOMEBREW_NO_ASK="))
            self.assertIn("HOMEBREW_NO_ASK=1", first)
            self.assertIn("HOMEBREW_NO_ANALYTICS=1", first)

    def test_update_checks_rpm_ostree_config_exists_before_grep(self) -> None:
        recipe = (
            DUDLEY_SYSTEM_FILES / "usr/share/ublue-os/just/update.just"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "if [[ -f /etc/rpm-ostreed.conf ]] && grep -q -E",
            recipe,
        )

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

    def test_dakota_install_includes_portable_and_ghostty_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            subprocess.run(
                [sys.executable, str(INSTALLER), "--profile", "dakota", "--dest", str(dest)],
                cwd=ROOT,
                check=True,
            )

            self.assertTrue((dest / "usr/share/dudley/terminal-contract.json").is_file())
            self.assertTrue((dest / "usr/share/dudley/terminal/ghostty.conf").is_file())
            self.assertTrue((dest / "etc/uwelcome/config.json").is_file())
            self.assertTrue((dest / "usr/share/ublue-os/just/60-dudley.just").is_file())
            self.assertFalse((dest / "etc/dconf/db/distro.d/99-dudley-terminal-keybindings").exists())
            self.assertFalse((dest / "usr/share/backgrounds/dudley").exists())

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
