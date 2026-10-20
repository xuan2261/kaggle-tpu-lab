"""CPU-only integration contracts; never starts a Kaggle session."""
import ast
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
KERNELS = [
    ROOT / "qwen38-27b/kernel/serve_qwen38.py",
    ROOT / "glm53-flash/kernel/serve_glm53.py",
]
NOTEBOOKS = [
    ROOT / "qwen38-27b/notebook/qwen38-tpu-serve.ipynb",
    ROOT / "glm53-flash/notebook/glm53-tpu-serve.ipynb",
]


def load_launcher():
    spec = importlib.util.spec_from_file_location("kaggle_launcher", ROOT / "launch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IntegrationContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = load_launcher()

    def test_kernels_do_not_publish_credentials(self):
        for path in KERNELS:
            with self.subTest(kernel=path.name):
                content = path.read_text(encoding="utf-8")
                tree = ast.parse(content, filename=str(path))
                ready = [
                    node for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "publish"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "ready"
                ]
                self.assertEqual(len(ready), 1)
                self.assertNotIn("api_key", [kw.arg for kw in ready[0].keywords])
                self.assertIn('json.dumps({"phase": phase, **safe_extra})', content)

    def test_notebooks_keep_safe_publisher(self):
        for path in NOTEBOOKS:
            with self.subTest(notebook=path.name):
                notebook = json.loads(path.read_text(encoding="utf-8"))
                source = "\n".join(
                    "".join(cell.get("source", []))
                    for cell in notebook["cells"]
                    if cell.get("cell_type") == "code"
                )
                self.assertIn("safe_extra", source)
                self.assertIn("def publish(phase, **extra):", source)
                ready = [line for line in source.splitlines()
                         if line.lstrip().startswith('publish("ready",')]
                self.assertEqual(len(ready), 1)
                self.assertNotIn("api_key=", ready[0])

    def test_launcher_uses_current_glm_profile(self):
        source = (ROOT / "launch.py").read_text(encoding="utf-8")
        self.assertIn("rahim3/glm53-flash-serve-v3", source)
        self.assertIn('s.add_argument("--streams", type=int, default=3,', source)

    def test_launcher_reads_key_from_local_state(self):
        launcher = self.launcher
        original = launcher.STATE_FILE
        with tempfile.TemporaryDirectory() as temp:
            launcher.STATE_FILE = Path(temp) / "session.json"
            try:
                launcher.write_private_state({
                    "kernel": "test/glm", "topic": "test",
                    "api_key": "glm-0123456789abcdef01234567",
                    "model": "glm53-flash",
                })
                loaded = json.loads(launcher.STATE_FILE.read_text(encoding="utf-8"))
                self.assertEqual(loaded["model"], "glm53-flash")
                if os.name == "posix":
                    mode = stat.S_IMODE(launcher.STATE_FILE.stat().st_mode)
                    self.assertEqual(mode, 0o600)
                ready = {"phase": "ready", "endpoint": "https://example.test/v1",
                         "model": "glm-5.3-flash", "max_model_len": 262144}
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    launcher.render_event(ready)
                self.assertIn("glm-0123456789abcdef01234567", buffer.getvalue())
            finally:
                launcher.STATE_FILE = original


if __name__ == "__main__":
    unittest.main()
