from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class EntrypointSmokeTests(unittest.TestCase):
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
                self.assertIn("\x00message\x1fSorted by frequency", result.stdout)
                state_path = state_home / "rofi-ssh-plus" / "history.json"
                self.assertTrue(state_path.exists())
                self.assertEqual(state_path.read_text(encoding="utf-8").count('"version": 1'), 1)
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
