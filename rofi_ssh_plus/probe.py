"""SSH reachability probing and stderr classification."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable, Sequence

from .model import normalize_destination


REACHED_SERVER_MARKERS = (
    "permission denied",
    "host key verification",
    "remote host identification has changed",
    "userauth",
)


@dataclass(frozen=True)
class ProbeResult:
    returncode: int | None
    stderr: str
    reached_server: bool
    timed_out: bool = False
    error: str = ""


def build_probe_argv(host: str, *, ssh_command: str = "ssh", timeout: int = 2) -> list[str]:
    canonical = normalize_destination(host)
    timeout_value = max(1, int(timeout))
    if not ssh_command:
        ssh_command = "ssh"
    return [
        ssh_command,
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={timeout_value}",
        canonical,
        "true",
    ]


def classify_probe(returncode: int | None, stderr: str = "", *, timed_out: bool = False, error: str = "") -> bool:
    """Return whether a probe established that a real SSH server answered."""

    if timed_out or error:
        return False
    if returncode == 0:
        return True
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    lowered = (stderr or "").casefold()
    return any(marker in lowered for marker in REACHED_SERVER_MARKERS)


def run_probe(
    host: str,
    *,
    ssh_command: str = "ssh",
    timeout: int = 2,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ProbeResult:
    """Run the non-interactive probe with argv separation and a hard guard."""

    argv = build_probe_argv(host, ssh_command=ssh_command, timeout=timeout)
    timeout_value = max(1, int(timeout))
    try:
        completed = runner(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_value + 1,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return ProbeResult(None, stderr, False, timed_out=True, error="probe timeout")
    except OSError as exc:
        return ProbeResult(None, "", False, error=str(exc))
    stderr = completed.stderr or ""
    reached = classify_probe(completed.returncode, stderr)
    return ProbeResult(completed.returncode, stderr, reached)
