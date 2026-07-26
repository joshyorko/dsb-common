from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "system_files/dudley/usr/lib"
sys.path.insert(0, str(LIBRARY))

from dudley_theme.adapters.base import (  # noqa: E402
    Adapter,
    AdapterResult,
    AdapterStatus,
    ThemeContext,
)
from dudley_theme.adapters.apps import KittyAdapter  # noqa: E402
from dudley_theme.engine import ThemeEngine  # noqa: E402
from dudley_theme.model import ResourceRecord  # noqa: E402


@dataclass(frozen=True)
class FakeTheme:
    id: str
    name: str
    version: str = "1"
    required_adapters: tuple[str, ...] = ("one", "two", "three")
    optional_adapters: tuple[str, ...] = ()
    render_outputs: tuple[Any, ...] = ()
    manifest: dict[str, Any] = None  # type: ignore[assignment]
    root: Path = Path("/")

    def __post_init__(self) -> None:
        if self.manifest is None:
            object.__setattr__(self, "manifest", {"assets": {}})


class SimulatedCrash(BaseException):
    pass


class FakeAdapter(Adapter):
    def __init__(
        self,
        adapter_id: str,
        surface: dict[str, str],
        *,
        fail_apply: bool = False,
        raise_apply: bool = False,
        activity: dict[str, int] | None = None,
    ) -> None:
        self.adapter_id = adapter_id
        self.surface = surface
        self.fail_apply = fail_apply
        self.raise_apply = raise_apply
        self.activity = activity

    def capture(self, context: ThemeContext) -> list[ResourceRecord]:
        return [
            ResourceRecord(
                adapter=self.adapter_id,
                resource=self.adapter_id,
                before=self.surface[self.adapter_id],
                applied=context.values["theme_id"],
            )
        ]

    def apply(
        self, context: ThemeContext, records: list[ResourceRecord]
    ) -> AdapterResult:
        del context
        if self.activity is not None:
            with self.activity["lock"]:
                self.activity["active"] += 1
                self.activity["maximum"] = max(
                    self.activity["maximum"], self.activity["active"]
                )
            time.sleep(0.02)
        self.surface[self.adapter_id] = records[0].applied
        if self.activity is not None:
            with self.activity["lock"]:
                self.activity["active"] -= 1
        if self.raise_apply:
            raise RuntimeError(f"injected {self.adapter_id} failure")
        return AdapterResult("failed" if self.fail_apply else "applied")

    def verify(self, context: ThemeContext) -> AdapterStatus:
        expected = context.values["theme_id"]
        return AdapterStatus(
            "verified" if self.surface[self.adapter_id] == expected else "drifted"
        )

    def restore(
        self, context: ThemeContext, records: list[ResourceRecord]
    ) -> AdapterResult:
        del context
        record = records[0]
        current = self.surface[self.adapter_id]
        if current == record.before:
            return AdapterResult("unchanged")
        if current != record.applied:
            return AdapterResult("conflicted", (self.adapter_id,))
        self.surface[self.adapter_id] = record.before
        return AdapterResult("restored")


class ThemeEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state_root = self.root / "state"
        self.runtime_dir = self.root / "runtime"
        self.runtime_dir.mkdir(mode=0o700)
        self.home = self.root / "home"
        self.home.mkdir()
        self.themes = {
            theme_id: FakeTheme(theme_id, theme_id.title())
            for theme_id in ("alpha", "beta")
        }
        self.surface = {"one": "baseline-1", "two": "baseline-2", "three": "baseline-3"}

    @staticmethod
    def render(theme: FakeTheme, destination: Path) -> SimpleNamespace:
        destination.mkdir(parents=True)
        output = destination / "theme.txt"
        output.write_text(theme.id, encoding="utf-8")
        return SimpleNamespace(destination=destination, hashes={"theme.txt": theme.id})

    def engine(
        self,
        *,
        failing: str | None = None,
        raising: str | None = None,
        activity: dict[str, int] | None = None,
        fault_hook: Any = None,
    ) -> ThemeEngine:
        factories = {
            adapter_id: (
                lambda _theme, _context, adapter_id=adapter_id: FakeAdapter(
                    adapter_id,
                    self.surface,
                    fail_apply=adapter_id == failing,
                    raise_apply=adapter_id == raising,
                    activity=activity,
                )
            )
            for adapter_id in self.surface
        }
        return ThemeEngine(
            state_root=self.state_root,
            runtime_dir=self.runtime_dir,
            home=self.home,
            themes=self.themes,
            adapter_factories=factories,
            renderer=self.render,
            default_theme="alpha",
            fault_hook=fault_hook,
        )

    def test_apply_switch_undo_and_off_restore_original_baseline(self) -> None:
        engine = self.engine()

        self.assertEqual(0, engine.set("alpha").exit_code)
        self.assertEqual(
            {"one": "alpha", "two": "alpha", "three": "alpha"}, self.surface
        )
        self.assertEqual(0, engine.set("beta").exit_code)
        self.assertEqual({"one": "beta", "two": "beta", "three": "beta"}, self.surface)
        self.assertEqual(0, engine.undo().exit_code)
        self.assertEqual(
            {"one": "alpha", "two": "alpha", "three": "alpha"}, self.surface
        )
        self.assertEqual(0, engine.off().exit_code)
        self.assertEqual(
            {"one": "baseline-1", "two": "baseline-2", "three": "baseline-3"},
            self.surface,
        )
        self.assertEqual("DISABLED", engine.status().state)

    def test_disabled_preference_persists_and_on_reactivates_last_theme(self) -> None:
        engine = self.engine()
        engine.set("beta")
        engine.off()

        restarted = self.engine()
        self.assertEqual("DISABLED", restarted.status().state)
        self.assertEqual(0, restarted.on().exit_code)
        self.assertEqual("beta", restarted.status().theme_id)

    def test_off_preserves_external_edit_and_keeps_active_generation(self) -> None:
        engine = self.engine()
        engine.set("alpha")
        self.surface["one"] = "user-edit"

        result = engine.off()

        self.assertEqual(3, result.exit_code)
        self.assertEqual(
            {"one": "user-edit", "two": "alpha", "three": "alpha"},
            self.surface,
        )
        self.assertEqual("ACTIVE", engine.status().state)
        self.assertEqual("alpha", engine.status().theme_id)

    def test_concurrent_mutations_are_serialized_by_runtime_lock(self) -> None:
        activity: dict[str, Any] = {
            "active": 0,
            "maximum": 0,
            "lock": threading.Lock(),
        }
        start = threading.Barrier(3)
        results = []

        def activate(theme_id: str) -> None:
            start.wait()
            results.append(self.engine(activity=activity).set(theme_id))

        workers = [
            threading.Thread(target=activate, args=(theme_id,))
            for theme_id in ("alpha", "beta")
        ]
        for worker in workers:
            worker.start()
        start.wait()
        for worker in workers:
            worker.join()

        self.assertEqual([0, 0], sorted(result.exit_code for result in results))
        self.assertEqual(1, activity["maximum"])
        self.assertIn(self.engine().status().theme_id, {"alpha", "beta"})

    def test_failure_after_each_adapter_rolls_back_without_active_receipt(self) -> None:
        for failing in self.surface:
            with self.subTest(adapter=failing):
                self.surface.update(
                    one="baseline-1", two="baseline-2", three="baseline-3"
                )
                state_root = self.root / f"failure-{failing}"
                original = self.state_root
                self.state_root = state_root
                try:
                    result = self.engine(failing=failing).set("alpha")
                    self.assertEqual(4, result.exit_code)
                    self.assertEqual(
                        {
                            "one": "baseline-1",
                            "two": "baseline-2",
                            "three": "baseline-3",
                        },
                        self.surface,
                    )
                    self.assertIsNone(self.engine().status().theme_id)
                finally:
                    self.state_root = original

    def test_adapter_exception_is_rolled_back_and_returns_exit_four(self) -> None:
        result = self.engine(raising="two").set("alpha")

        self.assertEqual(4, result.exit_code)
        self.assertEqual(
            {"one": "baseline-1", "two": "baseline-2", "three": "baseline-3"},
            self.surface,
        )
        self.assertIsNone(self.engine().status().theme_id)

    def test_incomplete_crash_journal_restores_applied_adapters_on_restart(
        self,
    ) -> None:
        def crash(phase: str, adapter_id: str | None) -> None:
            if phase == "after_adapter" and adapter_id == "one":
                raise SimulatedCrash()

        with self.assertRaises(SimulatedCrash):
            self.engine(fault_hook=crash).set("alpha")
        self.assertEqual("alpha", self.surface["one"])

        report = self.engine().status()

        self.assertEqual("UNMANAGED", report.state)
        self.assertEqual("baseline-1", self.surface["one"])

    def test_verified_crash_journal_completes_commit_on_restart(self) -> None:
        def crash(phase: str, adapter_id: str | None) -> None:
            if phase == "after_verify":
                raise SimulatedCrash()

        with self.assertRaises(SimulatedCrash):
            self.engine(fault_hook=crash).set("alpha")

        report = self.engine().status()

        self.assertEqual("ACTIVE", report.state)
        self.assertEqual("alpha", report.theme_id)
        self.assertEqual(
            {"one": "alpha", "two": "alpha", "three": "alpha"}, self.surface
        )

    def test_corrupted_current_pointer_is_recovered_from_commit_journal(self) -> None:
        engine = self.engine()
        engine.set("alpha")
        current = self.state_root / "current"
        current.unlink()
        current.symlink_to("../outside")

        report = self.engine().status()

        self.assertEqual("ACTIVE", report.state)
        self.assertEqual("alpha", report.theme_id)
        self.assertEqual("alpha", self.engine().status().theme_id)

    def test_newer_state_schema_is_read_only_for_mutations(self) -> None:
        self.state_root.mkdir()
        (self.state_root / "preferences.json").write_text(
            '{"schema_version": 999}\n', encoding="utf-8"
        )
        engine = self.engine()

        result = engine.set("alpha")

        self.assertEqual(3, result.exit_code)
        self.assertTrue(engine.status().read_only)
        self.assertEqual(
            {"one": "baseline-1", "two": "baseline-2", "three": "baseline-3"},
            self.surface,
        )

    def test_untrusted_runtime_directory_rejects_mutation(self) -> None:
        self.runtime_dir.chmod(0o755)

        result = self.engine().set("alpha")

        self.assertEqual(3, result.exit_code)
        self.assertIn("runtime", result.message)

    def test_restart_off_restores_typed_adapter_records(self) -> None:
        theme = FakeTheme(
            "alpha",
            "Alpha",
            required_adapters=("kitty",),
            render_outputs=(SimpleNamespace(source="kitty.tpl", path="kitty.conf"),),
            manifest={"assets": {"kitty": "kitty.tpl"}},
        )
        kitty_config = self.home / ".config/kitty/kitty.conf"
        kitty_config.parent.mkdir(parents=True)
        original = b"font_size 13\n"
        kitty_config.write_bytes(original)

        def render(_theme: FakeTheme, destination: Path) -> SimpleNamespace:
            destination.mkdir(parents=True)
            (destination / "kitty.conf").write_text(
                "background #000000\n", encoding="utf-8"
            )
            return SimpleNamespace(
                destination=destination,
                hashes={"kitty.conf": "test"},
            )

        def create_engine() -> ThemeEngine:
            return ThemeEngine(
                state_root=self.state_root,
                runtime_dir=self.runtime_dir,
                home=self.home,
                themes={"alpha": theme},
                adapter_factories={"kitty": lambda _theme, _context: KittyAdapter()},
                renderer=render,
                default_theme="alpha",
            )

        self.assertEqual(0, create_engine().set("alpha").exit_code)
        self.assertEqual(0, create_engine().off().exit_code)
        self.assertEqual(original, kitty_config.read_bytes())
        self.assertFalse((self.home / ".config/kitty/dudley-theme.conf").exists())

    def test_gnome_context_uses_generation_owned_wallpaper_copy(self) -> None:
        theme_root = self.root / "theme"
        wallpaper = theme_root / "wallpapers/wellness.png"
        wallpaper.parent.mkdir(parents=True)
        wallpaper.write_bytes(b"wallpaper")
        theme = FakeTheme(
            "alpha",
            "Alpha",
            required_adapters=("gnome",),
            manifest={
                "assets": {
                    "default_wallpaper": "wallpapers/wellness.png",
                }
            },
            root=theme_root,
        )
        surface = {"gnome": "baseline"}
        captured: list[str] = []

        def factory(_theme: FakeTheme, context: ThemeContext) -> Adapter:
            captured.append(str(context.values["wallpaper"]))
            return FakeAdapter("gnome", surface)

        engine = ThemeEngine(
            state_root=self.state_root,
            runtime_dir=self.runtime_dir,
            home=self.home,
            themes={"alpha": theme},
            adapter_factories={"gnome": factory},
            renderer=self.render,
            default_theme="alpha",
        )

        self.assertEqual(0, engine.set("alpha").exit_code)
        copied = Path(captured[0])
        self.assertEqual(b"wallpaper", copied.read_bytes())
        self.assertTrue(
            copied.is_relative_to(
                self.state_root / "generations" / engine.status().generation_id
            )
        )


if __name__ == "__main__":
    unittest.main()
