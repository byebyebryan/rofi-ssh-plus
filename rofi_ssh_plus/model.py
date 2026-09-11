"""Data-model and destination validation helpers.

The model deliberately contains no Rofi, subprocess, or filesystem code.  It
is consequently safe to use from both the picker process and the detached
worker process.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

# Schema v1 retains this compatibility value in serialized state.  It is not
# an active ordering mode or part of the picker API.
SORT_RECENCY = "recency"


class InvalidDestination(ValueError):
    """Raised when a value cannot safely be used as an SSH destination."""


def normalize_destination(value: str) -> str:
    """Validate and canonicalize a single SSH destination.

    Rofi custom input is user-controlled text.  A destination is passed as
    one argv element to every subprocess, but rejecting whitespace/control
    characters and option-like values still prevents accidental multi-token
    input and accidental SSH option injection.  SSH config aliases, user
    prefixes, bracketed IPv6 literals, and configured port syntax remain
    valid because they contain no shell syntax or additional argv tokens.
    """

    return validate_destination(value).casefold()


def validate_destination(value: str) -> str:
    """Validate one destination while preserving its configured spelling."""

    if not isinstance(value, str):
        raise InvalidDestination("destination must be text")
    if not value or value.strip() != value:
        raise InvalidDestination("destination must not be empty or padded")
    if value.startswith("-"):
        raise InvalidDestination("option-like destinations are not allowed")
    if any(
        char.isspace() or unicodedata.category(char).startswith("C") for char in value
    ):
        raise InvalidDestination(
            "destination must not contain whitespace or control characters"
        )
    return value


@dataclass(frozen=True)
class HostRecord:
    """One successfully reached SSH destination."""

    host: str
    last_connected: int
    count: int

    @property
    def lastConnected(self) -> int:
        """Compatibility spelling used by the DMS state schema."""

        return self.last_connected

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "lastConnected": self.last_connected,
            "count": self.count,
        }


@dataclass(frozen=True)
class HistoryState:
    """Validated generic state loaded from disk."""

    hosts: tuple[HostRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            # Keep the schema-v1 field for rollback compatibility.  It is
            # emitted only when state is written; reads do not rewrite a
            # legacy value merely to normalize this field.
            "sortMode": SORT_RECENCY,
            "hosts": [host.to_dict() for host in self.hosts],
        }
