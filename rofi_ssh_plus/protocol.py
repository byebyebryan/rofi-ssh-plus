"""Rofi script-mode rendering and dispatch."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from .launch import spawn_managed_worker, spawn_worker
from .mesh import MeshConfig
from .model import (
    SORT_FREQUENCY,
    SORT_RECENCY,
    HostRecord,
    InvalidDestination,
    normalize_destination,
)
from .ranking import display_record
from .state import StateStore

ROFI_RETV_CUSTOM_1 = 10
ROFI_RETV_CUSTOM_2 = 11
ROFI_RETV_CUSTOM_3 = 12
ROFI_RECORD_SEPARATOR = "\t"
ROFI_DELIMITER_VALUE = r"\t"
SORT_MODE_LABELS = {
    SORT_FREQUENCY: "Frequent",
    SORT_RECENCY: "Recent",
}


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

    def render(self, *, initial: bool = True) -> str:
        state = self.store.load()
        headers = [
            _option("use-hot-keys", "true"),
            _option(
                "prompt", f"SSH › {SORT_MODE_LABELS.get(state.sort_mode, 'Frequent')}"
            ),
        ]
        rendered_rows: list[str] = []
        ordered = self._sort_rows(self._rows(state.hosts), state.sort_mode)
        if ordered:
            for row in ordered:
                record = HostRecord(row.key, row.last_connected, row.count)
                shown = display_record(record, state.sort_mode, self.now_ms)
                if row.display != row.key:
                    details = shown.split("\n", 1)[1]
                    shown = f"{row.display}\n{details}"
                rendered_rows.append(
                    _row(row.display, display=shown, info=row.key, meta=row.key)
                )
        else:
            rendered_rows.append(
                _row(
                    "No verified SSH hosts yet",
                    display="No verified SSH hosts yet — type a host and press Ctrl+Enter",
                    meta="type a host",
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
    def _sort_rows(rows: Sequence[_Row], sort_mode: str) -> list[_Row]:
        if sort_mode == SORT_RECENCY:
            return sorted(
                rows,
                key=lambda row: (
                    0 if row.last_connected else 1,
                    -row.last_connected,
                    -row.count,
                    row.declaration_index
                    if row.managed and not row.last_connected
                    else 0,
                    row.display.casefold(),
                    row.key,
                ),
            )
        return sorted(
            rows,
            key=lambda row: (
                -row.count,
                -row.last_connected,
                row.display.casefold(),
                row.key,
            ),
        )

    def dispatch(
        self, retv: int, argv: Sequence[str], env: Mapping[str, str] | None = None
    ) -> str:
        """Handle one Rofi callback and return the next script output."""

        environ = os.environ if env is None else env
        if retv in (ROFI_RETV_CUSTOM_1, ROFI_RETV_CUSTOM_2, ROFI_RETV_CUSTOM_3):
            if retv == ROFI_RETV_CUSTOM_1:
                self.store.toggle_sort_mode()
            elif retv == ROFI_RETV_CUSTOM_2:
                self.store.cycle_sort_mode(1)
            else:
                self.store.cycle_sort_mode(-1)
            return self.render(initial=False)

        value = self._callback_value(retv, argv, environ)
        if retv == 1:
            if value:
                self._launch_if_valid(value)
            return ""
        if retv == 2:
            if value:
                self._launch_if_valid(value)
            return ""
        if retv == 3:
            if value:
                try:
                    resolved = (
                        self.mesh.resolve_token(value)
                        if self.mesh is not None
                        else None
                    )
                    self.store.remove(
                        resolved.id
                        if resolved is not None and not resolved.local
                        else value
                    )
                except InvalidDestination:
                    pass
            return self.render(initial=False)
        return self.render(initial=retv == 0)

    @staticmethod
    def _callback_value(retv: int, argv: Sequence[str], env: Mapping[str, str]) -> str:
        if retv in (1, 3):
            return env.get("ROFI_INFO", "") or (argv[0] if argv else "")
        # Rofi 2.0 passes custom input as argv[1] in script mode.  Newer
        # builds may additionally expose ROFI_INPUT; the argv value remains
        # authoritative when present.
        return (argv[0] if argv else "") or env.get("ROFI_INPUT", "")

    def _launch_if_valid(self, value: str) -> bool:
        try:
            host = normalize_destination(value)
        except InvalidDestination:
            return False
        resolved = self.mesh.resolve_token(host) if self.mesh is not None else None
        if resolved is not None and not resolved.local:
            return self.managed_worker_launcher(resolved.id)
        return self.worker_launcher(host)
