"""SSH reachability probing and stderr classification."""

from __future__ import annotations

import secrets
import shlex
import subprocess
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .mesh import SshPolicy
from .model import normalize_destination, validate_destination

REACHED_SERVER_MARKERS = (
    "permission denied",
    "host key verification",
    "remote host identification has changed",
    "userauth",
)

REACHED_MARKER_PREFIX = "\x1eROFI_PLUS_REACHED_V1:"
REACHED_MARKER_SUFFIX = "\x1f\n"
# Descriptive aliases make the producer protocol easy to discover for
# consumers without coupling them to a private parser implementation.
REACHED_HOST_MARKER_PREFIX = REACHED_MARKER_PREFIX
REACHED_HOST_MARKER_SUFFIX = REACHED_MARKER_SUFFIX
TRANSPORT_FAILURE_MARKERS = (
    "could not resolve hostname",
    "name or service not known",
    "temporary failure in name resolution",
    "connection refused",
    "connection timed out",
    "operation timed out",
    "no route to host",
    "network is unreachable",
    "connection reset by peer",
    "kex_exchange_identification",
)


@dataclass(frozen=True)
class ProbeResult:
    returncode: int | None
    stderr: str
    reached_server: bool
    timed_out: bool = False
    error: str = ""


def build_probe_argv(
    host: str,
    *,
    ssh_command: str = "ssh",
    timeout: int = 2,
    attempts: int = 1,
    preserve_spelling: bool = False,
) -> list[str]:
    canonical = (
        validate_destination(host) if preserve_spelling else normalize_destination(host)
    )
    timeout_value = max(1, int(timeout))
    if not ssh_command:
        ssh_command = "ssh"
    if (
        not isinstance(ssh_command, str)
        or not ssh_command
        or ssh_command.startswith("-")
    ):
        raise ValueError("ssh executable must be one nonempty argv element")
    if any(
        char.isspace() or unicodedata.category(char).startswith("C")
        for char in ssh_command
    ):
        raise ValueError("ssh executable must be one nonempty argv element")
    argv = [
        ssh_command,
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={timeout_value}",
    ]
    attempts_value = max(1, int(attempts))
    if attempts_value != 1:
        argv.extend(["-o", f"ConnectionAttempts={attempts_value}"])
    argv.extend([canonical, "true"])
    return argv


def classify_probe(
    returncode: int | None,
    stderr: str = "",
    *,
    timed_out: bool = False,
    error: str = "",
) -> bool:
    """Return whether a probe established that a real SSH server answered."""

    if timed_out or error:
        return False
    if returncode == 0:
        return True
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    lowered = (stderr or "").casefold()
    return any(marker in lowered for marker in REACHED_SERVER_MARKERS)


def classify_transport_failure(
    returncode: int | None,
    stderr: str = "",
    *,
    timed_out: bool = False,
    error: str = "",
) -> bool:
    """Classify only failures that are confidently transport-level.

    Authentication, host-key, and policy failures intentionally return false:
    the SSH process reached a server, but the caller cannot safely infer a
    route-health result from an unmarked command.  The marker protocol is the
    authoritative positive signal for domain operations.
    """

    if timed_out or error:
        return bool(timed_out)
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    lowered = (stderr or "").casefold()
    return any(marker in lowered for marker in TRANSPORT_FAILURE_MARKERS)


def generate_reached_nonce() -> str:
    """Generate the required unpredictable lowercase hexadecimal nonce."""

    return secrets.token_hex(16)


def reached_marker(nonce: str) -> str:
    _validate_nonce(nonce)
    return f"{REACHED_MARKER_PREFIX}{nonce}{REACHED_MARKER_SUFFIX}"


def _validate_nonce(nonce: str) -> None:
    if (
        not isinstance(nonce, str)
        or len(nonce) < 32
        or any(char not in "0123456789abcdef" for char in nonce)
    ):
        raise ValueError(
            "reached-host nonce must be at least 128-bit lowercase hexadecimal"
        )


def build_reached_wrapper(
    domain_argv: Sequence[str], *, nonce: str | None = None
) -> tuple[str, list[str], str]:
    """Build a fixed shell wrapper that executes domain argv literally.

    The nonce is passed as an argv value rather than interpolated into shell
    source.  The wrapper emits its marker before shifting that value and uses
    ``exec \"$@\"`` so domain arguments are never reparsed as shell code.
    """

    if not domain_argv:
        raise ValueError("domain argv must not be empty")
    values: list[str] = []
    for value in domain_argv:
        if (
            not isinstance(value, str)
            or "\x00" in value
            or any(unicodedata.category(char).startswith("C") for char in value)
        ):
            raise ValueError("domain argv contains an invalid argument")
        values.append(value)
    marker_nonce = generate_reached_nonce() if nonce is None else nonce
    _validate_nonce(marker_nonce)
    script = r'''printf '\036ROFI_PLUS_REACHED_V1:%s\037\n' "$1" >&2
shift
exec "$@"'''
    return script, ["rofi-plus-reached", marker_nonce, *values], marker_nonce


