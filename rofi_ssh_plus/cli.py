"""Command-line entry point used by the executable Rofi script."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

from .launch import run_managed_worker, run_worker, spawn_managed_worker, spawn_worker
from .mesh import (
    MeshError,
    MeshPersistenceError,
    RouteHealthStore,
    load_mesh,
    report_route,
    route_health_path,
)
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
    output_stream = stdout or sys.stdout
    if args and args[0] == "mesh":
        return _mesh_main(args[1:], env, output_stream)
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
        try:
            return run_worker(
                host,
                store=StateStore.from_environment(dict(env)),
                ssh_command=ssh_command,
                timeout=timeout,
                terminal=env.get("TERMINAL") or "ghostty",
            )
        except (InvalidDestination, ValueError, OSError, RuntimeError):
            return 2
    if args and args[0] == "--worker-managed":
        if len(args) != 2:
            return 2
        try:
            from .model import normalize_destination

            host_id = normalize_destination(args[1])
        except (InvalidDestination, TypeError):
            return 2
        try:
            return run_managed_worker(
                host_id,
                terminal=env.get("TERMINAL") or "ghostty",
                environ=env,
            )
        except (MeshError, OSError, RuntimeError, ValueError):
            return 2

    if args and args[0].startswith("--"):
        return 2
    try:
        retv = int(env.get("ROFI_RETV", "0"))
    except ValueError:
        retv = 0
    try:
        mesh = load_mesh(env)
    except MeshError as exc:
        output_stream.write(
            "\x00use-hot-keys\x1ftrue\n"
            f"\x00prompt\x1fSSH\n"
            f"\x00message\x1fHost Mesh error: {exc.message}\n"
        )
        output_stream.flush()
        return 1
    except (MeshPersistenceError, OSError) as exc:
        output_stream.write(
            "\x00use-hot-keys\x1ftrue\n"
            f"\x00prompt\x1fSSH\n"
            f"\x00message\x1fHost Mesh persistence error: {exc}\n"
        )
        output_stream.flush()
        return 1
    store = StateStore.from_environment(dict(env), mesh=mesh)
    entrypoint = Path(sys.argv[0]).resolve()
    launcher = lambda host: spawn_worker(host, entrypoint=entrypoint)
    managed_launcher = lambda host_id: spawn_managed_worker(
        host_id, entrypoint=entrypoint
    )
    picker = Picker(
        store,
        worker_launcher=launcher,
        mesh=mesh,
        managed_worker_launcher=managed_launcher,
    )
    output = picker.dispatch(retv, args, env)
    output_stream.write(output)
    output_stream.flush()
    return 0


def _json_write(stream: TextIO, payload: object) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    stream.flush()


def _error_payload(code: str, message: str) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "ok": False,
        "error": {"code": code, "message": message},
    }


def _mesh_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rofi-ssh-plus mesh", add_help=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list", add_help=False)
    list_parser.add_argument("--json", action="store_true")
    report_parser = subparsers.add_parser("report-route", add_help=False)
    report_parser.add_argument("--json", action="store_true")
    report_parser.add_argument("--host")
    report_parser.add_argument("--route")
    report_parser.add_argument("--status")
    report_parser.add_argument("--source")
    report_parser.add_argument("--mesh-revision", dest="mesh_revision")
    report_parser.add_argument("--observed-at", dest="observed_at", type=int)
    return parser


def _mesh_main(args: Sequence[str], environ: Mapping[str, str], stdout: TextIO) -> int:
    parser = _mesh_parser()
    try:
        parsed = parser.parse_args(list(args))
    except SystemExit:
        _json_write(
            stdout, _error_payload("invalid_input", "invalid mesh command arguments")
        )
        return 1
    if not parsed.json:
        _json_write(
            stdout, _error_payload("invalid_input", "mesh commands require --json")
        )
        return 1
    try:
        mesh = load_mesh(environ)
        if parsed.command == "list":
            _json_write(stdout, mesh.to_dict())
            return 0
        required = {
            "host": parsed.host,
            "route": parsed.route,
            "status": parsed.status,
            "source": parsed.source,
            "mesh revision": parsed.mesh_revision,
            "observed-at": parsed.observed_at,
        }
        missing = next(
            (label for label, value in required.items() if value is None), None
        )
        if missing is not None:
            raise MeshError("invalid_input", f"{missing} is required")
        accepted = report_route(
            mesh,
            host_id=parsed.host,
            route=parsed.route,
            status=parsed.status,
            source=parsed.source,
            mesh_revision=parsed.mesh_revision,
            observed_at=parsed.observed_at,
            health_store=RouteHealthStore(route_health_path(environ)),
        )
        _json_write(stdout, {"schemaVersion": 1, "ok": True, "accepted": accepted})
        return 0
    except MeshError as exc:
        _json_write(stdout, _error_payload(exc.code, exc.message))
        return 1
    except (MeshPersistenceError, OSError) as exc:
        _json_write(stdout, _error_payload("persistence_failed", str(exc)))
        return 1
