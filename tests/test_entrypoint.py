from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class EntrypointSmokeTests(unittest.TestCase):
    def test_mesh_works_without_picker_or_launcher_modules(self) -> None:
        source_root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            config = root / "config/rofi-ssh-plus"
            config.mkdir(parents=True)
            shutil.copyfile(
                source_root / "contracts/host-mesh-v1/fixtures/config-multi-route.toml",
                config / "config.toml",
            )
            script = """
import importlib.abc
import json
import sys
class NoPicker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname in {
            'rofi_ssh_plus.launch', 'rofi_ssh_plus.model',
            'rofi_ssh_plus.protocol', 'rofi_ssh_plus.state',
        }:
            raise AssertionError('Mesh depends on picker module: ' + fullname)
sys.meta_path.insert(0, NoPicker())
from rofi_ssh_plus.cli import main
raise SystemExit(main(['mesh', 'list', '--json']))
"""
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=source_root,
                env={
                    **os.environ,
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_STATE_HOME": str(root / "state"),
                },
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            import json

            value = json.loads(result.stdout)
            self.assertEqual(value["localHostId"], "alpha")
            self.assertEqual(len(value["hosts"]), 3)
            self.assertFalse((root / "state/rofi-ssh-plus/history.json").exists())

    def test_package_exports_preserve_original_objects(self) -> None:
        import rofi_ssh_plus
        from rofi_ssh_plus import mesh, model, state

        for name in rofi_ssh_plus.__all__:
            module = (
                state if name == "StateStore"
                else model if name in {"HistoryState", "HostRecord"}
                else mesh
            )
            self.assertIs(getattr(rofi_ssh_plus, name), getattr(module, name))
            self.assertIn(name, dir(rofi_ssh_plus))
        with self.assertRaises(AttributeError):
            getattr(rofi_ssh_plus, "missing_export")

    def test_real_entrypoint_initializes_state_and_emits_headers(self) -> None:
        root = Path(tempfile.mkdtemp())
        try:
            source_root = Path(__file__).parents[1]
            install_root = root / "install"
            shutil.copytree(
                source_root / "rofi_ssh_plus",
                install_root / "rofi_ssh_plus",
                ignore=shutil.ignore_patterns("__pycache__", "*.py[co]"),
            )
            (install_root / "bin").mkdir()
            entrypoint = shutil.copy2(
                source_root / "bin" / "rofi-ssh-plus",
                install_root / "bin" / "rofi-ssh-plus",
            )
            script_dir = root / "scripts"
            script_dir.mkdir()
            discovered = script_dir / "ssh-plus"
            discovered.symlink_to(entrypoint.resolve())
            for executable, state_home in (
                (entrypoint, root / "direct-state"),
                (discovered, root / "discovered-state"),
            ):
                environment = os.environ.copy()
                environment["XDG_STATE_HOME"] = str(state_home)
                environment["ROFI_RETV"] = "0"
                result = subprocess.run(
                    [str(executable)],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("\x00use-hot-keys\x1ftrue", result.stdout)
                self.assertIn("\x00prompt\x1fSSH", result.stdout)
                self.assertNotIn("Frequent", result.stdout)
                self.assertNotIn("Recent", result.stdout)
                self.assertIn("\x00delim\x1f\\t\n", result.stdout)
                self.assertNotIn("Sorted by", result.stdout)
                state_path = state_home / "rofi-ssh-plus" / "history.json"
                self.assertTrue(state_path.exists())
                self.assertEqual(
                    state_path.read_text(encoding="utf-8").count('"version": 1'), 1
                )
            self.assertFalse(list(install_root.rglob("__pycache__")))
            self.assertFalse(list(install_root.rglob("*.py[co]")))
        finally:
            for path in sorted(root.rglob("*"), reverse=True):
                if path.is_file() or path.is_symlink():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            root.rmdir()


if __name__ == "__main__":
    unittest.main()
