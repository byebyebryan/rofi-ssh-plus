"""Rofi script-mode rendering and dispatch."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .launch import spawn_worker
from .model import (
    InvalidDestination,
    SORT_FREQUENCY,
    SORT_RECENCY,
    normalize_destination,
)
from .ranking import display_record, sort_hosts
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


def _row(text: str, *, display: str | None = None, info: str | None = None, meta: str | None = None, nonselectable: bool = False) -> str:
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

    def render(self, *, initial: bool = True) -> str:
        state = self.store.load()
        headers = [
            _option("use-hot-keys", "true"),
            _option("prompt", f"SSH › {SORT_MODE_LABELS.get(state.sort_mode, 'Frequent')}"),
        ]
        rendered_rows: list[str] = []
        ordered = sort_hosts(state.hosts, state.sort_mode)
        if ordered:
            for record in ordered:
                shown = display_record(record, state.sort_mode, self.now_ms)
                rendered_rows.append(
                    _row(record.host, display=shown, info=record.host, meta=record.host)
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
        return ROFI_RECORD_SEPARATOR.join([*headers, *rendered_rows]) + ROFI_RECORD_SEPARATOR

    def dispatch(self, retv: int, argv: Sequence[str], env: Mapping[str, str] | None = None) -> str:
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
                    self.store.remove(value)
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
        return self.worker_launcher(host)
