"""Offline integrity contracts for the two standalone Kaggle kernel scripts.

Load only selected AST functions: importing either kernel starts runtime work.
No network, TPU, cloudflared execution or persistent cache is touched.
"""
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
KERNELS = (
    (ROOT / "qwen38-27b/kernel/serve_qwen38.py",
     ROOT / "qwen38-27b/notebook/qwen38-tpu-serve.ipynb",
     "%%writefile serve_qwen38.py\n"),
    (ROOT / "glm53-flash/kernel/serve_glm53.py",
     ROOT / "glm53-flash/notebook/glm53-tpu-serve.ipynb",
     "%%writefile serve_glm53.py\n"),
)
OFFICIAL_RELEASE_SHA = "ae5e8add7884b0531d66bbca4570d1de491ff6da51e4ebe7eb160cdf241d9e42"
OFFICIAL_RELEASE_SIZE = 40247428


class IntegrityContracts(unittest.TestCase):
    def make_kernel_helpers(self, kernel, directory, trusted=b"unit-tested-cloudflared"):
        tree = ast.parse(kernel.read_text(encoding="utf-8"), filename=str(kernel))
        names = {"cloudflared_verified", "install_cloudflared"}
        funcs = [item for item in tree.body
                 if isinstance(item, ast.FunctionDef) and item.name in names]
        self.assertEqual({func.name for func in funcs}, names)
        # The release digest is replaced solely in the hermetic helper namespace.
        # Real pinned constants and their cross-kernel parity are tested separately.
        urlopen = Mock(side_effect=lambda *_args, **_kwargs: io.BytesIO(trusted))
        namespace = {
            "CLOUDFLARED": directory / "cloudflared",
            "CLOUDFLARED_SHA256": hashlib.sha256(trusted).hexdigest(),
            "CLOUDFLARED_BYTES": len(trusted),
            "CLOUDFLARED_URL": "https://example.invalid/fixture",
            "_CLOUDFLARED_LOCK": threading.Lock(),
            "Path": Path, "tempfile": tempfile, "os": os,
            "hashlib": hashlib, "secrets": secrets,
            "urllib": SimpleNamespace(request=SimpleNamespace(urlopen=urlopen)),
        }
        exec(compile(ast.fix_missing_locations(ast.Module(body=funcs, type_ignores=[])),
                     str(kernel), "exec"), namespace)
        return namespace, urlopen

    def test_exact_official_pin_and_standalone_notebooks(self):
        for kernel, notebook, magic in KERNELS:
            with self.subTest(kernel=kernel.name):
                source = kernel.read_text(encoding="utf-8")
                tree = ast.parse(source)
                constants = {
                    target.id: ast.literal_eval(node.value)
                    for node in tree.body if isinstance(node, ast.Assign)
                    for target in node.targets if isinstance(target, ast.Name)
                    and target.id in ("CLOUDFLARED_VERSION", "CLOUDFLARED_SHA256",
                                      "CLOUDFLARED_BYTES")
                }
                self.assertEqual(constants, {
                    "CLOUDFLARED_VERSION": "2026.10.4",
                    "CLOUDFLARED_SHA256": OFFICIAL_RELEASE_SHA,
                    "CLOUDFLARED_BYTES": OFFICIAL_RELEASE_SIZE,
                })
                self.assertIn("releases/download/{CLOUDFLARED_VERSION}/", source)
                self.assertNotIn("releases/latest/download/cloudflared", source)
                cells = json.loads(notebook.read_text(encoding="utf-8"))["cells"]
                matches = ["".join(c.get("source", [])) for c in cells
                           if "".join(c.get("source", [])).startswith(magic)]
                self.assertEqual(matches, [magic + source])

    def test_healthy_cached_binary_never_triggers_download(self):
        for kernel, _, _ in KERNELS:
            with self.subTest(kernel=kernel.name), tempfile.TemporaryDirectory() as directory:
                cache = Path(directory) / "cloudflared"
                cache.write_bytes(b"unit-tested-cloudflared")
                helpers, request = self.make_kernel_helpers(kernel, Path(directory))
                self.assertTrue(helpers["cloudflared_verified"](cache))
                self.assertTrue(helpers["install_cloudflared"]())
                request.assert_not_called()
                self.assertEqual(cache.read_bytes(), b"unit-tested-cloudflared")

    def test_download_is_verified_and_atomically_replaces_bad_cache(self):
        for kernel, _, _ in KERNELS:
            with self.subTest(kernel=kernel.name), tempfile.TemporaryDirectory() as directory:
                cache = Path(directory) / "cloudflared"
                cache.write_bytes(b"old-unverified")
                helpers, request = self.make_kernel_helpers(kernel, Path(directory))
                self.assertFalse(helpers["cloudflared_verified"](cache))
                self.assertTrue(helpers["install_cloudflared"]())
                request.assert_called_once()
                self.assertTrue(helpers["cloudflared_verified"](cache))
                self.assertEqual(cache.read_bytes(), b"unit-tested-cloudflared")
                self.assertEqual(list(Path(directory).glob(".cloudflared-*")), [])

    def test_wrong_digest_truncated_and_oversized_downloads_fail_closed(self):
        expected = b"unit-tested-cloudflared"
        for kernel, _, _ in KERNELS:
            for payload in (b"bad" + expected[3:], expected[:-1], expected + b"x"):
                with self.subTest(kernel=kernel.name, length=len(payload)), \
                        tempfile.TemporaryDirectory() as directory:
                    cache = Path(directory) / "cloudflared"
                    cache.write_bytes(b"old-unverified")
                    helpers, request = self.make_kernel_helpers(kernel, Path(directory))
                    request.side_effect = lambda *_args, **_kwargs: io.BytesIO(payload)
                    with self.assertRaisesRegex(ValueError, "pinned|exceeds"):
                        helpers["install_cloudflared"]()
                    self.assertEqual(cache.read_bytes(), b"old-unverified")
                    self.assertFalse(helpers["cloudflared_verified"](cache))
                    self.assertEqual(list(Path(directory).glob(".cloudflared-*")), [])

    def test_failed_transfer_cleans_staging_without_replacing_cache(self):
        class BrokenStream(io.BytesIO):
            def read(self, size=-1):
                if self.tell():
                    raise OSError("connection interrupted")
                return super().read(3)

        for kernel, _, _ in KERNELS:
            with self.subTest(kernel=kernel.name), tempfile.TemporaryDirectory() as directory:
                cache = Path(directory) / "cloudflared"
                cache.write_bytes(b"old-unverified")
                helpers, request = self.make_kernel_helpers(kernel, Path(directory))
                request.side_effect = lambda *_args, **_kwargs: BrokenStream(b"partial")
                with self.assertRaises(OSError):
                    helpers["install_cloudflared"]()
                self.assertEqual(cache.read_bytes(), b"old-unverified")
                self.assertEqual(list(Path(directory).glob(".cloudflared-*")), [])

    def test_bundle_is_verifiable_but_bad_bundle_cannot_be_run(self):
        for kernel, _, _ in KERNELS:
            with self.subTest(kernel=kernel.name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                cache = root / "cloudflared"
                bundle = root / "bundle-cloudflared"
                bundle.write_bytes(b"not-the-pinned-release")
                helpers, request = self.make_kernel_helpers(kernel, root)
                with self.assertRaises(ValueError):
                    helpers["install_cloudflared"](bundle)
                self.assertFalse(cache.exists())
                bundle.write_bytes(b"unit-tested-cloudflared")
                self.assertTrue(helpers["install_cloudflared"](bundle))
                self.assertTrue(helpers["cloudflared_verified"](cache))
                request.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "symlink semantics covered on Linux CI")
    def test_untrusted_cache_symlink_does_not_touch_referent(self):
        for kernel, _, _ in KERNELS:
            with self.subTest(kernel=kernel.name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                victim = root / "unrelated-file"
                victim.write_bytes(b"must-not-be-overwritten")
                cache = root / "cloudflared"
                cache.symlink_to(victim)
                helpers, _ = self.make_kernel_helpers(kernel, root)
                self.assertFalse(helpers["cloudflared_verified"](cache))
                self.assertTrue(helpers["install_cloudflared"]())
                self.assertFalse(cache.is_symlink())
                self.assertTrue(helpers["cloudflared_verified"](cache))
                self.assertEqual(victim.read_bytes(), b"must-not-be-overwritten")


if __name__ == "__main__":
    unittest.main()
