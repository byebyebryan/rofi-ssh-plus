from __future__ import annotations

import subprocess
import sys
import unittest
from types import SimpleNamespace

from rofi_ssh_plus.launch import run_worker, spawn_detached, terminal_argv, worker_argv
from rofi_ssh_plus.model import InvalidDestination
from rofi_ssh_plus.probe import ProbeResult, build_probe_argv, classify_probe, run_probe


class ProbeTests(unittest.TestCase):
    def test_probe_argv_is_separate_and_uses_batch_mode(self) -> None:
        self.assertEqual(
            build_probe_argv("User@Host", timeout=4),
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", "user@host", "true"],
        )

    def test_classifies_success_and_reached_server_markers(self) -> None:
        self.assertTrue(classify_probe(0, ""))
        for stderr in (
            "Permission denied (publickey,password).",
            "Host key verification failed.",
            "REMOTE HOST IDENTIFICATION HAS CHANGED!",
            "userauth_pubkey: key type ssh-rsa not in PubkeyAcceptedAlgorithms",
        ):
            with self.subTest(stderr=stderr):
                self.assertTrue(classify_probe(255, stderr))
        for stderr in ("Could not resolve hostname typo", "Connection refused", "Connection timed out"):
            with self.subTest(stderr=stderr):
                self.assertFalse(classify_probe(255, stderr))
        self.assertFalse(classify_probe(None, "Permission denied", timed_out=True))

    def test_run_probe_handles_success_timeout_and_missing_binary(self) -> None:
        calls: list[tuple[list[str], dict[str, object]]] = []

        def success(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, "", "")

        result = run_probe("host", timeout=2, runner=success)
        self.assertTrue(result.reached_server)
        self.assertEqual(calls[0][0][-2:], ["host", "true"])
        self.assertEqual(calls[0][1]["timeout"], 3)

        def timeout(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(argv, 3, stderr=b"Permission denied")

        self.assertFalse(run_probe("host", runner=timeout).reached_server)

        def missing(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError("ssh")

        self.assertFalse(run_probe("host", runner=missing).reached_server)


class LaunchTests(unittest.TestCase):
    def test_terminal_and_worker_argv_are_shell_free(self) -> None:
        self.assertEqual(terminal_argv("HOST", terminal="foot", ssh_command="ssh"), ["foot", "-e", "ssh", "host"])
        self.assertEqual(terminal_argv("HOST", terminal="foot --app-id ssh", ssh_command="ssh"), ["foot", "--app-id", "ssh", "-e", "ssh", "host"])
        with self.assertRaises(InvalidDestination):
            terminal_argv("-oProxyCommand=bad")
        command = worker_argv("HOST", entrypoint="/tmp/rofi-ssh-plus")
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1:], ["/tmp/rofi-ssh-plus", "--worker", "host"])

    def test_spawn_detached_sets_independent_session_and_private_stdio(self) -> None:
        calls: list[tuple[list[str], dict[str, object]]] = []

        def fake(argv: list[str], **kwargs: object) -> object:
            calls.append((argv, kwargs))
            return SimpleNamespace()

        self.assertTrue(spawn_detached(["thing", "arg"], popen=fake))
        self.assertEqual(calls[0][0], ["thing", "arg"])
        self.assertTrue(calls[0][1]["start_new_session"])
        self.assertTrue(calls[0][1]["close_fds"])
        self.assertIs(calls[0][1]["stdin"], subprocess.DEVNULL)

    def test_worker_records_only_reached_server_but_always_launches(self) -> None:
        class FakeStore:
            def __init__(self) -> None:
                self.hosts: list[str] = []

            def record_success(self, host: str) -> None:
                self.hosts.append(host)

        launched: list[list[str]] = []
        store = FakeStore()

        def reached(host: str, **kwargs: object) -> ProbeResult:
            return ProbeResult(255, "Permission denied", True)

        self.assertEqual(
            run_worker("Host", store=store, probe=reached, terminal_launcher=lambda argv: launched.append(list(argv)) or True),
            0,
        )
        self.assertEqual(store.hosts, ["host"])
        self.assertEqual(launched[0][-2:], ["ssh", "host"])

        def unreachable(host: str, **kwargs: object) -> ProbeResult:
            return ProbeResult(255, "Could not resolve hostname", False)

        self.assertEqual(
            run_worker("other", store=store, probe=unreachable, terminal_launcher=lambda argv: launched.append(list(argv)) or True),
            0,
        )
        self.assertEqual(store.hosts, ["host"])

    def test_worker_launches_even_when_state_write_fails(self) -> None:
        class BrokenStore:
            def record_success(self, host: str) -> None:
                raise OSError("read-only")

        launched: list[list[str]] = []
        result = run_worker(
            "host",
            store=BrokenStore(),
            probe=lambda host, **kwargs: ProbeResult(0, "", True),
            terminal_launcher=lambda argv: launched.append(list(argv)) or True,
        )
        self.assertEqual(result, 0)
        self.assertEqual(launched[0][-2:], ["ssh", "host"])


if __name__ == "__main__":
    unittest.main()
