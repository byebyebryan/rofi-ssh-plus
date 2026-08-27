"""Versioned, locked, atomically persisted SSH history."""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - this application targets Linux
    fcntl = None  # type: ignore[assignment]

from .model import (
    HostRecord,
    HistoryState,
    InvalidDestination,
    SORT_FREQUENCY,
    SORT_MODES,
    normalize_destination,
)
from .ranking import sort_hosts


SCHEMA_VERSION = 1
DEFAULT_MAX_HOSTS = 100


class StateStore:
    """Manage the generic history and perform one-time DMS migration.

    Every public operation takes the advisory lock and reloads the file.  That
    keeps concurrent Rofi invocations and detached workers from losing an
    update.  A missing generic file is initialized under the same lock, even
    when the legacy file is absent or malformed; this is the one-time import
    marker.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        legacy_path: str | os.PathLike[str] | None = None,
        *,
        max_hosts: int = DEFAULT_MAX_HOSTS,
    ) -> None:
        self.path = Path(path).expanduser()
        if legacy_path is None:
            legacy_path = self.path.parent / "DankMaterialShell" / "plugins" / "sshPlus_state.json"
        self.legacy_path = Path(legacy_path).expanduser()
        self.max_hosts = max(1, int(max_hosts))

    @classmethod
    def from_environment(cls, environ: dict[str, str] | None = None) -> "StateStore":
        env = os.environ if environ is None else environ
        state_home = Path(env.get("XDG_STATE_HOME") or "~/.local/state").expanduser()
        return cls(
            state_home / "rofi-ssh-plus" / "history.json",
            state_home / "DankMaterialShell" / "plugins" / "sshPlus_state.json",
        )

    @property
    def lock_path(self) -> Path:
        return self.path.with_name(f".{self.path.name}.lock")

    def load(self) -> HistoryState:
        with self._locked():
            return self._load_and_initialize_unlocked()

    def record_success(self, host: str, now_ms: int | None = None) -> HistoryState:
        canonical = normalize_destination(host)
        timestamp = int(now_ms if now_ms is not None else time.time() * 1000)
        if timestamp < 0:
            raise ValueError("timestamp must not be negative")
        with self._locked():
            state = self._load_and_initialize_unlocked()
            records = list(state.hosts)
            for index, record in enumerate(records):
                if record.host.casefold() == canonical:
                    records[index] = HostRecord(canonical, timestamp, record.count + 1)
                    break
            else:
                records.append(HostRecord(canonical, timestamp, 1))
            records = self._trim(records, state.sort_mode)
            result = HistoryState(tuple(records), state.sort_mode)
            self._write_unlocked(result)
            return result

    def remove(self, host: str) -> tuple[bool, HistoryState]:
        canonical = normalize_destination(host)
        with self._locked():
            state = self._load_and_initialize_unlocked()
            records = [record for record in state.hosts if record.host.casefold() != canonical]
            removed = len(records) != len(state.hosts)
            result = HistoryState(tuple(records), state.sort_mode)
            if removed:
                self._write_unlocked(result)
            return removed, result

    def set_sort_mode(self, sort_mode: str) -> HistoryState:
        if sort_mode not in SORT_MODES:
            raise ValueError(f"unknown sort mode: {sort_mode}")
        with self._locked():
            state = self._load_and_initialize_unlocked()
            result = HistoryState(state.hosts, sort_mode)
            self._write_unlocked(result)
            return result

    def toggle_sort_mode(self) -> HistoryState:
        with self._locked():
            state = self._load_and_initialize_unlocked()
            next_mode = "recency" if state.sort_mode == SORT_FREQUENCY else SORT_FREQUENCY
            result = HistoryState(state.hosts, next_mode)
            self._write_unlocked(result)
            return result

    def _trim(self, records: list[HostRecord], sort_mode: str) -> list[HostRecord]:
        return sort_hosts(records, sort_mode)[: self.max_hosts]

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                os.chmod(self.lock_path, 0o600)
            except OSError:
                pass
            if fcntl is None:  # pragma: no cover
                raise RuntimeError("advisory file locking is unavailable")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _load_and_initialize_unlocked(self) -> HistoryState:
        if self.path.exists():
            return self._read_generic()
        state = self._read_legacy()
        self._write_unlocked(state)
        return state

    def _read_generic(self) -> HistoryState:
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, ValueError, TypeError):
            return HistoryState(())
        return self._state_from_payload(payload)

    def _read_legacy(self) -> HistoryState:
        try:
            with self.legacy_path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, ValueError, TypeError):
            return HistoryState(())
        return self._state_from_payload(payload, legacy=True)

    def _state_from_payload(self, payload: object, *, legacy: bool = False) -> HistoryState:
        if not isinstance(payload, dict):
            return HistoryState(())
        if not legacy and payload.get("version", SCHEMA_VERSION) != SCHEMA_VERSION:
            return HistoryState(())
        raw_hosts = payload.get("hosts")
        if not isinstance(raw_hosts, list):
            return HistoryState(())
        sort_mode = payload.get("sortMode", payload.get("sort_mode", SORT_FREQUENCY))
        if sort_mode not in SORT_MODES:
            sort_mode = SORT_FREQUENCY
        records: dict[str, HostRecord] = {}
        for raw in raw_hosts:
            if not isinstance(raw, dict):
                continue
            raw_host = raw.get("host")
            try:
                host = normalize_destination(raw_host)
            except (InvalidDestination, TypeError):
                continue
            count = self._positive_int(raw.get("count"), default=1)
            timestamp = self._nonnegative_int(
                raw.get("lastConnected", raw.get("last_connected")), default=0
            )
            record = HostRecord(host, timestamp, count)
            existing = records.get(host)
            if existing is None:
                records[host] = record
            else:
                records[host] = HostRecord(
                    host,
                    max(existing.last_connected, record.last_connected),
                    existing.count + record.count,
                )
        result = HistoryState(tuple(self._trim(list(records.values()), sort_mode)), sort_mode)
        if legacy:
            return HistoryState(result.hosts, SORT_FREQUENCY)
        return result

    @staticmethod
    def _positive_int(value: object, *, default: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return default
        return value

    @staticmethod
    def _nonnegative_int(value: object, *, default: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return default
        return value

    def _write_unlocked(self, state: HistoryState) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        temporary_path = Path(temporary)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(state.to_dict(), stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
            try:
                directory_fd = os.open(self.path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
