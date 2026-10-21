"""Hermetic Kaggle Model Proxy gateway tests. No network beyond 127.0.0.1."""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import contextlib
import io
import json
import os
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tools import kaggle_model_proxy as gateway

LOCAL_KEY = "local-secret-key-0123456789abcdef"
REMOTE_KEY = "kaggle-remote-token-test-only"
MODEL = "google/gemini-3.5-flash"


def valid_config(origin="https://mp-staging.kaggle.net/models",
                 expiry=None, models=(MODEL, "anthropic/claude-haiku-4-5@20251001")):
    return gateway.ProxyConfig(
        origin, REMOTE_KEY,
        expiry or (datetime.now(timezone.utc) + timedelta(hours=1)),
        models,
    )


class MockKaggleHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        self.server.received.append({
            "path": self.path, "data": request, "auth": self.headers.get("Authorization"),
            "key": self.headers.get("x-api-key"),
            "version": self.headers.get("anthropic-version"),
        })
        if request.get("redirect"):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:{}/unexpected".format(self.server.server_port))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/openapi/v1/chat/completions" and request.get("stream"):
            data = (b'data: {"choices":[{"delta":{"content":"OK"},"index":0}]}\n\n'
                    b'data: [DONE]\n\n')
            content_type = "text/event-stream"
        elif self.path == "/anthropic/v1/messages":
            data = json.dumps({"content": [{"type": "text", "text": "OK"}]}).encode()
            content_type = "application/json"
        else:
            data = json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode()
            content_type = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / ".env.model-proxy"

    def write_config(self, url="https://mp-staging.kaggle.net/models",
                     models=MODEL, token=REMOTE_KEY, expiry=None):
        expiry = expiry or (datetime.now(timezone.utc) + timedelta(hours=1))
        self.path.write_text(
            "MODEL_PROXY_URL=" + url + "\n" +
            "MODEL_PROXY_API_KEY=" + token + "\n" +
            "MODEL_PROXY_EXPIRY_TIME=" + expiry.isoformat() + "\n" +
            "LLMS_AVAILABLE=" + models + "\n", encoding="utf-8",
        )
        if os.name != "nt":
            self.path.chmod(0o600)

    def test_reads_curated_model_list_and_appended_refresh(self):
        self.write_config(models=MODEL + ",anthropic/claude-haiku-4-5@20251001")
        with self.path.open("a", encoding="utf-8") as out:
            out.write('export MODEL_PROXY_API_KEY="rotated-test-token"\n')
        c = gateway.load_config(self.path)
        self.assertEqual(c.api_key, "rotated-test-token")
        self.assertEqual(len(c.models), 2)
        self.assertEqual(c.origin, "https://mp-staging.kaggle.net/models")
        self.assertFalse(c.expired())

    def test_restricts_local_models(self):
        self.write_config(models="")
        with self.assertRaises(gateway.ConfigError):
            gateway.load_config(self.path)

    def test_rejects_host_spoofing_and_protocol_downgrade(self):
        for url in (
            "http://mp-staging.kaggle.net/models",
            "https://mp-staging.kaggle.net.evil.example/models",
            "https://someone:password@mp-staging.kaggle.net/models",
            "https://mp-staging.kaggle.net/models?api_key=secret",
            "https://mp-staging.kaggle.net:invalid/models",
        ):
            with self.subTest(url=url):
                self.write_config(url=url)
                with self.assertRaises(gateway.ConfigError):
                    gateway.load_config(self.path)

    def test_rejects_open_group_permissions_and_symlink(self):
        self.write_config()
        if os.name != "nt":
            self.path.chmod(0o644)
            with self.assertRaises(gateway.ConfigError):
                gateway.load_config(self.path)
            self.path.chmod(0o600)
        linked = Path(self.temp.name) / "link.env"
        try:
            linked.symlink_to(self.path)
        except (OSError, NotImplementedError):
            return
        with self.assertRaises(gateway.ConfigError):
            gateway.load_config(linked)

    def test_doctor_never_echoes_remote_token(self):
        self.write_config()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = gateway.command_line(["--env-file", str(self.path), "doctor"])
        self.assertEqual(status, 0)
        self.assertNotIn(REMOTE_KEY, output.getvalue())
        self.assertIn("No model requests sent", output.getvalue())

    def test_read_only_quota_command_parses_known_fields(self):
        payload = '[{"period":"Daily","used":"$1","remaining":"$9","total":"$10","refillAt":"tomorrow"}]'
        with patch.object(gateway.subprocess, "run",
                          return_value=SimpleNamespace(returncode=0, stdout=payload)) as run:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = gateway.command_line(["quota"])
        self.assertEqual(result, 0)
        self.assertIn("Daily", output.getvalue())
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0],
                         ["kaggle", "benchmarks", "quota", "--format", "json"])


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), MockKaggleHandler)
        self.upstream.received = []
        self.upthread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.upthread.start()
        origin = "http://127.0.0.1:" + str(self.upstream.server_port)
        self.config = valid_config(origin=origin)
        self.gate = gateway.LocalGateway(
            ("127.0.0.1", 0), lambda: self.config, LOCAL_KEY,
            max_requests=2, max_output_tokens=120, timeout=5
        )
        self.gatethread = threading.Thread(target=self.gate.serve_forever, daemon=True)
        self.gatethread.start()

    def tearDown(self):
        self.gate.shutdown()
        self.gate.server_close()
        self.gatethread.join(timeout=3)
        self.upstream.shutdown()
        self.upstream.server_close()
        self.upthread.join(timeout=3)

    def call(self, path, body=None, auth=True, scheme="openai", extra=None):
        headers = dict(extra or {})
        if auth:
            headers.update({"x-api-key": LOCAL_KEY} if scheme == "anthropic" else
                           {"Authorization": "Bearer " + LOCAL_KEY})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = Request("http://127.0.0.1:" + str(self.gate.server_port) + path,
                      data=data, headers=headers, method="POST" if data is not None else "GET")
        try:
            with urlopen(req, timeout=5) as response:
                return response.status, response.read()
        except HTTPError as exc:
            return exc.code, exc.read()

    def test_rejects_unauthorized_client(self):
        status, content = self.call("/v1/models", auth=False)
        self.assertEqual(status, 401)
        self.assertNotIn(REMOTE_KEY.encode(), content)
        self.assertFalse(self.upstream.received)

    def test_curated_model_catalog(self):
        status, content = self.call("/v1/models")
        self.assertEqual(status, 200)
        ids = [x["id"] for x in json.loads(content)["data"]]
        self.assertEqual(ids, list(self.config.models))
        self.assertNotIn(REMOTE_KEY.encode(), content)

    def test_openai_passes_remote_auth_but_not_local_key(self):
        status, content = self.call("/v1/chat/completions",
                                    {"model": MODEL, "messages": [{"role": "user", "content": "hi"}],
                                     "max_tokens": 24})
        self.assertEqual(status, 200)
        self.assertIn(b"choices", content)
        item = self.upstream.received[0]
        self.assertEqual(item["auth"], "Bearer " + REMOTE_KEY)
        self.assertIsNone(item["key"])
        self.assertEqual(item["data"]["max_tokens"], 24)

    def test_anthropic_passes_key_and_version(self):
        status, content = self.call("/v1/messages",
                                    {"model": MODEL, "messages": [{"role": "user", "content": "hi"}],
                                     "max_tokens": 20}, scheme="anthropic")
        self.assertEqual(status, 200)
        self.assertIn(b"content", content)
        self.assertEqual(self.upstream.received[0]["key"], REMOTE_KEY)
        self.assertEqual(self.upstream.received[0]["version"], "2023-06-01")

    def test_openai_responses_path(self):
        status, _ = self.call("/v1/responses", {"model": MODEL, "input": "hi"})
        self.assertEqual(status, 200)
        self.assertEqual(self.upstream.received[0]["path"], "/openapi/v1/responses")
        self.assertEqual(self.upstream.received[0]["data"]["max_output_tokens"], 120 if 120 < 256 else 256)

    def test_stream_is_forwarded_without_synthetic_conversion(self):
        status, data = self.call("/v1/chat/completions",
                                 {"model": MODEL, "messages": [], "stream": True, "max_tokens": 24})
        self.assertEqual(status, 200)
        self.assertIn(b"data: [DONE]", data)

    def test_unknown_model_and_too_many_tokens_rejected_without_charge(self):
        status, _ = self.call("/v1/chat/completions", {"model": "openai/not-authorized", "messages": []})
        self.assertEqual(status, 403)
        status, _ = self.call("/v1/chat/completions",
                              {"model": MODEL, "messages": [], "max_tokens": 1000000})
        self.assertEqual(status, 422)
        self.assertEqual(self.gate.requests_made, 0)
        self.assertFalse(self.upstream.received)

    def test_expired_proxy_token_fails_closed(self):
        self.config = valid_config(origin=self.config.origin,
                                   expiry=datetime.now(timezone.utc) - timedelta(minutes=1))
        status, content = self.call("/v1/chat/completions", {"model": MODEL, "messages": []})
        self.assertEqual(status, 503)
        self.assertIn(b"expired", content)
        self.assertFalse(self.upstream.received)

    def test_upstream_redirect_does_not_send_kaggle_token_to_other_host(self):
        status, _ = self.call("/v1/chat/completions",
                              {"model": MODEL, "messages": [], "redirect": True})
        self.assertEqual(status, 502)
        self.assertEqual(len(self.upstream.received), 1)
        self.assertEqual(self.upstream.received[0]["auth"], "Bearer " + REMOTE_KEY)

    def test_local_request_cap(self):
        for _ in range(2):
            status, _ = self.call("/v1/chat/completions", {"model": MODEL, "messages": []})
            self.assertEqual(status, 200)
        status, _ = self.call("/v1/chat/completions", {"model": MODEL, "messages": []})
        self.assertEqual(status, 429)
        self.assertEqual(len(self.upstream.received), 2)

    def test_blocks_browser_origin_and_unknown_routes(self):
        status, _ = self.call("/v1/models", extra={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        status, _ = self.call("/v1/embeddings")
        self.assertEqual(status, 404)
        self.assertEqual(self.gate.requests_made, 0)

    def test_gateway_rejects_remote_bind_and_short_client_key(self):
        with self.assertRaises(gateway.ConfigError):
            gateway.LocalGateway(("0.0.0.0", 0), lambda: self.config, LOCAL_KEY)
        with self.assertRaises(gateway.ConfigError):
            gateway.LocalGateway(("127.0.0.1", 0), lambda: self.config, "short")


if __name__ == "__main__":
    unittest.main()
