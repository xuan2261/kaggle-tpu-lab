"""Offline contracts for the redacted preflight projection; no Kaggle access."""
import ast
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools/resource_preflight.py"
SPEC = importlib.util.spec_from_file_location("resource_preflight", SOURCE)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


class ReadOnlyPreflightTests(unittest.TestCase):
    def test_both_supported_profiles_are_target_not_observed_hardware(self):
        for profile, served in (("qwen38-27b", "qwen3.8-27b"),
                                ("glm53-flash", "glm-5.3-flash")):
            with self.subTest(profile=profile):
                report = preflight.build_preflight(profile)
                self.assertEqual(report["model"]["served_id"], served)
                self.assertEqual(report["model"]["target_device_count"], 8)
                self.assertEqual(report["readiness"], "inconclusive")
                self.assertIsNone(report["observed"]["accelerator"]["device_count"])
                self.assertIsNone(report["observed"]["disk"]["available_bytes"])
                self.assertFalse(report["provenance"]["hardware_verified"])
                self.assertFalse(report["provenance"]["inference_verified"])
                self.assertEqual(report["checks"]["inference_requests_sent"], 0)
                self.assertEqual(report["checks"]["mutating_actions"], 0)
                self.assertEqual(report["checks"]["openai_sse"], "not_checked")
                self.assertEqual(report["session"]["phase"]["source"], "not_provided")

    def test_ready_snapshot_does_not_become_tpu_verified(self):
        report = preflight.build_preflight("qwen38-27b", {
            "model": "qwen38-27b", "phase": "ready",
            "kaggleStatus": "running", "endpointLive": True,
            "endpoint": "https://example.invalid/v1",
            "hasApiKey": True, "decodeTokS": 35.5,
            "readyAtEstimated": True, "remainingSecs": 900,
            "remainingEstimated": True, "maxModelLen": 262144,
            "keepaliveMin": 480, "textOnly": False, "mtpTokens": 3,
        })
        self.assertEqual(report["session"]["phase"]["value"], "ready")
        self.assertTrue(report["session"]["endpoint_present"]["value"])
        self.assertTrue(report["session"]["endpoint_live_claim"]["value"])
        self.assertEqual(report["observed"]["decode_tokens_per_second"]["value"], 35.5)
        self.assertEqual(report["configured"]["context_tokens"]["source"],
                         "companion_effective_or_settings_fallback")
        self.assertIsNone(report["observed"]["accelerator"]["device_count"])
        self.assertEqual(report["readiness"], "inconclusive")
        self.assertEqual(report["checks"]["openai_sse"], "not_checked")

    def test_redacts_secrets_urls_and_unrecognized_free_text(self):
        marker = "sk-FIXTURE-SHOULD-NEVER-APPEAR"
        report = preflight.build_preflight("glm53-flash", {
            "model": "glm53-flash",
            "endpoint": "https://name:" + marker + "@host.invalid/v1?api_key=" + marker,
            "apiKey": marker, "ntfyTopic": marker,
            "kernel": marker, "error": marker,
            "activity": [{"note": marker, "token": marker}],
            "source": {"bearer": marker}, "phase": marker, "decodeTokS": -100,
        })
        output = json.dumps(report)
        self.assertNotIn(marker, output)
        self.assertNotIn("host.invalid", output)
        self.assertTrue(report["session"]["endpoint_present"]["value"])
        self.assertEqual(report["session"]["phase"]["source"], "invalid_or_unknown")
        self.assertEqual(report["observed"]["decode_tokens_per_second"]["source"],
                         "invalid_or_unknown")
        self.assertNotIn("mtp_tokens", report["configured"])

    def test_profile_mismatch_unsupported_and_type_confusion_fail(self):
        with self.assertRaises(ValueError):
            preflight.build_preflight("another-model")
        with self.assertRaises(ValueError):
            preflight.build_preflight("glm53-flash", {"model": "qwen38-27b"})
        with self.assertRaises(ValueError):
            preflight.build_preflight("glm53-flash", ["not a dict"])
        report = preflight.build_preflight("qwen38-27b", {
            "uptimeSecs": True, "readyAt": -1, "decodeTokS": float("nan"),
            "endpointLive": "true", "maxModelLen": True, "phase": None,
        })
        for field in ("uptime_secs", "ready_at", "endpoint_live_claim"):
            self.assertIsNone(report["session"][field]["value"])
        self.assertIsNone(report["configured"]["context_tokens"]["value"])
        self.assertIsNone(report["observed"]["decode_tokens_per_second"]["value"])
        self.assertEqual(report["session"]["phase"]["source"], "unavailable_in_snapshot")
        json.dumps(report, allow_nan=False)

    def test_optional_json_file_is_bounded_and_not_auto_discovered(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "snapshot.json"
            file.write_text(json.dumps({
                "model": "glm53-flash", "phase": "loadingWeights",
                "apiKey": "private-fixture-token",
                "endpoint": "https://hidden.invalid/v1",
            }), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = preflight.main(["--profile", "glm53-flash",
                                         "--snapshot-file", str(file)])
            self.assertEqual(status, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["session"]["phase"]["value"], "loadingWeights")
            self.assertNotIn("private-fixture-token", output.getvalue())
            self.assertNotIn("hidden.invalid", output.getvalue())
            file.write_bytes(b"0" * (preflight.MAX_SNAPSHOT_BYTES + 1))
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                status = preflight.main(["--profile", "glm53-flash",
                                         "--snapshot-file", str(file)])
            self.assertEqual(status, 1)
            self.assertNotIn(str(file), stderr.getvalue())

    def test_pure_code_never_imports_device_or_network_tools(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        imported = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                imported.add(node.module.split(".")[0])
        self.assertFalse(imported.intersection({
            "jax", "torch", "requests", "kaggle", "subprocess",
            "urllib", "socket", "http", "psutil",
        }))


if __name__ == "__main__":
    unittest.main()