def build_marked_probe_argv(
    route: str,
    *,
    ssh_command: str = "ssh",
    timeout: int = 2,
    attempts: int = 1,
    preserve_spelling: bool = True,
    nonce: str | None = None,
) -> tuple[list[str], str]:
    """Build an SSH argv invoking the version-1 reached-host wrapper."""

    script, wrapper_args, marker_nonce = build_reached_wrapper(["true"], nonce=nonce)
    argv = build_probe_argv(
        route,
        ssh_command=ssh_command,
        timeout=timeout,
        attempts=attempts,
        preserve_spelling=preserve_spelling,
    )
    # build_probe_argv ends with the old ``true`` domain command.  Replace it
    # with the shell wrapper while retaining all bounded SSH policy options.
    argv = argv[:-1] + [
        " ".join(shlex.quote(value) for value in ("sh", "-c", script, *wrapper_args))
    ]
    return argv, marker_nonce


def parse_reached_marker(stderr: str | bytes, nonce: str) -> tuple[bool, str]:
    """Validate and remove exactly one invocation marker from stderr."""

    _validate_nonce(nonce)
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    marker = reached_marker(nonce)
    if stderr.count(marker) != 1:
        return False, stderr
    return True, stderr.replace(marker, "", 1)


@dataclass(frozen=True)
class MarkedCommandResult:
    returncode: int | None
    stdout: str
    stderr: str
    reached_host: bool
    timed_out: bool = False
    error: str = ""


def run_marked_command(
    route: str,
    domain_argv: Sequence[str],
    *,
    policy: SshPolicy | None = None,
    ssh_command: str | None = None,
    timeout: int | None = None,
    attempts: int | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> MarkedCommandResult:
    """Run a bounded marked command and classify its reached-host marker."""

    selected = policy or SshPolicy()
    command = ssh_command or selected.executable
    timeout_value = (
        selected.connect_timeout_seconds if timeout is None else max(1, int(timeout))
    )
    attempts_value = (
        selected.connection_attempts if attempts is None else max(1, int(attempts))
    )
    nonce = generate_reached_nonce()
    script, wrapper_args, nonce = build_reached_wrapper(domain_argv, nonce=nonce)
    canonical_route = validate_destination(route)
    argv = build_probe_argv(
        canonical_route,
        ssh_command=command,
        timeout=timeout_value,
        attempts=attempts_value,
        preserve_spelling=True,
    )[:-1] + [
        " ".join(shlex.quote(value) for value in ("sh", "-c", script, *wrapper_args))
    ]
    try:
        completed = runner(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_value * attempts_value + 1,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = (
            exc.stderr.decode(errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        return MarkedCommandResult(
            None, "", stderr, False, timed_out=True, error="command timeout"
        )
    except OSError as exc:
        return MarkedCommandResult(None, "", "", False, error=str(exc))
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    reached, clean_stderr = parse_reached_marker(stderr, nonce)
    return MarkedCommandResult(completed.returncode, stdout, clean_stderr, reached)


def run_probe(
    host: str,
    *,
    ssh_command: str = "ssh",
    timeout: int = 2,
    attempts: int = 1,
    preserve_spelling: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ProbeResult:
    """Run the non-interactive probe with argv separation and a hard guard."""

    argv = build_probe_argv(
        host,
        ssh_command=ssh_command,
        timeout=timeout,
        attempts=attempts,
        preserve_spelling=preserve_spelling,
    )
    timeout_value = max(1, int(timeout))
    attempts_value = max(1, int(attempts))
    try:
        completed = runner(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_value * attempts_value + 1,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = (
            exc.stderr.decode(errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        return ProbeResult(None, stderr, False, timed_out=True, error="probe timeout")
    except OSError as exc:
        return ProbeResult(None, "", False, error=str(exc))
    stderr = completed.stderr or ""
    reached = classify_probe(completed.returncode, stderr)
    return ProbeResult(completed.returncode, stderr, reached)


parse_reached_host_marker = parse_reached_marker
build_reached_host_wrapper = build_reached_wrapper
