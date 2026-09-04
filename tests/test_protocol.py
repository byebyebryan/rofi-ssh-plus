from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from rofi_ssh_plus.cli import main
from rofi_ssh_plus.model import HostRecord, SORT_FREQUENCY, SORT_RECENCY
from rofi_ssh_plus.protocol import (
    ROFI_DELIMITER_VALUE,
    Picker,
)
from rofi_ssh_plus.state import StateStore


class ProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.store = StateStore(root / "history.json", root / "legacy.json")
        self.store.record_success("alpha", now_ms=1_000)
        self.store.record_success("alpha", now_ms=2_000)
        self.store.record_success("beta", now_ms=3_000)
        self.launched: list[str] = []
        self.picker = Picker(self.store, worker_launcher=lambda host: self.launched.append(host) or True, now_ms=4_000)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_render_has_dynamic_prompt_two_line_rows_raw_info_and_metadata(self) -> None:
        output = self.picker.render()
        self.assertIn("\x00use-hot-keys\x1ftrue", output)
        self.assertIn("\x00prompt\x1fSSH › Frequent", output)
        self.assertNotIn("\x00message\x1f", output)
        self.assertIn(f"\x00delim\x1f{ROFI_DELIMITER_VALUE}\n", output)
        self.assertIn("\x00display\x1falpha\n2 connects · just now", output)
        self.assertIn("\x00info\x1falpha", output)
        self.assertIn("\x00meta\x1falpha", output)

        delimiter = f"\x00delim\x1f{ROFI_DELIMITER_VALUE}\n"
        _, records = output.split(delimiter, 1)
        self.assertEqual(2, len(records.removesuffix("\t").split("\t")))

    def test_selected_uses_rofi_info_and_custom_uses_argv_then_rofi_input(self) -> None:
        self.assertEqual(self.picker.dispatch(1, ["decorated display"], {"ROFI_INFO": "Alpha"}), "")
        self.assertEqual(self.launched, ["alpha"])
        self.assertEqual(self.picker.dispatch(2, ["NewHost"], {}), "")
        self.assertEqual(self.launched, ["alpha", "newhost"])
        self.assertEqual(self.picker.dispatch(2, [], {"ROFI_INPUT": "InputHost"}), "")
        self.assertEqual(self.launched, ["alpha", "newhost", "inputhost"])

    def test_invalid_custom_input_is_not_launched(self) -> None:
        for value in ("", "host name", "-oBad"):
            self.picker.dispatch(2, [value], {})
        self.assertEqual(self.launched, [])

    def test_delete_uses_info_and_renders_remaining_rows(self) -> None:
        output = self.picker.dispatch(3, ["irrelevant"], {"ROFI_INFO": "ALPHA"})
        self.assertNotIn("alpha\n", output)
        self.assertIn("beta\n", output)
        self.assertEqual([h.host for h in self.store.load().hosts], ["beta"])

    def test_right_and_left_cycle_lenses_with_wrap_and_persistence(self) -> None:
        output = ""
        for retv, expected_mode, expected_prompt in (
            (11, SORT_RECENCY, "SSH › Recent"),
            (11, SORT_FREQUENCY, "SSH › Frequent"),
            (12, SORT_RECENCY, "SSH › Recent"),
            (12, SORT_FREQUENCY, "SSH › Frequent"),
        ):
            with self.subTest(retv=retv, expected_mode=expected_mode):
                output = self.picker.dispatch(retv, [], {})
                self.assertEqual(self.store.load().sort_mode, expected_mode)
                self.assertIn(f"\x00prompt\x1f{expected_prompt}", output)
                self.assertNotIn("\x00keep-filter\x1ftrue", output)
                self.assertNotIn("\x00keep-selection\x1ftrue", output)

        self.assertIn("\x00display\x1fbeta\n1 connect · just now", output)
        self.assertNotIn("\x00delim\x1f", output)
        self.assertTrue(output.startswith("\x00use-hot-keys\x1ftrue\t\x00prompt\x1f"))

    def test_alt_s_remains_compatibility_alias_for_switching_lens(self) -> None:
        output = self.picker.dispatch(10, [], {})
        self.assertEqual(self.store.load().sort_mode, SORT_RECENCY)
        self.assertIn("\x00use-hot-keys\x1ftrue", output)
        self.assertIn("\x00prompt\x1fSSH › Recent", output)
        self.assertNotIn("Sorted by", output)
        self.assertIn("beta\n", output)

    def test_empty_state_keeps_typed_destination_guidance_clear(self) -> None:
        root = Path(self.tempdir.name) / "empty"
        picker = Picker(StateStore(root / "history.json", root / "legacy.json"))
        output = picker.render()
        self.assertIn("SSH › Frequent", output)
        self.assertIn("No verified SSH hosts yet", output)
        self.assertIn("type a host and press Ctrl+Enter", output)

    def test_main_initial_and_callback_protocol(self) -> None:
        root = Path(self.tempdir.name)
        environment = {"XDG_STATE_HOME": str(root), "ROFI_RETV": "0"}
        output = io.StringIO()
        self.assertEqual(main([], environ=environment, stdout=output), 0)
        self.assertIn("\x00prompt\x1fSSH", output.getvalue())
        self.assertEqual(json.loads((root / "rofi-ssh-plus/history.json").read_text())["version"], 1)


if __name__ == "__main__":
    unittest.main()
