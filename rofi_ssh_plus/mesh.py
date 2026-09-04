"""Host Mesh Contract v1 configuration, identity, and route health.

The mesh is intentionally a small in-process model.  Its public consumers use
the executable JSON interface; keeping parsing and persistence here separate
also makes the contract deterministic to test without a network connection.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import tempfile
import time
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - the application targets Linux
    fcntl = None  # type: ignore[assignment]

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.11 is required
    tomllib = None  # type: ignore[assignment]


MESH_SCHEMA_VERSION = 1
DEFAULT_CONNECT_TIMEOUT_SECONDS = 2
DEFAULT_CONNECTION_ATTEMPTS = 1
DEFAULT_ROUTE_HEALTH_TTL_SECONDS = 300
MAX_REPORT_CLOCK_SKEW_MS = 5 * 60 * 1000
HOST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_ALLOWED_TOP_LEVEL = {
    "schema_version",
    "local_id",
    "local_display",
    "local_aliases",
    "ssh",
    "hosts",
}
_ALLOWED_SSH = {
    "executable",
    "connect_timeout_seconds",
    "connection_attempts",
    "route_health_ttl_seconds",
}
_ALLOWED_HOST = {"id", "display", "routes", "aliases"}


class MeshError(ValueError):
    """A user-visible Host Mesh contract/configuration error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class MeshPersistenceError(OSError):
    """A route-health state read/write failure."""


def _casefold(value: str) -> str:
    return value.casefold()


def _token(value: object, *, label: str, identifier: bool = False) -> str:
    if not isinstance(value, str) or not value:
        raise MeshError("invalid_config", f"{label} must be a nonempty string")
    if value.strip() != value or value.startswith("-"):
        raise MeshError("invalid_config", f"{label} must be one SSH-safe token")
    if any(
        char.isspace() or unicodedata.category(char).startswith("C") for char in value
    ):
        raise MeshError(
            "invalid_config",
            f"{label} must not contain whitespace or control characters",
        )
    if identifier and not HOST_ID_RE.fullmatch(value):
        raise MeshError(
            "invalid_config", f"{label} must match [A-Za-z0-9][A-Za-z0-9_.-]*"
        )
    return value


