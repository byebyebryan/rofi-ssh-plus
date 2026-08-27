"""Safe detached worker and terminal launching."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

from .model import normalize_destination
from .probe import ProbeResult, run_probe
from .state import StateStore


def terminal_argv(host: str, *, terminal: str | None = None, ssh_command: str = "ssh") -> list[str]:
    """Build the terminal argv without interpolating the destination."""

    canonical = normalize_destination(host)
    terminal_spec = terminal if terminal is not None else (os.environ.get("TERMINAL") or "ghostty")
    try:
        command = shlex.split(terminal_spec)
    except ValueError:
        command = []
    if not command:
        command = ["ghostty"]
    return command + ["-e", ssh_command or "ssh", canonical]


def spawn_detached(argv: Sequence[str], *, popen: Callable[..., object] = subprocess.Popen) -> bool:
    """Start an independent process with no Rofi/worker stdio dependency."""

    try:
        popen(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except OSError:
        return False
    return True


def worker_argv(host: str, *, entrypoint: str | os.PathLike[str] | None = None) -> list[str]:
    canonical = normalize_destination(host)
    script = Path(entrypoint or sys.argv[0]).resolve()
    return [sys.executable, str(script), "--worker", canonical]


def spawn_worker(host: str, *, entrypoint: str | os.PathLike[str] | None = None) -> bool:
    return spawn_detached(worker_argv(host, entrypoint=entrypoint))


def run_worker(
    host: str,
    *,
    store: StateStore | None = None,
    ssh_command: str = "ssh",
    timeout: int = 2,
    terminal: str | None = None,
    probe: Callable[..., ProbeResult] = run_probe,
    terminal_launcher: Callable[[Sequence[str]], bool] = spawn_detached,
) -> int:
    """Probe, best-effort record, and launch the terminal in that order."""

    canonical = normalize_destination(host)
    try:
        result = probe(canonical, ssh_command=ssh_command, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        result = ProbeResult(None, "", False, error=str(exc))
    if result.reached_server:
        try:
            (store or StateStore.from_environment()).record_success(canonical)
        except (OSError, ValueError, RuntimeError):
            # A broken state path must not prevent the requested SSH session.
            pass
    command = terminal_argv(canonical, terminal=terminal, ssh_command=ssh_command)
    return 0 if terminal_launcher(command) else 1
