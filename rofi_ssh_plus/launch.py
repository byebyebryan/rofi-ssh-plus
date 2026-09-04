"""Safe detached worker and terminal launching."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from .mesh import MeshConfig, load_mesh
from .model import normalize_destination, validate_destination
from .probe import (
    ProbeResult,
    classify_transport_failure,
    run_probe,
)
from .state import StateStore


def terminal_argv(
    host: str,
    *,
    terminal: str | None = None,
    ssh_command: str = "ssh",
    preserve_spelling: bool = False,
) -> list[str]:
    """Build the terminal argv without interpolating the destination."""

    canonical = (
        validate_destination(host) if preserve_spelling else normalize_destination(host)
    )
    terminal_spec = (
        terminal if terminal is not None else (os.environ.get("TERMINAL") or "ghostty")
    )
    try:
        command = shlex.split(terminal_spec)
    except ValueError:
        command = []
    if not command:
        command = ["ghostty"]
    executable = ssh_command or "ssh"
    executable = validate_destination(executable)
    return command + ["-e", executable, canonical]


def spawn_detached(
    argv: Sequence[str], *, popen: Callable[..., object] = subprocess.Popen
) -> bool:
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


def worker_argv(
    host: str, *, entrypoint: str | os.PathLike[str] | None = None
) -> list[str]:
    canonical = normalize_destination(host)
    script = Path(entrypoint or sys.argv[0]).resolve()
    return [sys.executable, str(script), "--worker", canonical]


def spawn_worker(
    host: str, *, entrypoint: str | os.PathLike[str] | None = None
) -> bool:
    return spawn_detached(worker_argv(host, entrypoint=entrypoint))


def managed_worker_argv(
    host_id: str, *, entrypoint: str | os.PathLike[str] | None = None
) -> list[str]:
    canonical = normalize_destination(host_id)
    script = Path(entrypoint or sys.argv[0]).resolve()
    return [sys.executable, str(script), "--worker-managed", canonical]


def spawn_managed_worker(
    host_id: str, *, entrypoint: str | os.PathLike[str] | None = None
) -> bool:
    return spawn_detached(managed_worker_argv(host_id, entrypoint=entrypoint))


def run_worker(
    host: str,
    *,
    store: StateStore | None = None,
    ssh_command: str = "ssh",
    timeout: int = 2,
    attempts: int = 1,
    terminal: str | None = None,
    probe: Callable[..., ProbeResult] = run_probe,
    terminal_launcher: Callable[[Sequence[str]], bool] = spawn_detached,
) -> int:
    """Probe, best-effort record, and launch the terminal in that order."""

    canonical = normalize_destination(host)
    try:
        result = probe(
            canonical, ssh_command=ssh_command, timeout=timeout, attempts=attempts
        )
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


def run_managed_worker(
    host_id: str,
    *,
    mesh: MeshConfig | None = None,
    store: StateStore | None = None,
    probe: Callable[..., ProbeResult] | None = None,
    terminal_launcher: Callable[[Sequence[str]], bool] = spawn_detached,
    terminal: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Probe a logical host's recommended routes and launch exactly one route.

    Managed route selection intentionally uses SSH Plus's existing explicit
    reachability probe. Its ``classify_probe`` semantics treat recognized
    authentication and host-key responses as a reached server, while keeping
    transport failures out of usage history. Consumers that run domain
    commands use the separate reached-host marker helpers in ``probe.py``.
    """

    selected_mesh = mesh or load_mesh(environ=environ)
    canonical_id = normalize_destination(host_id)
    host = selected_mesh.host_by_id(canonical_id)
    if host is None or host.local:
        return 2
    selected_store = store or StateStore.from_environment(
        dict(environ) if environ is not None else None, mesh=selected_mesh
    )
    if selected_store.mesh is None:
        selected_store.mesh = selected_mesh
    routes = selected_mesh.routes_for(host)
    if not routes:
        return 2
    chosen = routes[0]
    reached = False
    selected_probe = run_probe if probe is None else probe
    for route in routes:
        try:
            result = selected_probe(
                route.destination,
                ssh_command=selected_mesh.ssh_policy.executable,
                timeout=selected_mesh.ssh_policy.connect_timeout_seconds,
                attempts=selected_mesh.ssh_policy.connection_attempts,
                preserve_spelling=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            result = ProbeResult(None, "", False, error=str(exc))
        if result.reached_server:
            chosen = route
            reached = True
            break
        if classify_transport_failure(
            result.returncode,
            result.stderr,
            timed_out=result.timed_out,
            error=result.error,
        ):
            continue
        # An unclassified policy/SSH failure is not a route-health failure,
        # but another configured candidate may still be useful to the user.
        continue
    if reached:
        try:
            selected_store.record_success(canonical_id)
        except (OSError, ValueError, RuntimeError):
            pass
    command = terminal_argv(
        chosen.destination,
        terminal=terminal,
        ssh_command=selected_mesh.ssh_policy.executable,
        preserve_spelling=True,
    )
    return 0 if terminal_launcher(command) else 1
