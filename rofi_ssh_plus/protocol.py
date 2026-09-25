"""Rofi script-mode rendering and dispatch."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from html import escape

from .launch import spawn_managed_worker, spawn_worker
from .mesh import MeshConfig
from .model import (
    HostRecord,
    InvalidDestination,
    normalize_destination,
)
from .ranking import display_record
from .state import StateStore

ROFI_RETV_CUSTOM_1 = 10
ROFI_RETV_CUSTOM_2 = 11
ROFI_RETV_CUSTOM_3 = 12
ROFI_RETV_CUSTOM_7 = 16
ROFI_RETV_CUSTOM_8 = 17
ROFI_RECORD_SEPARATOR = "\t"
ROFI_DELIMITER_VALUE = r"\t"

ACTION_CONNECT = "connect"
ACTION_FORGET = "forget"
ACTION_ORDER = (ACTION_CONNECT, ACTION_FORGET)
ACTION_DATA_VERSION = 1
ROW_INFO_VERSION = 1

_INVALID_STATE = object()


def _valid_version(value: object, expected: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


def _option(key: str, value: str) -> str:
    return "\x00" + key + "\x1f" + value


def _row(
    text: str,
    *,
    display: str | None = None,
    info: str | None = None,
    meta: str | None = None,
    nonselectable: bool = False,
) -> str:
    parts = [text]
    if display is not None:
        parts.append(_option("display", display))
    if info is not None:
        parts.append(_option("info", info))
    if meta is not None:
        parts.append(_option("meta", meta))
    if nonselectable:
        parts.append(_option("nonselectable", "true"))
    return "".join(parts)


def _action_data(action: str) -> str:
    """Serialize one stable action name for Rofi's continuation channel."""

    if action not in ACTION_ORDER:
        raise ValueError("unknown SSH picker action")
    return json.dumps(
        {"version": ACTION_DATA_VERSION, "action": action},
        ensure_ascii=True,
        separators=(",", ":"),
    )


def _parse_action_data(value: object) -> str | object:
    """Parse untrusted ``ROFI_DATA`` without choosing a fallback action."""

    if not isinstance(value, str) or not value:
        return _INVALID_STATE
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _INVALID_STATE
    if not isinstance(payload, dict):
        return _INVALID_STATE
    if set(payload) != {"version", "action"}:
        return _INVALID_STATE
    if not _valid_version(payload["version"], ACTION_DATA_VERSION):
        return _INVALID_STATE
    action = payload.get("action")
    if not isinstance(action, str) or action not in ACTION_ORDER:
        return _INVALID_STATE
    return action


def _row_info(row_key: str) -> str:
    """Serialize a typed row identity for ``ROFI_INFO``."""

    return json.dumps(
        {"version": ROW_INFO_VERSION, "kind": "host", "id": row_key},
        ensure_ascii=True,
        separators=(",", ":"),
    )


def _parse_row_info(value: object) -> str | object:
    """Parse the canonical host identity carried by a selected row."""

    if not isinstance(value, str) or not value:
        return _INVALID_STATE
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _INVALID_STATE
    if not isinstance(payload, dict):
        return _INVALID_STATE
    if set(payload) != {"version", "kind", "id"}:
        return _INVALID_STATE
    if not _valid_version(payload["version"], ROW_INFO_VERSION):
        return _INVALID_STATE
    if payload.get("kind") != "host":
        return _INVALID_STATE
    try:
        return normalize_destination(payload.get("id"))
    except (InvalidDestination, TypeError):
        return _INVALID_STATE


