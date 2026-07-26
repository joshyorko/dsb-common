from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "system_files/dudley/usr/lib"
sys.path.insert(0, str(LIBRARY))

from dudley_theme.state import StateConflict, StateStore


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

    def test_recover_pointer_uses_newest_committed_generation(self) -> None:
        store = StateStore(self.root)
        store.create_generation("a", {"state": "ACTIVE"})
        store.commit_generation("a")
        store.create_generation("b", {"state": "ACTIVE"})
        store.commit_generation("b")
        (self.root / "current").unlink()

        self.assertEqual("b", store.recover_pointer())
        self.assertEqual("b", store.current_id())
        self.assertEqual("a", store.previous_id())

    def test_recover_pointer_repairs_inconsistent_committed_pointers(self) -> None:
        store = StateStore(self.root)
        store.create_generation("a", {"state": "ACTIVE"})
        store.commit_generation("a")
        store.create_generation("b", {"state": "ACTIVE"})
        store.commit_generation("b")
        (self.root / "current").unlink()
        (self.root / "current").symlink_to("generations/a")
        (self.root / "previous").unlink()
        (self.root / "previous").symlink_to("generations/b")

        self.assertEqual("b", store.recover_pointer())
        self.assertEqual("b", store.current_id())
        self.assertEqual("a", store.previous_id())

    def test_commit_rejects_generation_symlink_escaping_store(self) -> None:
        store = StateStore(self.root)
        external = self.root / "external"
        external.mkdir()
        (store.generations_path / "escape").symlink_to(
            external, target_is_directory=True
        )

        with self.assertRaises(StateConflict):
            store.commit_generation("escape")

    def test_recover_pointer_completes_durable_prepared_journal(self) -> None:
        store = StateStore(self.root)
        store.create_generation("a", {"state": "ACTIVE"})
        store.commit_generation("a")
        store.create_generation("b", {"state": "ACTIVE"})
        journal = store.transactions_path / "00000000000000000002-b.json"
        store._atomic_json(
            journal,
            {
                "generation_id": "b",
                "previous_generation_id": "a",
                "sequence": 2,
                "state": "PREPARED",
            },
        )

        self.assertEqual("b", store.recover_pointer())
        self.assertEqual("b", store.current_id())
        self.assertEqual("a", store.previous_id())
        self.assertEqual(
            "COMMITTED", json.loads(journal.read_text(encoding="utf-8"))["state"]
        )

    def test_recover_pointer_breaks_duplicate_sequences_deterministically(self) -> None:
        store = StateStore(self.root)
        store.create_generation("a", {"state": "ACTIVE"})
        store.create_generation("b", {"state": "ACTIVE"})
        store._atomic_json(
            store.transactions_path / "00000000000000000001-b.json",
            {
                "generation_id": "b",
                "previous_generation_id": "a",
                "sequence": 1,
                "state": "COMMITTED",
            },
        )
        store._atomic_json(
            store.transactions_path / "00000000000000000001-a.json",
            {
                "generation_id": "a",
                "previous_generation_id": None,
                "sequence": 1,
                "state": "COMMITTED",
            },
        )
        (store.transactions_path / "00000000000000000002-invalid.json").write_text(
            "not json", encoding="utf-8"
        )

        self.assertEqual("b", store.recover_pointer())
        self.assertEqual("b", store.current_id())
        self.assertEqual("a", store.previous_id())

    def test_commit_reserves_sequence_from_separatorless_journal_name(self) -> None:
        store = StateStore(self.root)
        store.create_generation("a", {"state": "ACTIVE"})
        store.commit_generation("a")
        store.create_generation("b", {"state": "ACTIVE"})
        store._atomic_json(
            store.transactions_path / "00000000000000000002.json",
            {
                "generation_id": "b",
                "previous_generation_id": "a",
                "sequence": 2,
                "state": "COMMITTED",
            },
        )
        store.create_generation("c", {"state": "ACTIVE"})

        store.commit_generation("c")

        sequences = sorted(
            json.loads(path.read_text(encoding="utf-8"))["sequence"]
            for path in store.transactions_path.glob("*.json")
        )
        self.assertEqual([1, 2, 3], sequences)
        self.assertEqual("c", store.current_id())
        self.assertEqual("b", store.previous_id())

    def test_recover_pointer_completes_commit_interrupted_after_journal_write(self) -> None:
        store = StateStore(self.root)
        store.create_generation("a", {"state": "ACTIVE"})
        store.commit_generation("a")
        store.create_generation("b", {"state": "ACTIVE"})

        with patch.object(
            store,
            "_after_journal_persisted",
            side_effect=InterruptedError("simulated crash"),
        ):
            with self.assertRaises(InterruptedError):
                store.commit_generation("b")

        journals = list(store.transactions_path.glob("*.json"))
        prepared = [
            path
            for path in journals
            if json.loads(path.read_text(encoding="utf-8"))["state"] == "PREPARED"
        ]
        self.assertEqual(1, len(prepared))
        self.assertEqual("a", store.current_id())
        self.assertEqual("b", store.recover_pointer())
        self.assertEqual("b", store.current_id())
        self.assertEqual("a", store.previous_id())

    def test_concurrent_commits_allocate_unique_journal_sequences(self) -> None:
        store = StateStore(self.root)
        store.create_generation("a", {"state": "ACTIVE"})
        store.create_generation("b", {"state": "ACTIVE"})
        start = threading.Barrier(3)
        errors: list[BaseException] = []

        def commit(generation_id: str) -> None:
            try:
                start.wait()
                StateStore(self.root).commit_generation(generation_id)
            except BaseException as error:
                errors.append(error)

        workers = [threading.Thread(target=commit, args=(generation_id,)) for generation_id in ("a", "b")]
        for worker in workers:
            worker.start()
        start.wait()
        for worker in workers:
            worker.join()

        self.assertEqual([], errors)
        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in store.transactions_path.glob("*.json")
        ]
        self.assertEqual([1, 2], sorted(record["sequence"] for record in records))
        latest = max(records, key=lambda record: record["sequence"])
        self.assertEqual(latest["generation_id"], store.recover_pointer())


if __name__ == "__main__":
    unittest.main()
