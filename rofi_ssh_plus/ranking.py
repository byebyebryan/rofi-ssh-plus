"""Deterministic recency ordering and display metadata for history rows."""

from __future__ import annotations

from datetime import datetime, timezone

from .model import HostRecord


def sort_hosts(hosts: list[HostRecord] | tuple[HostRecord, ...]) -> list[HostRecord]:
    """Return hosts newest-first, with count excluded from every tie-break."""

    return sorted(hosts, key=lambda host: (-host.last_connected, host.host))


def format_age(timestamp_ms: int, now_ms: int | None = None) -> str:
    """Format a compact relative age using the DMS picker's vocabulary."""

    if not timestamp_ms:
        return "never"
    if now_ms is None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    seconds = max(0, (now_ms - timestamp_ms) // 1000)
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def connection_label(count: int) -> str:
    return f"{count} connect" if count == 1 else f"{count} connects"


def display_record(record: HostRecord, now_ms: int | None = None) -> str:
    """Render one two-line row while leaving identity to Rofi metadata.

    The first line is always the destination.  The secondary line shows age
    first, followed by the retained connection count.  The protocol adapter
    uses a tab row delimiter, allowing this LF to remain a physical display
    line instead of becoming a new Rofi row.
    """

    age = format_age(record.last_connected, now_ms)
    frequency = connection_label(record.count)
    return f"{record.host}\n{age} · {frequency}"
