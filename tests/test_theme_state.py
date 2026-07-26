from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "system_files/dudley/usr/lib"
sys.path.insert(0, str(LIBRARY))

from dudley_theme.state import StateStore


class StateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def test_commit_moves_current_to_previous(self) -> None:
        store = StateStore(self.root)
        store.create_generation("a", {"state": "ACTIVE"})
        store.commit_generation("a")
        store.create_generation("b", {"state": "ACTIVE"})
        store.commit_generation("b")

        self.assertEqual("b", store.current_id())
        self.assertEqual("a", store.previous_id())

    def test_newer_schema_is_read_only(self) -> None:
        (self.root / "preferences.json").write_text(
            '{"schema_version": 999}', encoding="utf-8"
        )

        self.assertTrue(StateStore(self.root).read_only)

    def test_recover_pointer_repairs_one_committed_generation(self) -> None:
        store = StateStore(self.root)
        store.create_generation("a", {"state": "ACTIVE"})
        store.commit_generation("a")
        (self.root / "current").unlink()

        self.assertEqual("a", store.recover_pointer())
        self.assertEqual("a", store.current_id())


if __name__ == "__main__":
    unittest.main()
