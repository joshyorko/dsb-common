from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "system_files/dudley/usr/lib"
sys.path.insert(0, str(LIBRARY))

from dudley_theme.cli import main  # noqa: E402
from dudley_theme.engine import Result, StatusReport, ThemeEngine  # noqa: E402

from tests.test_theme_engine import FakeAdapter, FakeTheme  # noqa: E402


class LegacyMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.config = self.home / ".config/dudley"
        self.config.mkdir(parents=True)
        self.state_root = self.root / "state"
        self.runtime_dir = self.root / "runtime"
        self.runtime_dir.mkdir(mode=0o700)
        self.surface = {"one": "current"}
        self.theme = FakeTheme(
            "alpha",
            "Alpha",
            required_adapters=("one",),
        )

    def engine(self) -> ThemeEngine:
        def render(theme: FakeTheme, destination: Path) -> SimpleNamespace:
            destination.mkdir(parents=True)
            (destination / "theme.txt").write_text(theme.id, encoding="utf-8")
            return SimpleNamespace(
                destination=destination,
                hashes={"theme.txt": theme.id},
            )

        return ThemeEngine(
            state_root=self.state_root,
            runtime_dir=self.runtime_dir,
            home=self.home,
            themes={"alpha": self.theme},
            adapter_factories={
                "one": lambda _theme, _context: FakeAdapter("one", self.surface)
            },
            renderer=render,
            default_theme="alpha",
        )

    def test_experimental_state_is_archived_and_blocks_automatic_activation(
        self,
    ) -> None:
        (self.config / "theme").write_text("alpha\n", encoding="utf-8")
        (self.config / "theme-receipt.json").write_text(
            '{"theme":"alpha"}\n', encoding="utf-8"
        )
        engine = self.engine()

        report = engine.status()
        result = engine.on()

        self.assertEqual("CONFLICTED", report.state)
        self.assertEqual(3, result.exit_code)
        self.assertEqual("current", self.surface["one"])
        archived = list((self.state_root / "legacy").glob("*"))
        self.assertEqual(2, len(archived))
        self.assertFalse((self.config / "theme").exists())
        self.assertFalse((self.config / "theme-receipt.json").exists())

    def test_adopt_current_baseline_clears_legacy_conflict_without_mutation(
        self,
    ) -> None:
        (self.config / "theme").write_text("alpha\n", encoding="utf-8")
        engine = self.engine()
        self.assertEqual("CONFLICTED", engine.status().state)

        result = engine.repair(adopt_current_baseline=True)

        self.assertEqual(0, result.exit_code)
        self.assertEqual("UNMANAGED", engine.status().state)
        self.assertEqual("current", self.surface["one"])
        preferences = json.loads(
            (self.state_root / "preferences.json").read_text(encoding="utf-8")
        )
        self.assertTrue(preferences["adopted_current_baseline"])


class CliTests(unittest.TestCase):
    def invoke(self, argv: list[str], engine: Mock) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv, engine=engine)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_usage_errors_exit_two(self) -> None:
        code, _, _ = self.invoke(["set"], Mock())
        self.assertEqual(2, code)

    def test_result_exit_codes_are_preserved(self) -> None:
        for expected in (0, 3, 4):
            with self.subTest(exit_code=expected):
                engine = Mock()
                engine.on.return_value = Result("test", "result", expected)
                code, _, _ = self.invoke(["on"], engine)
                self.assertEqual(expected, code)

    def test_compatibility_aliases_route_through_transactional_methods(self) -> None:
        cases = [
            (["apply", "alpha"], "set", ("alpha",)),
            (["current"], "status", ()),
            (["reset"], "off", ()),
        ]
        for argv, method, arguments in cases:
            with self.subTest(command=argv[0]):
                engine = Mock()
                if method == "status":
                    engine.status.return_value = StatusReport(
                        state="ACTIVE",
                        theme_id="alpha",
                        generation_id="g1",
                        surfaces={},
                    )
                else:
                    getattr(engine, method).return_value = Result("verified", "ok", 0)
                code, _, stderr = self.invoke(argv, engine)
                self.assertEqual(0, code)
                getattr(engine, method).assert_called_once_with(*arguments)
                self.assertIn("deprecated", stderr.lower())

    def test_status_json_is_machine_readable(self) -> None:
        engine = Mock()
        engine.status.return_value = StatusReport(
            state="ACTIVE",
            theme_id="alpha",
            generation_id="g1",
            surfaces={"one": "verified"},
        )

        code, stdout, _ = self.invoke(["status", "--json"], engine)

        self.assertEqual(0, code)
        self.assertEqual("ACTIVE", json.loads(stdout)["state"])

    def test_launcher_finds_sibling_library_from_payload_tree(self) -> None:
        launcher = ROOT / "system_files/dudley/usr/bin/dudley-theme"
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)

        result = subprocess.run(
            [str(launcher)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("Usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
