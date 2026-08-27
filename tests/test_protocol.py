from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from rofi_ssh_plus.cli import main
from rofi_ssh_plus.model import HostRecord, SORT_RECENCY
from rofi_ssh_plus.protocol import Picker
from rofi_ssh_plus.state import StateStore


class ProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.store = StateStore(root / "history.json", root / "legacy.json")
        self.store.record_success("starship", now_ms=1_000)
        self.store.record_success("starship", now_ms=2_000)
        self.store.record_success("snap", now_ms=3_000)
        self.launched: list[str] = []
        self.picker = Picker(self.store, worker_launcher=lambda host: self.launched.append(host) or True, now_ms=4_000)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_render_has_hot_key_header_raw_info_and_metadata(self) -> None:
        output = self.picker.render()
        self.assertIn("\x00use-hot-keys\x1ftrue", output)
        self.assertIn("\x00message\x1fSorted by frequency", output)
        self.assertIn("Alt+S toggles order", output)
        self.assertIn("Ctrl+Enter connects a typed destination", output)
        self.assertIn("starship  ·  2 connects · just now", output)
        self.assertIn("\x00info\x1fstarship", output)
        self.assertIn("\x00meta\x1fstarship", output)

    def test_selected_uses_rofi_info_and_custom_uses_argv_then_rofi_input(self) -> None:
        self.assertEqual(self.picker.dispatch(1, ["decorated display"], {"ROFI_INFO": "StarShip"}), "")
        self.assertEqual(self.launched, ["starship"])
        self.assertEqual(self.picker.dispatch(2, ["NewHost"], {}), "")
        self.assertEqual(self.launched, ["starship", "newhost"])
        self.assertEqual(self.picker.dispatch(2, [], {"ROFI_INPUT": "InputHost"}), "")
        self.assertEqual(self.launched, ["starship", "newhost", "inputhost"])

    def test_invalid_custom_input_is_not_launched(self) -> None:
        for value in ("", "host name", "-oBad"):
            self.picker.dispatch(2, [value], {})
        self.assertEqual(self.launched, [])

    def test_delete_uses_info_and_renders_remaining_rows(self) -> None:
        output = self.picker.dispatch(3, ["irrelevant"], {"ROFI_INFO": "STARSHIP"})
        self.assertNotIn("starship  ·", output)
        self.assertIn("snap  ·", output)
        self.assertEqual([h.host for h in self.store.load().hosts], ["snap"])

    def test_custom_key_toggles_and_persists_sort_mode(self) -> None:
        output = self.picker.dispatch(10, [], {})
        self.assertEqual(self.store.load().sort_mode, SORT_RECENCY)
        self.assertIn("\x00use-hot-keys\x1ftrue", output)
        self.assertIn("\x00message\x1fSorted by recency", output)
        self.assertIn("Alt+S toggles order", output)
        self.assertIn("snap  ·", output)

    def test_main_initial_and_callback_protocol(self) -> None:
        root = Path(self.tempdir.name)
        environment = {"XDG_STATE_HOME": str(root), "ROFI_RETV": "0"}
        output = io.StringIO()
        self.assertEqual(main([], environ=environment, stdout=output), 0)
        self.assertIn("\x00prompt\x1fSSH", output.getvalue())
        self.assertEqual(json.loads((root / "rofi-ssh-plus/history.json").read_text())["version"], 1)


if __name__ == "__main__":
    unittest.main()
