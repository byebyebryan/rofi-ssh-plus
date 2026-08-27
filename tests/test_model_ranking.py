from __future__ import annotations

import unittest

from rofi_ssh_plus.model import HostRecord, InvalidDestination, SORT_FREQUENCY, SORT_RECENCY, normalize_destination
from rofi_ssh_plus.ranking import display_record, format_age, sort_hosts


class DestinationTests(unittest.TestCase):
    def test_normalizes_case_insensitively(self) -> None:
        self.assertEqual(normalize_destination("User@Host.Example"), "user@host.example")
        self.assertEqual(normalize_destination("[2001:db8::1]"), "[2001:db8::1]")

    def test_rejects_empty_whitespace_control_and_option_values(self) -> None:
        for value in ("", " host", "host ", "host name", "host\nname", "host\x00name", "host\u202e", "-oProxyCommand=bad"):
            with self.subTest(value=value):
                with self.assertRaises(InvalidDestination):
                    normalize_destination(value)


class RankingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hosts = [
            HostRecord("zulu", 100, 2),
            HostRecord("alpha", 300, 2),
            HostRecord("bravo", 400, 1),
            HostRecord("charlie", 500, 1),
        ]

    def test_frequency_uses_count_then_timestamp_then_name(self) -> None:
        self.assertEqual([h.host for h in sort_hosts(self.hosts, SORT_FREQUENCY)], ["alpha", "zulu", "charlie", "bravo"])

    def test_recency_uses_timestamp_then_count_then_name(self) -> None:
        self.assertEqual([h.host for h in sort_hosts(self.hosts, SORT_RECENCY)], ["charlie", "bravo", "alpha", "zulu"])

    def test_relative_age_and_metadata_are_deterministic(self) -> None:
        now = 3_600_000
        self.assertEqual(format_age(3_599_000, now), "just now")
        self.assertEqual(format_age(3_540_000, now), "1m ago")
        self.assertEqual(format_age(0, now), "never")
        shown = display_record(HostRecord("alpha", 3_540_000, 2), SORT_FREQUENCY, now)
        self.assertEqual(shown, "alpha  ·  2 connects · 1m ago")


if __name__ == "__main__":
    unittest.main()
