"""Command-line entry point used by the executable Rofi script."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping, Sequence, TextIO

from .launch import run_worker, spawn_worker
from .model import InvalidDestination
from .protocol import Picker
from .state import StateStore


def _positive_env(env: Mapping[str, str], name: str, default: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if environ is None else environ
    if args and args[0] == "--worker":
        if len(args) != 2:
            return 2
        try:
            host = args[1]
            # Normalize before entering the worker so malformed custom input
            # can never reach a subprocess.
            from .model import normalize_destination

            host = normalize_destination(host)
        except (InvalidDestination, TypeError):
            return 2
        timeout = _positive_env(env, "ROFI_SSH_PLUS_CONNECT_TIMEOUT", 2)
        ssh_command = env.get("ROFI_SSH_PLUS_SSH_COMMAND") or "ssh"
        return run_worker(
            host,
            store=StateStore.from_environment(dict(env)),
            ssh_command=ssh_command,
            timeout=timeout,
            terminal=env.get("TERMINAL") or "ghostty",
        )

    if args and args[0].startswith("--"):
        return 2
    try:
        retv = int(env.get("ROFI_RETV", "0"))
    except ValueError:
        retv = 0
    store = StateStore.from_environment(dict(env))
    entrypoint = Path(sys.argv[0]).resolve()
    launcher = lambda host: spawn_worker(host, entrypoint=entrypoint)
    picker = Picker(store, worker_launcher=launcher)
    output = picker.dispatch(retv, args, env)
    (stdout or sys.stdout).write(output)
    (stdout or sys.stdout).flush()
    return 0
