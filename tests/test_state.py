from __future__ import annotations

import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rofi_ssh_plus.model import SORT_FREQUENCY, SORT_RECENCY
from rofi_ssh_plus.state import SCHEMA_VERSION, StateStore


class StateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.path = self.root / "rofi-ssh-plus" / "history.json"
        self.legacy = self.root / "DankMaterialShell" / "plugins" / "sshPlus_state.json"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def write_legacy(self, payload: object) -> None:
        self.legacy.parent.mkdir(parents=True, exist_ok=True)
        self.legacy.write_text(json.dumps(payload), encoding="utf-8")

    def test_migrates_valid_partial_and_duplicate_legacy_records_once(self) -> None:
        self.write_legacy(
            {
                "hosts": [
                    {"host": "StarShip", "lastConnected": 100, "count": 2},
                    {"host": "starship", "lastConnected": 300, "count": 4},
                    {"host": "SNAP", "lastConnected": "bad", "count": 3},
                    {"host": "bad host", "lastConnected": 500, "count": 9},
                    {"host": "missing-fields"},
                    None,
                ]
            }
        )
        store = StateStore(self.path, self.legacy)
        state = store.load()
        self.assertEqual(state.sort_mode, SORT_FREQUENCY)
        self.assertEqual(
            [(h.host, h.last_connected, h.count) for h in state.hosts],
            [("starship", 300, 6), ("snap", 0, 3), ("missing-fields", 0, 1)],
        )
        self.assertTrue(self.path.exists())
        self.assertTrue(self.legacy.exists())
        self.assertEqual(json.loads(self.path.read_text())["version"], SCHEMA_VERSION)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)

        self.write_legacy({"hosts": [{"host": "new-host", "count": 99, "lastConnected": 999}]})
        self.assertNotIn("new-host", {h.host for h in store.load().hosts})

    def test_missing_or_malformed_legacy_still_creates_one_time_state(self) -> None:
        self.legacy.parent.mkdir(parents=True)
        self.legacy.write_text("not json", encoding="utf-8")
        store = StateStore(self.path, self.legacy)
        self.assertEqual(store.load().hosts, ())
        self.assertTrue(self.path.exists())
        self.legacy.write_text(json.dumps({"hosts": [{"host": "later"}]}), encoding="utf-8")
        self.assertEqual(store.load().hosts, ())

    def test_sort_mode_and_remove_are_persisted(self) -> None:
        store = StateStore(self.path, self.legacy)
        store.record_success("Alpha", now_ms=100)
        store.record_success("Bravo", now_ms=200)
        state = store.set_sort_mode(SORT_RECENCY)
        self.assertEqual(state.sort_mode, SORT_RECENCY)
        self.assertEqual(store.load().sort_mode, SORT_RECENCY)
        removed, state = store.remove("ALPHA")
        self.assertTrue(removed)
        self.assertEqual([h.host for h in state.hosts], ["bravo"])
        removed, _ = store.remove("not-there")
        self.assertFalse(removed)

    def test_record_success_does_not_regress_last_connected(self) -> None:
        store = StateStore(self.path, self.legacy)
        store.record_success("Alpha", now_ms=200)
        state = store.record_success("Alpha", now_ms=100)
        self.assertEqual(state.hosts[0].last_connected, 200)
        self.assertEqual(state.hosts[0].count, 2)

    def test_directional_sort_cycle_wraps_and_persists(self) -> None:
        store = StateStore(self.path, self.legacy)
        self.assertEqual(SORT_RECENCY, store.cycle_sort_mode(1).sort_mode)
        self.assertEqual(SORT_FREQUENCY, store.cycle_sort_mode(1).sort_mode)
        self.assertEqual(SORT_RECENCY, store.cycle_sort_mode(-1).sort_mode)
        self.assertEqual(SORT_FREQUENCY, store.cycle_sort_mode(-1).sort_mode)
        self.assertEqual(SORT_FREQUENCY, store.load().sort_mode)

        for direction in (0, 2, -2):
            with self.subTest(direction=direction):
                with self.assertRaises(ValueError):
                    store.cycle_sort_mode(direction)

    def test_concurrent_record_mutations_do_not_lose_updates(self) -> None:
        store = StateStore(self.path, self.legacy)

        def record(index: int) -> None:
            store.record_success("shared-host", now_ms=100 + index)

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(record, range(16)))
        state = store.load()
        self.assertEqual(len(state.hosts), 1)
        self.assertEqual(state.hosts[0].count, 16)
        self.assertEqual(state.hosts[0].last_connected, 115)

    def test_unknown_generic_schema_is_not_imported_over(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"version": 99, "hosts": [{"host": "generic"}]}), encoding="utf-8")
        self.write_legacy({"hosts": [{"host": "legacy"}]})
        state = StateStore(self.path, self.legacy).load()
        self.assertEqual(state.hosts, ())
        self.assertNotIn("legacy", self.path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
