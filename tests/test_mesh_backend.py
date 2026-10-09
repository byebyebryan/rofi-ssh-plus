"""Explicit shared authority selection without operational state access."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MeshBackendTests(unittest.TestCase):
    def invoke(self, backend, *, block_mesh=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config/rofi-ssh-plus/config.toml"
            config.parent.mkdir(parents=True)
            config.write_text('schema_version = 1\nlocal_id = "test-host"\n')
            state = root / "state/rofi-ssh-plus"
            state.mkdir(parents=True)
            history = state / "history.json"
            history.write_bytes(b'private history sentinel\n')
            env = {**os.environ, "ROFI_SSH_PLUS_MESH_BACKEND": backend,
                   "XDG_CONFIG_HOME": str(root / "config"),
                   "XDG_STATE_HOME": str(root / "state")}
            program = "import sys; sys.path.insert(0, sys.argv[1]); "
            if block_mesh:
                program += "sys.modules['mesh_plus'] = None; "
            program += "from rofi_ssh_plus.cli import main; sys.exit(main(['mesh','list','--json']))"
            result = subprocess.run([sys.executable, "-c", program, str(ROOT)],
                                    env=env, capture_output=True, timeout=3)
            self.assertEqual(result.stderr, b"")
            self.assertEqual(history.read_bytes(), b'private history sentinel\n')
            self.assertFalse((state / "route-health.json").exists())
            return result.returncode, json.loads(result.stdout)

    def test_legacy_selection_is_standalone(self):
        code, value = self.invoke("legacy", block_mesh=True)
        self.assertEqual(code, 0)
        self.assertEqual(value["localHostId"], "test-host")

    def test_missing_selected_mesh_fails_without_fallback(self):
        code, value = self.invoke("mesh-plus", block_mesh=True)
        self.assertEqual(code, 1)
        self.assertEqual(value["error"]["code"], "invalid_config")

    def test_unknown_selection_is_typed(self):
        code, value = self.invoke("unrecognized")
        self.assertEqual(code, 1)
        self.assertEqual(value["error"]["code"], "invalid_config")

    @unittest.skipUnless(importlib.util.find_spec("mesh_plus"), "Mesh package integration environment required")
    def test_mesh_selected_process_preserves_catalog_shape(self):
        legacy_code, legacy = self.invoke("legacy")
        mesh_code, mesh = self.invoke("mesh-plus")
        self.assertEqual((legacy_code, mesh_code), (0, 0))
        legacy.pop("generatedAt")
        mesh.pop("generatedAt")
        self.assertEqual(mesh, legacy)