def _display(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise MeshError("invalid_config", f"{label} must be a nonempty display string")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise MeshError(
            "invalid_config", f"{label} must not contain control characters"
        )
    return value


def _string_list(
    value: object, *, label: str, identifier: bool = False
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise MeshError("invalid_config", f"{label} must be an array")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        text = _token(item, label=f"{label}[{index}]", identifier=identifier)
        key = _casefold(text)
        if key in seen:
            raise MeshError("invalid_config", f"{label} contains duplicate values")
        seen.add(key)
        result.append(text)
    return tuple(result)


def _int_range(value: object, *, label: str, low: int, high: int, default: int) -> int:
    if value is None:
        return default
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not low <= value <= high
    ):
        raise MeshError(
            "invalid_config", f"{label} must be an integer from {low} through {high}"
        )
    return value


@dataclass(frozen=True)
class SshPolicy:
    executable: str = "ssh"
    connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS
    connection_attempts: int = DEFAULT_CONNECTION_ATTEMPTS
    route_health_ttl_seconds: int = DEFAULT_ROUTE_HEALTH_TTL_SECONDS

    def to_dict(self) -> dict[str, object]:
        return {
            "executable": self.executable,
            "connectTimeoutSeconds": self.connect_timeout_seconds,
            "connectionAttempts": self.connection_attempts,
            "routeHealthTtlSeconds": self.route_health_ttl_seconds,
        }


@dataclass(frozen=True)
class RouteHealth:
    last_reachable_at: int | None = None
    last_unreachable_at: int | None = None

    @property
    def newest(self) -> tuple[str, int] | None:
        values: list[tuple[str, int]] = []
        if self.last_reachable_at is not None:
            values.append(("reachable", self.last_reachable_at))
        if self.last_unreachable_at is not None:
            values.append(("unreachable", self.last_unreachable_at))
        return max(values, key=lambda item: item[1]) if values else None

    def to_dict(self) -> dict[str, int | None]:
        return {
            "lastReachableAt": self.last_reachable_at,
            "lastUnreachableAt": self.last_unreachable_at,
        }


@dataclass(frozen=True)
class Route:
    destination: str
    configured_index: int
    health: RouteHealth = RouteHealth()

    def to_dict(self) -> dict[str, object]:
        return {
            "destination": self.destination,
            "configuredIndex": self.configured_index,
            **self.health.to_dict(),
        }


@dataclass(frozen=True)
class Host:
    id: str
    display: str
    local: bool
    aliases: tuple[str, ...]
    routes: tuple[Route, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "display": self.display,
            "local": self.local,
            "aliases": list(self.aliases),
            "routes": [route.to_dict() for route in self.routes],
        }


@dataclass(frozen=True)
class MeshConfig:
    local_host_id: str
    local_display: str
    local_aliases: tuple[str, ...]
    hosts: tuple[Host, ...]
    ssh_policy: SshPolicy
    mesh_revision: str
    config_path: Path | None = None

    @property
    def local_host(self) -> Host:
        return self.hosts[0]

    @property
    def remote_hosts(self) -> tuple[Host, ...]:
        return self.hosts[1:]

    def host_by_id(self, host_id: str) -> Host | None:
        canonical = _casefold(host_id)
        return next((host for host in self.hosts if host.id == canonical), None)

    def resolve_token(self, value: str) -> Host | None:
        """Resolve an ID, alias, or route only when it maps unambiguously."""

        canonical = _casefold(value)
        matches = [
            host
            for host in self.hosts
            if host.id == canonical
            or any(_casefold(alias) == canonical for alias in host.aliases)
            or any(_casefold(route.destination) == canonical for route in host.routes)
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def routes_for(self, host: Host, *, now_ms: int | None = None) -> tuple[Route, ...]:
        routes = list(host.routes)
        if not routes:
            return ()
        ttl_ms = self.ssh_policy.route_health_ttl_seconds * 1000
        effective_now_ms = current_time_ms() if now_ms is None else now_ms

        def demoted(route: Route) -> bool:
            latest = route.health.newest
            return bool(
                latest
                and latest[0] == "unreachable"
                and effective_now_ms - latest[1] < ttl_ms
            )

        # Stable sorting retains declaration order among healthy and demoted
        # routes, and therefore never promotes a fallback permanently.
        return tuple(sorted(routes, key=demoted))

    recommended_routes = routes_for

    def with_health(self, health: Mapping[tuple[str, str], RouteHealth]) -> MeshConfig:
        hosts: list[Host] = []
        for host in self.hosts:
            routes = tuple(
                Route(
                    route.destination,
                    route.configured_index,
                    health.get((host.id, _casefold(route.destination)), RouteHealth()),
                )
                for route in host.routes
            )
            hosts.append(Host(host.id, host.display, host.local, host.aliases, routes))
        return MeshConfig(
            self.local_host_id,
            self.local_display,
            self.local_aliases,
            tuple(hosts),
            self.ssh_policy,
            self.mesh_revision,
            self.config_path,
        )

    def to_dict(
        self, *, generated_at: int | None = None, now_ms: int | None = None
    ) -> dict[str, object]:
        """Serialize the public ``mesh list --json`` response."""

        host_values: list[dict[str, object]] = []
        for host in self.hosts:
            value = host.to_dict()
            value["routes"] = [
                route.to_dict() for route in self.routes_for(host, now_ms=now_ms)
            ]
            host_values.append(value)
        return {
            "schemaVersion": MESH_SCHEMA_VERSION,
            "generatedAt": current_time_ms() if generated_at is None else generated_at,
            "meshRevision": self.mesh_revision,
            "localHostId": self.local_host_id,
            "sshPolicy": self.ssh_policy.to_dict(),
            "hosts": host_values,
        }


def _hostname_parts() -> tuple[str, str]:
    short = socket.gethostname().split(".", 1)[0] or "localhost"
    full = socket.getfqdn() or short
    return full, short


def config_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    config_home = Path(env.get("XDG_CONFIG_HOME") or "~/.config").expanduser()
    return config_home / "rofi-ssh-plus" / "config.toml"


def route_health_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    state_home = Path(env.get("XDG_STATE_HOME") or "~/.local/state").expanduser()
    return state_home / "rofi-ssh-plus" / "route-health.json"


def _revision_payload(config: MeshConfig) -> dict[str, object]:
    return {
        "schemaVersion": MESH_SCHEMA_VERSION,
        "localHostId": config.local_host_id,
        "localDisplay": config.local_display,
        "localAliases": [_casefold(alias) for alias in config.local_aliases],
        "hosts": [
            {
                "id": host.id,
                "display": host.display,
                "local": host.local,
                "aliases": [_casefold(alias) for alias in host.aliases],
                "routes": [route.destination for route in host.routes],
            }
            for host in config.hosts
        ],
        "sshPolicy": config.ssh_policy.to_dict(),
    }


def _with_revision(config: MeshConfig) -> MeshConfig:
    encoded = json.dumps(
        _revision_payload(config),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    revision = "sha256:" + hashlib.sha256(encoded).hexdigest()
    return MeshConfig(
        config.local_host_id,
        config.local_display,
        config.local_aliases,
        config.hosts,
        config.ssh_policy,
        revision,
        config.config_path,
    )


def _validate_top_level(payload: Mapping[str, object]) -> None:
    unknown = set(payload) - _ALLOWED_TOP_LEVEL
    if unknown:
        raise MeshError("invalid_config", f"unknown configuration key: {min(unknown)}")
    schema = payload.get("schema_version")
    if isinstance(schema, bool) or not isinstance(schema, int):
        raise MeshError("invalid_config", "schema_version must be 1")
    if schema != MESH_SCHEMA_VERSION:
        raise MeshError(
            "unsupported_schema", f"unsupported Host Mesh schema version: {schema}"
        )


def load_config(
    path: str | os.PathLike[str] | None = None,
    *,
    hostname: tuple[str, str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> MeshConfig:
    """Load strict TOML configuration, or synthesize the local-only mesh."""

    source = Path(path).expanduser() if path is not None else config_path(environ)
    full_hostname, short_hostname = hostname or _hostname_parts()
    if not source.exists():
        # The no-file path is the only fallback.  Hostname APIs normally
        # return RFC-style tokens, but a compromised or unusual local value
        # must not leak controls into Rofi output or become an option-like ID.
        try:
            local_id = _casefold(
                _token(short_hostname, label="inferred hostname", identifier=True)
            )
        except MeshError:
            local_id = "localhost"
        aliases = list(_safe_inferred_aliases((full_hostname, short_hostname)))
        local_aliases = _dedupe_aliases(aliases or [local_id])
        local_display = (
            short_hostname
            if isinstance(short_hostname, str)
            and short_hostname
            and short_hostname.strip() == short_hostname
            and not any(
                unicodedata.category(char).startswith("C") for char in short_hostname
            )
            else local_id
        )
        local = Host(local_id, local_display, True, local_aliases, ())
        return _with_revision(
            MeshConfig(
                local_id, local_display, local_aliases, (local,), SshPolicy(), "", None
            )
        )
    try:
        with source.open("rb") as stream:
            payload = tomllib.load(stream) if tomllib is not None else {}
    except MeshError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise MeshError(
            "invalid_config", f"unable to parse Host Mesh configuration: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise MeshError("invalid_config", "configuration root must be a table")
    _validate_top_level(payload)

    local_id_was_omitted = "local_id" not in payload
    raw_local_id = payload.get("local_id", short_hostname)
    try:
        local_id_raw = _token(raw_local_id, label="local_id", identifier=True)
    except MeshError:
        if not local_id_was_omitted:
            raise
        local_id_raw = "localhost"
    local_id = _casefold(local_id_raw)
    if "local_display" in payload:
        local_display = _display(payload["local_display"], label="local_display")
    else:
        try:
            local_display = _display(short_hostname, label="local_display")
        except MeshError:
            local_display = local_id
    configured_aliases = _string_list(
        payload.get("local_aliases", []), label="local_aliases"
    )
    local_aliases = _dedupe_aliases(
        (*configured_aliases, *_safe_inferred_aliases((full_hostname, short_hostname)))
    )
    if not local_aliases:
        local_aliases = (local_id,)

    raw_ssh = payload.get("ssh", {})
    if not isinstance(raw_ssh, dict):
        raise MeshError("invalid_config", "ssh must be a table")
    unknown_ssh = set(raw_ssh) - _ALLOWED_SSH
    if unknown_ssh:
        raise MeshError(
            "invalid_config", f"unknown ssh configuration key: {min(unknown_ssh)}"
        )
    executable = _token(raw_ssh.get("executable", "ssh"), label="ssh.executable")
    policy = SshPolicy(
        executable,
        _int_range(
            raw_ssh.get("connect_timeout_seconds"),
            label="ssh.connect_timeout_seconds",
            low=1,
            high=60,
            default=DEFAULT_CONNECT_TIMEOUT_SECONDS,
        ),
        _int_range(
            raw_ssh.get("connection_attempts"),
            label="ssh.connection_attempts",
            low=1,
            high=10,
            default=DEFAULT_CONNECTION_ATTEMPTS,
        ),
        _int_range(
            raw_ssh.get("route_health_ttl_seconds"),
            label="ssh.route_health_ttl_seconds",
            low=1,
            high=86400,
            default=DEFAULT_ROUTE_HEALTH_TTL_SECONDS,
        ),
    )

    raw_hosts = payload.get("hosts", [])
    if not isinstance(raw_hosts, list):
        raise MeshError("invalid_config", "hosts must be an array of tables")
    hosts: list[Host] = [Host(local_id, local_display, True, local_aliases, ())]
    for index, raw_host in enumerate(raw_hosts):
        if not isinstance(raw_host, dict):
            raise MeshError("invalid_config", f"hosts[{index}] must be a table")
        unknown_host = set(raw_host) - _ALLOWED_HOST
        if unknown_host:
            raise MeshError(
                "invalid_config",
                f"unknown host configuration key: {min(unknown_host)}",
            )
        host_id_raw = _token(
            raw_host.get("id"), label=f"hosts[{index}].id", identifier=True
        )
        host_id = _casefold(host_id_raw)
        display = _display(
            raw_host.get("display", host_id_raw), label=f"hosts[{index}].display"
        )
        aliases = _string_list(
            raw_host.get("aliases", []), label=f"hosts[{index}].aliases"
        )
        routes_raw = raw_host.get("routes")
        routes_values = _string_list(routes_raw, label=f"hosts[{index}].routes")
        if not routes_values:
            raise MeshError(
                "invalid_config",
                f"hosts[{index}].routes must contain at least one route",
            )
        routes = tuple(
            Route(destination, route_index)
            for route_index, destination in enumerate(routes_values)
        )
        hosts.append(Host(host_id, display, False, aliases, routes))

    _validate_identity_collisions(hosts)
    return _with_revision(
        MeshConfig(
            local_id, local_display, local_aliases, tuple(hosts), policy, "", source
        )
    )


def _dedupe_aliases(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = _casefold(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return tuple(result)


def _safe_inferred_aliases(values: Sequence[object]) -> tuple[str, ...]:
    """Keep only hostname values safe to expose as SSH/Rofi tokens."""

    aliases: list[str] = []
    for value in values:
        try:
            aliases.append(_token(value, label="inferred hostname"))
        except MeshError:
            continue
    return _dedupe_aliases(aliases)


def _validate_identity_collisions(hosts: Sequence[Host]) -> None:
    values: dict[str, tuple[str, str]] = {}
    host_ids: set[str] = set()
    for host in hosts:
        if host.id in host_ids:
            raise MeshError("invalid_config", "host IDs must be unique")
        host_ids.add(host.id)
        identities = [
            (host.id, "host id"),
            *((_casefold(alias), "alias") for alias in host.aliases),
        ]
        identities.extend(
            (_casefold(route.destination), "route") for route in host.routes
        )
        for value, kind in identities:
            previous = values.get(value)
            if previous is not None and previous[0] != host.id:
                raise MeshError(
                    "invalid_config", f"{kind} {value!r} maps to multiple logical hosts"
                )
            if previous is not None and kind == "host id" and previous[1] == "host id":
                raise MeshError("invalid_config", "host IDs must be unique")
            values[value] = (host.id, kind)


class RouteHealthStore:
    """Private, independent, revision-free route-health persistence."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path).expanduser()

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> RouteHealthStore:
        return cls(route_health_path(environ))

    @property
    def lock_path(self) -> Path:
        return self.path.with_name(f".{self.path.name}.lock")

    def load(self) -> dict[tuple[str, str], RouteHealth]:
        with self._locked():
            return self._read_unlocked()

    def record(self, host_id: str, route: str, status: str, observed_at: int) -> bool:
        host_id = _input_token(host_id, label="host")
        route = _input_token(route, label="route")
        if not isinstance(status, str) or status not in {"reachable", "unreachable"}:
            raise MeshError("invalid_input", "status must be reachable or unreachable")
        if (
            isinstance(observed_at, bool)
            or not isinstance(observed_at, int)
            or observed_at < 0
        ):
            raise MeshError(
                "invalid_input",
                "observedAt must be a nonnegative Unix-millisecond integer",
            )
        with self._locked():
            health = self._read_unlocked()
            key = (_casefold(host_id), _casefold(route))
            current = health.get(key, RouteHealth())
            if current.newest is not None and observed_at <= current.newest[1]:
                return False
            if status == "reachable":
                health[key] = RouteHealth(observed_at, current.last_unreachable_at)
            else:
                health[key] = RouteHealth(current.last_reachable_at, observed_at)
            self._write_unlocked(health)
            return True

    @contextmanager
    def _locked(self) -> Iterator[None]:
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.path.parent, 0o700)
            fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            os.chmod(self.lock_path, 0o600)
            if self.path.exists():
                os.chmod(self.path, 0o600)
        except OSError as exc:
            raise MeshPersistenceError(str(exc)) from exc
        try:
            if fcntl is None:  # pragma: no cover
                raise MeshPersistenceError("advisory file locking is unavailable")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        except MeshPersistenceError:
            raise
        except OSError as exc:
            raise MeshPersistenceError(str(exc)) from exc
        finally:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _read_unlocked(self) -> dict[tuple[str, str], RouteHealth]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, ValueError, TypeError) as exc:
            raise MeshPersistenceError(str(exc)) from exc
        version = payload.get("version") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or isinstance(version, bool)
            or version != self.SCHEMA_VERSION
            or set(payload) != {"version", "routes"}
        ):
            raise MeshPersistenceError("invalid route-health state")
        raw_routes = payload.get("routes")
        if not isinstance(raw_routes, dict):
            raise MeshPersistenceError("invalid route-health state")
        result: dict[tuple[str, str], RouteHealth] = {}
        for raw_key, raw_value in raw_routes.items():
            if (
                not isinstance(raw_key, str)
                or "\x00" not in raw_key
                or not isinstance(raw_value, dict)
                or set(raw_value) != {"lastReachableAt", "lastUnreachableAt"}
            ):
                raise MeshPersistenceError("invalid route-health state")
            host_id, route = raw_key.split("\x00", 1)
            try:
                host_id = _input_token(host_id, label="host")
                route = _input_token(route, label="route")
            except MeshError as exc:
                raise MeshPersistenceError("invalid route-health state") from exc
            reachable = _health_time(raw_value.get("lastReachableAt"))
            unreachable = _health_time(raw_value.get("lastUnreachableAt"))
            key = (_casefold(host_id), _casefold(route))
            if key in result:
                raise MeshPersistenceError("duplicate route-health identity")
            result[key] = RouteHealth(reachable, unreachable)
        return result

    def _write_unlocked(self, health: Mapping[tuple[str, str], RouteHealth]) -> None:
        temporary_path: Path | None = None
        fd: int | None = None
        try:
            fd, temporary = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
            )
            temporary_path = Path(temporary)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                routes = {
                    f"{host}\x00{route}": record.to_dict()
                    for (host, route), record in sorted(health.items())
                }
                json.dump(
                    {"version": self.SCHEMA_VERSION, "routes": routes},
                    stream,
                    indent=2,
                    sort_keys=True,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
            try:
                directory_fd = os.open(
                    self.path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                )
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        except OSError as exc:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise MeshPersistenceError(str(exc)) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass


def _health_time(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MeshPersistenceError("invalid route-health timestamp")
    return value


def load_mesh(environ: Mapping[str, str] | None = None) -> MeshConfig:
    """Load config plus private health, returning a consumer-ready mesh."""

    config = load_config(environ=environ)
    health = RouteHealthStore(route_health_path(environ)).load()
    return config.with_health(health)


def current_time_ms() -> int:
    return int(time.time() * 1000)


def validate_report_time(value: object, *, now_ms: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MeshError(
            "invalid_input", "observedAt must be a nonnegative Unix-millisecond integer"
        )
    now = current_time_ms() if now_ms is None else now_ms
    if value > now + MAX_REPORT_CLOCK_SKEW_MS:
        raise MeshError("invalid_input", "observedAt is too far in the future")
    return value


def validate_source(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise MeshError(
            "invalid_input", "source must be a nonempty label of at most 64 characters"
        )
    if any(
        char.isspace() or unicodedata.category(char).startswith("C") for char in value
    ):
        raise MeshError(
            "invalid_input", "source must not contain whitespace or control characters"
        )
    return value


def _input_token(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or value.startswith("-")
    ):
        raise MeshError("invalid_input", f"{label} must be one nonempty SSH-safe token")
    if any(
        char.isspace() or unicodedata.category(char).startswith("C") for char in value
    ):
        raise MeshError(
            "invalid_input",
            f"{label} must not contain whitespace or control characters",
        )
    return value


def report_route(
    mesh: MeshConfig,
    *,
    host_id: object,
    route: object,
    status: object,
    source: object,
    mesh_revision: object,
    observed_at: object,
    health_store: RouteHealthStore | None = None,
    now_ms: int | None = None,
) -> bool:
    """Validate and persist one public route-health observation."""

    host_id = _input_token(host_id, label="host")
    route = _input_token(route, label="route")
    if not isinstance(status, str) or status not in {"reachable", "unreachable"}:
        raise MeshError("invalid_input", "status must be reachable or unreachable")
    validate_source(source)
    if (
        not isinstance(mesh_revision, str)
        or not mesh_revision
        or mesh_revision.strip() != mesh_revision
        or any(
            char.isspace() or unicodedata.category(char).startswith("C")
            for char in mesh_revision
        )
    ):
        raise MeshError("invalid_input", "meshRevision must be a nonempty token")
    if mesh_revision != mesh.mesh_revision:
        raise MeshError(
            "stale_mesh", "mesh revision does not match current configuration"
        )
    host = mesh.host_by_id(host_id.casefold())
    if host is None or host.local:
        raise MeshError("unknown_host", f"unknown remote host: {host_id}")
    selected_route = next(
        (
            candidate
            for candidate in host.routes
            if candidate.destination.casefold() == route.casefold()
        ),
        None,
    )
    if selected_route is None:
        raise MeshError("unknown_route", f"unknown route for host: {route}")
    timestamp = validate_report_time(observed_at, now_ms=now_ms)
    selected_health_store = health_store or RouteHealthStore.from_environment()
    return selected_health_store.record(
        host.id, selected_route.destination, status, timestamp
    )
