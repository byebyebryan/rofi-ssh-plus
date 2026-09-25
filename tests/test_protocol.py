from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from rofi_ssh_plus.cli import main
from rofi_ssh_plus.protocol import (
    ACTION_CONNECT,
    ACTION_FORGET,
    ROFI_DELIMITER_VALUE,
    ROFI_RETV_CUSTOM_7,
    ROFI_RETV_CUSTOM_8,
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
        self.picker = Picker(
            self.store,
            worker_launcher=lambda host: self.launched.append(host) or True,
            now_ms=4_000,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def row_info(host: str) -> str:
        return json.dumps(
            {"version": 1, "kind": "host", "id": host},
            separators=(",", ":"),
        )

    @staticmethod
    def action_data(action: str) -> str:
        return json.dumps(
            {"version": 1, "action": action},
            separators=(",", ":"),
        )

    def test_render_has_action_hint_typed_info_and_two_line_rows(
        self,
    ) -> None:
        output = self.picker.render()
        self.assertIn("\x00use-hot-keys\x1ftrue", output)
        self.assertIn("\x00no-custom\x1ftrue", output)
        self.assertIn("\x00prompt\x1fSSH\n", output)
        self.assertIn('Enter: <span foreground="#42a5f5" weight="bold">[Connect]</span> · Forget recent history  │  Tab: Cycle actions', output)
        self.assertNotIn("Shift+Tab:", output)
        self.assertIn(f'\x00data\x1f{self.action_data(ACTION_CONNECT)}', output)
        self.assertNotIn("Frequent", output)
        self.assertNotIn("Recent", output)
        self.assertNotIn("\x00keep-filter\x1ftrue", output)
        self.assertNotIn("\x00keep-selection\x1ftrue", output)
        self.assertIn(f"\x00delim\x1f{ROFI_DELIMITER_VALUE}\n", output)
        self.assertIn("\x00display\x1falpha\njust now · 2 connects", output)
        self.assertIn(
            f'\x00info\x1f{self.row_info("alpha")}',
            output,
        )
        self.assertIn("\x00meta\x1falpha", output)

        delimiter = f"\x00delim\x1f{ROFI_DELIMITER_VALUE}\n"
        _, records = output.split(delimiter, 1)
        self.assertEqual(2, len(records.removesuffix("\t").split("\t")))

    def test_action_notice_is_escaped_for_rofi_message_markup(self) -> None:
        message = self.picker._message(ACTION_CONNECT, "host <alpha> & beta\u2028next")
        self.assertIn("Tab: Cycle actions\u2028\u2028host &lt;alpha&gt; &amp; beta next", message)
        self.assertNotIn("host <alpha>", message)

    def test_selected_uses_typed_rofi_info_and_custom_input_cannot_connect(self) -> None:
        self.assertEqual(
            self.picker.dispatch(
                1,
                ["decorated display"],
                {"ROFI_INFO": self.row_info("Alpha")},
            ),
            "",
        )
        self.assertEqual(self.launched, ["alpha"])
        output = self.picker.dispatch(2, ["NewHost"], {})
        self.assertIn("Custom destinations are disabled", output)
        self.assertEqual(self.launched, ["alpha"])
        output = self.picker.dispatch(2, [], {"ROFI_INPUT": "InputHost"})
        self.assertIn("Custom destinations are disabled", output)
        self.assertEqual(self.launched, ["alpha"])

    def test_invalid_custom_input_is_not_launched(self) -> None:
        for value in ("", "host name", "-oBad"):
            self.picker.dispatch(2, [value], {})
        self.assertEqual(self.launched, [])

    def test_failed_connect_launcher_keeps_row_and_reports_notice(self) -> None:
        picker = Picker(
            self.store,
            worker_launcher=lambda _host: False,
            now_ms=4_000,
        )
        output = picker.dispatch(
            1,
            [],
            {"ROFI_INFO": self.row_info("alpha")},
        )
        self.assertIn("Unable to connect to alpha.", output)
        self.assertIn("\x00keep-filter\x1ftrue", output)
        self.assertIn("\x00keep-selection\x1ftrue", output)
        self.assertIn("\x00new-selection\x1f1", output)
        self.assertIn("\x00display\x1falpha\n", output)

    def test_forget_uses_current_typed_selection_and_renders_remaining_rows(self) -> None:
        output = self.picker.dispatch(
            1,
            ["irrelevant"],
            {
                "ROFI_DATA": self.action_data(ACTION_FORGET),
                "ROFI_INFO": self.row_info("ALPHA"),
            },
        )
        self.assertNotIn("\talpha\x00display", output)
        self.assertIn("beta\n", output)
        self.assertIn("\x00prompt\x1fSSH\t", output)
        self.assertIn("[Connect]</span> · Forget recent history  │  Tab: Cycle actions\u2028\u2028Forgot recent history for alpha", output)
        self.assertNotIn("\x00new-selection\x1f", output)
        self.assertEqual([h.host for h in self.store.load().hosts], ["beta"])

    def test_action_cycle_wraps_and_preserves_filter_and_selection(self) -> None:
        before = self.store.path.read_bytes()
        output = self.picker.dispatch(
            ROFI_RETV_CUSTOM_7,
            [],
            {
                "ROFI_DATA": self.action_data(ACTION_CONNECT),
                "ROFI_INFO": self.row_info("alpha"),
            },
        )
        self.assertIn("\x00prompt\x1fSSH\t", output)
        self.assertIn('Connect · <span foreground="#ffb74d" weight="bold">[Forget recent history]</span>', output)
        self.assertIn(f'\x00data\x1f{self.action_data(ACTION_FORGET)}', output)
        self.assertIn("\x00keep-filter\x1ftrue", output)
        self.assertIn("\x00keep-selection\x1ftrue", output)
        self.assertIn("\x00new-selection\x1f1", output)
        self.assertEqual(self.store.path.read_bytes(), before)

        output = self.picker.dispatch(
            ROFI_RETV_CUSTOM_8,
            [],
            {"ROFI_DATA": self.action_data(ACTION_FORGET)},
        )
        self.assertIn("\x00prompt\x1fSSH\t", output)
        self.assertIn('Enter: <span foreground="#42a5f5" weight="bold">[Connect]</span>', output)
        self.assertIn(f'\x00data\x1f{self.action_data(ACTION_CONNECT)}', output)
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_action_cycle_recomputes_selection_after_recency_reorder(self) -> None:
        # beta is initially first. A concurrent success moves alpha ahead of
        # it before the Tab callback; the typed identity must still select beta.
        self.store.record_success("alpha", now_ms=5_000)
        output = self.picker.dispatch(
            ROFI_RETV_CUSTOM_7,
            [],
            {
                "ROFI_DATA": self.action_data(ACTION_CONNECT),
                "ROFI_INFO": self.row_info("beta"),
            },
        )
        self.assertIn("\x00keep-filter\x1ftrue", output)
        self.assertIn("\x00keep-selection\x1ftrue", output)
        self.assertIn("\x00new-selection\x1f1", output)
        self.assertIn("\x00display\x1falpha\n", output)
        self.assertIn("\x00display\x1fbeta\n", output)

    def test_forget_uses_row_selected_at_enter_not_tab(self) -> None:
        self.picker.dispatch(
            ROFI_RETV_CUSTOM_7,
            [],
            {
                "ROFI_DATA": self.action_data(ACTION_CONNECT),
                "ROFI_INFO": self.row_info("alpha"),
            },
        )
        output = self.picker.dispatch(
            1,
            [],
            {
                "ROFI_DATA": self.action_data(ACTION_FORGET),
                "ROFI_INFO": self.row_info("beta"),
            },
        )
        self.assertIn("Forgot recent history for beta", output)
        self.assertEqual([host.host for host in self.store.load().hosts], ["alpha"])

    def test_malformed_action_data_blocks_enter_with_visible_error(self) -> None:
        before = self.store.path.read_bytes()
        for data in (
            '{"version":1,"action":"retired"}',
            '{"action":"forget"}',
        ):
            output = self.picker.dispatch(
                1,
                [],
                {"ROFI_DATA": data, "ROFI_INFO": self.row_info("alpha")},
            )
            self.assertIn("Invalid SSH action state", output)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.launched, [])

    def test_untyped_or_unlisted_info_cannot_become_a_destination(self) -> None:
        before = self.store.path.read_bytes()
        for info in (
            "alpha",
            self.row_info("not-listed"),
            '{"kind":"host","id":"alpha"}',
        ):
            output = self.picker.dispatch(1, ["alpha"], {"ROFI_INFO": info})
            self.assertIn("Select a listed SSH host first", output)
            self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.launched, [])

    def test_retired_input_and_delete_callbacks_are_visible_noops(self) -> None:
        before = self.store.path.read_bytes()
        for retv in (2, 3):
            output = self.picker.dispatch(
                retv,
                ["new-host"],
                {
                    "ROFI_DATA": self.action_data(ACTION_FORGET),
                    "ROFI_INFO": self.row_info("alpha"),
                },
            )
            self.assertIn("\x00message\x1f", output)
            self.assertIn("\x00keep-filter\x1ftrue", output)
            self.assertIn("\x00keep-selection\x1ftrue", output)
            self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.launched, [])

    def test_legacy_lens_callbacks_are_byte_preserving_until_real_mutation(
        self,
    ) -> None:
        # Keep the exact v1 bytes in recency order so the only discrepancy is
        # the retired sortMode field.  Legacy callbacks must not rewrite it.
        before = (
            b'{"version":1,"sortMode":"frequency","hosts":['
            b'{"host":"beta","lastConnected":3000,"count":1},'
            b'{"host":"alpha","lastConnected":2000,"count":2}]}'
            b"\n"
        )
        self.store.path.write_bytes(before)
        for retv in (10, 11, 12):
            output = self.picker.dispatch(retv, [], {})
            self.assertEqual(self.store.path.read_bytes(), before)
            self.assertIn("\x00prompt\x1fSSH", output)
            self.assertIn("\x00no-custom\x1ftrue", output)
            self.assertIn("\x00keep-filter\x1ftrue", output)
            self.assertIn("\x00keep-selection\x1ftrue", output)
            self.assertIn(f'\x00data\x1f{self.action_data(ACTION_CONNECT)}', output)
            self.assertNotIn("Frequent", output)
            self.assertNotIn("Recent", output)
            self.assertNotIn("\x00delim\x1f", output)
            self.assertTrue(
                output.startswith(
                    "\x00use-hot-keys\x1ftrue\t\x00no-custom\x1ftrue\t\x00prompt\x1f"
                )
            )

        self.assertIn("\x00display\x1fbeta\njust now · 1 connect", output)

        state = self.store.record_success("alpha", now_ms=5_000)
        self.assertEqual(
            [(host.host, host.last_connected, host.count) for host in state.hosts],
            [("alpha", 5_000, 3), ("beta", 3_000, 1)],
        )
        persisted = json.loads(self.store.path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["sortMode"], "recency")
        self.assertEqual(
            persisted["hosts"],
            [
                {"host": "alpha", "lastConnected": 5_000, "count": 3},
                {"host": "beta", "lastConnected": 3_000, "count": 1},
            ],
        )

    def test_legacy_callback_recomputes_selection_after_recency_reorder(self) -> None:
        self.store.record_success("alpha", now_ms=5_000)
        output = self.picker.dispatch(
            10,
            [],
            {
                "ROFI_INFO": self.row_info("beta"),
                "ROFI_DATA": self.action_data(ACTION_CONNECT),
            },
        )
        self.assertIn("\x00keep-filter\x1ftrue", output)
        self.assertIn("\x00keep-selection\x1ftrue", output)
        self.assertIn("\x00new-selection\x1f1", output)

    def test_empty_state_has_no_custom_destination_guidance(self) -> None:
        root = Path(self.tempdir.name) / "empty"
        picker = Picker(StateStore(root / "history.json", root / "legacy.json"))
        output = picker.render()
        self.assertIn("\x00prompt\x1fSSH", output)
        self.assertNotIn("Frequent", output)
        self.assertNotIn("Recent", output)
        self.assertIn("No verified SSH hosts yet", output)
        self.assertIn("No listed SSH hosts yet", output)
        self.assertNotIn("Ctrl+Enter", output)

    def test_main_initial_and_callback_protocol(self) -> None:
        root = Path(self.tempdir.name)
        environment = {"XDG_STATE_HOME": str(root), "ROFI_RETV": "0"}
        output = io.StringIO()
        self.assertEqual(main([], environ=environment, stdout=output), 0)
        self.assertIn("\x00prompt\x1fSSH", output.getvalue())
        self.assertEqual(
            json.loads((root / "rofi-ssh-plus/history.json").read_text())["version"], 1
        )


if __name__ == "__main__":
    unittest.main()
