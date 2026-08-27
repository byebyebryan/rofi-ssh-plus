"""Rofi script-mode rendering and dispatch."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .launch import spawn_worker
from .model import InvalidDestination, normalize_destination
from .ranking import display_record, sort_hosts
from .state import StateStore


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

    def render(self) -> str:
        state = self.store.load()
        rows = [
            _option("use-hot-keys", "true"),
            _option("prompt", "SSH"),
            _option(
                "message",
                f"Sorted by {state.sort_mode} · Alt+S toggles order · Ctrl+Enter connects a typed destination",
            ),
        ]
        ordered = sort_hosts(state.hosts, state.sort_mode)
        if ordered:
            for record in ordered:
                shown = display_record(record, state.sort_mode, self.now_ms)
                rows.append(_row(record.host, display=shown, info=record.host, meta=record.host))
        else:
            rows.append(
                _row(
                    "No verified SSH hosts yet",
                    display="No verified SSH hosts yet — type a host and press Ctrl+Enter",
                    meta="type a host",
                    nonselectable=True,
                )
            )
        return "\n".join(rows) + "\n"

    def dispatch(self, retv: int, argv: Sequence[str], env: Mapping[str, str] | None = None) -> str:
        """Handle one Rofi callback and return the next script output."""

        environ = os.environ if env is None else env
        if retv == 10:
            self.store.toggle_sort_mode()
            return self.render()

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
            return self.render()
        return self.render()

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