@dataclass
class Picker:
    store: StateStore
    worker_launcher: Callable[[str], bool] = spawn_worker
    now_ms: int | None = None
    mesh: MeshConfig | None = None
    managed_worker_launcher: Callable[[str], bool] = spawn_managed_worker

    def __post_init__(self) -> None:
        if self.mesh is not None and self.store.mesh is None:
            self.store.mesh = self.mesh

    def render(
        self,
        *,
        initial: bool = True,
        keep_filter: bool = False,
        keep_selection: bool = False,
        selected_identity: str | None = None,
        action: str = ACTION_CONNECT,
        notice: str = "",
    ) -> str:
        if action not in ACTION_ORDER:
            action = ACTION_CONNECT
        state = self.store.load()
        headers = [
            _option("use-hot-keys", "true"),
            _option("no-custom", "true"),
            _option("prompt", self._prompt()),
            _option("message", self._message(action, notice)),
            _option("data", _action_data(action)),
        ]
        if keep_filter:
            headers.append(_option("keep-filter", "true"))
        if keep_selection:
            headers.append(_option("keep-selection", "true"))
        rendered_rows: list[str] = []
        ordered = self._sort_rows(self._rows(state.hosts))
        if keep_selection and selected_identity is not None:
            for index, row in enumerate(ordered):
                if row.key == selected_identity:
                    headers.append(_option("new-selection", str(index)))
                    break
        if ordered:
            for row in ordered:
                record = HostRecord(row.key, row.last_connected, row.count)
                shown = display_record(record, now_ms=self.now_ms)
                if row.display != row.key:
                    details = shown.split("\n", 1)[1]
                    shown = f"{row.display}\n{details}"
                rendered_rows.append(
                    _row(
                        row.display,
                        display=shown,
                        info=_row_info(row.key),
                        meta=row.key,
                    )
                )
        else:
            rendered_rows.append(
                _row(
                    "No verified SSH hosts yet",
                    display="No listed SSH hosts yet",
                    meta="no listed hosts",
                    nonselectable=True,
                )
            )
        # A literal LF in ``display`` is a physical second line.  On the first
        # call, declare a tab record delimiter while Rofi still expects the
        # default LF.  Rofi remembers that delimiter, so callback headers and
        # rows must all use tabs and must not redeclare it.
        if initial:
            headers.append(_option("delim", ROFI_DELIMITER_VALUE))
            return (
                "\n".join(headers)
                + "\n"
                + ROFI_RECORD_SEPARATOR.join(rendered_rows)
                + ROFI_RECORD_SEPARATOR
            )
        return (
            ROFI_RECORD_SEPARATOR.join([*headers, *rendered_rows])
            + ROFI_RECORD_SEPARATOR
        )

    @staticmethod
    def _prompt() -> str:
        return "SSH"

    @staticmethod
    def _action_label(action: str) -> str:
        return {
            ACTION_CONNECT: "Connect",
            ACTION_FORGET: "Forget recent history",
        }.get(action, "Connect")

    @classmethod
    def _message(cls, action: str, notice: str = "") -> str:
        labels = []
        for candidate in ACTION_ORDER:
            label = escape(cls._action_label(candidate), quote=False)
            if candidate == action:
                color = "#ffb74d" if candidate == ACTION_FORGET else "#42a5f5"
                label = f'<span foreground="{color}" weight="bold">[{label}]</span>'
            labels.append(label)
        hint = f"Enter: {' · '.join(labels)}\u2028Tab: Cycle actions"
        if not notice:
            return hint
        safe_notice = "".join(
            " " if ord(char) < 32 or char in "\x7f\u0085\u2028\u2029" else char
            for char in notice
        ).strip()
        return f"{hint}\u2028{escape(safe_notice, quote=False)}"

    @dataclass(frozen=True)
    class _Row:
        key: str
        display: str
        last_connected: int
        count: int
        declaration_index: int
        managed: bool

    def _rows(self, records: Sequence[HostRecord]) -> list[_Row]:
        if self.mesh is None:
            return [
                self._Row(
                    record.host,
                    record.host,
                    record.last_connected,
                    record.count,
                    index,
                    False,
                )
                for index, record in enumerate(records)
            ]
        managed_usage: dict[str, HostRecord] = {}
        ad_hoc: list[HostRecord] = []
        for record in records:
            resolved = self.mesh.resolve_token(record.host)
            if resolved is not None and not resolved.local:
                existing = managed_usage.get(resolved.id)
                if existing is None:
                    managed_usage[resolved.id] = HostRecord(
                        resolved.id,
                        record.last_connected,
                        record.count,
                    )
                else:
                    managed_usage[resolved.id] = HostRecord(
                        resolved.id,
                        max(existing.last_connected, record.last_connected),
                        existing.count + record.count,
                    )
            else:
                ad_hoc.append(record)
        rows: list[Picker._Row] = []
        managed_keys: set[str] = set()
        for declaration_index, host in enumerate(self.mesh.remote_hosts):
            record = managed_usage.get(host.id)
            rows.append(
                self._Row(
                    host.id,
                    host.display,
                    record.last_connected if record is not None else 0,
                    record.count if record is not None else 0,
                    declaration_index,
                    True,
                )
            )
            managed_keys.add(host.id)
        for index, record in enumerate(ad_hoc):
            if record.host in managed_keys:
                continue
            rows.append(
                self._Row(
                    record.host,
                    record.host,
                    record.last_connected,
                    record.count,
                    len(self.mesh.remote_hosts) + index,
                    False,
                )
            )
        return rows

    @staticmethod
    def _sort_rows(rows: Sequence[_Row]) -> list[_Row]:
        def key(row: Picker._Row) -> tuple[object, ...]:
            if row.last_connected:
                # Recency is the only primary ordering.  Declaration order is
                # a stable tie-break for managed hosts; display/key completes
                # the deterministic order for ad-hoc destinations.
                return (
                    0,
                    -row.last_connected,
                    row.declaration_index if row.managed else len(rows),
                    row.display.casefold(),
                    row.key,
                )
            # Never-used managed hosts retain Host Mesh declaration order and
            # remain after every used destination.
            if row.managed:
                return (1, 0, row.declaration_index, row.display.casefold(), row.key)
            return (1, 1, 0, row.display.casefold(), row.key)

        return sorted(rows, key=key)

    def dispatch(
        self, retv: int, argv: Sequence[str], env: Mapping[str, str] | None = None
    ) -> str:
        """Handle one Rofi callback and return the next script output."""

        environ = os.environ if env is None else env
        action, action_valid = self._continuation_action(environ)

        if retv in (ROFI_RETV_CUSTOM_7, ROFI_RETV_CUSTOM_8):
            if not action_valid:
                return self.render(
                    initial=False,
                    keep_filter=True,
                    keep_selection=True,
                    selected_identity=self._selected_identity(environ),
                    action=ACTION_CONNECT,
                    notice="Invalid SSH action state; choose Connect and try again.",
                )
            direction = 1 if retv == ROFI_RETV_CUSTOM_7 else -1
            next_action = self._cycle_action(action, direction)
            return self.render(
                initial=False,
                keep_filter=True,
                keep_selection=True,
                selected_identity=self._selected_identity(environ),
                action=next_action,
            )

        if retv in (
            2,
            3,
            ROFI_RETV_CUSTOM_1,
            ROFI_RETV_CUSTOM_2,
            ROFI_RETV_CUSTOM_3,
        ):
            notice = {
                2: "Custom destinations are disabled; select a listed host and press Enter.",
                3: "Delete is unavailable; use Tab to choose Forget recent history.",
            }.get(
                retv,
                "This SSH callback is retired; use Tab to choose an action.",
            )
            if not action_valid:
                action = ACTION_CONNECT
                notice = "Invalid SSH action state; " + notice
            return self.render(
                initial=False,
                keep_filter=True,
                keep_selection=True,
                selected_identity=self._selected_identity(environ),
                action=action,
                notice=notice,
            )

        if retv == 1:
            if not action_valid:
                return self.render(
                    initial=False,
                    keep_filter=True,
                    keep_selection=True,
                    selected_identity=self._selected_identity(environ),
                    action=ACTION_CONNECT,
                    notice="Invalid SSH action state; choose Connect and try again.",
                )
            row = self._selected_row(environ)
            if row is None:
                return self.render(
                    initial=False,
                    keep_filter=True,
                    keep_selection=True,
                    selected_identity=self._selected_identity(environ),
                    action=action,
                    notice="Select a listed SSH host first.",
                )
            if action == ACTION_CONNECT:
                notice = ""
                try:
                    launched = self._launch_row(row)
                except (OSError, RuntimeError, ValueError) as exc:
                    launched = False
                    notice = f"Unable to connect to {row.key}: {exc}"
                if launched:
                    return ""
                return self.render(
                    initial=False,
                    keep_filter=True,
                    keep_selection=True,
                    selected_identity=row.key,
                    action=action,
                    notice=notice or f"Unable to connect to {row.key}.",
                )
            return self._forget_row(row)
        return self.render(initial=retv == 0)

    @staticmethod
    def _cycle_action(action: str, direction: int) -> str:
        index = ACTION_ORDER.index(action)
        return ACTION_ORDER[(index + direction) % len(ACTION_ORDER)]

    @staticmethod
    def _continuation_action(env: Mapping[str, str]) -> tuple[str, bool]:
        if "ROFI_DATA" not in env:
            return ACTION_CONNECT, True
        action = _parse_action_data(env.get("ROFI_DATA"))
        if action is _INVALID_STATE:
            return ACTION_CONNECT, False
        assert isinstance(action, str)
        return action, True

    def _selected_row(self, env: Mapping[str, str]) -> _Row | None:
        value = self._selected_identity(env)
        if value is None:
            return None
        state = self.store.load()
        for row in self._rows(state.hosts):
            if row.key == value:
                return row
        return None

    @staticmethod
    def _selected_identity(env: Mapping[str, str]) -> str | None:
        value = _parse_row_info(env.get("ROFI_INFO"))
        if value is _INVALID_STATE:
            return None
        assert isinstance(value, str)
        return value

    def _launch_row(self, row: _Row) -> bool:
        resolved = self.mesh.resolve_token(row.key) if self.mesh is not None else None
        if resolved is not None:
            if resolved.local:
                return False
            return bool(self.managed_worker_launcher(resolved.id))
        return bool(self.worker_launcher(row.key))

    def _forget_row(self, row: _Row) -> str:
        try:
            resolved = self.mesh.resolve_token(row.key) if self.mesh is not None else None
            target = (
                resolved.id
                if resolved is not None and not resolved.local
                else row.key
            )
            removed, _ = self.store.remove(target)
        except (InvalidDestination, OSError, RuntimeError, ValueError) as exc:
            return self.render(
                initial=False,
                keep_filter=True,
                keep_selection=True,
                selected_identity=row.key,
                action=ACTION_CONNECT,
                notice=f"Unable to forget {row.key}: {exc}",
            )
        if removed:
            notice = f"Forgot recent history for {row.key}."
        else:
            notice = f"No recent history for {row.key}."
        return self.render(
            initial=False,
            keep_filter=True,
            keep_selection=True,
            selected_identity=row.key,
            action=ACTION_CONNECT,
            notice=notice,
        )
