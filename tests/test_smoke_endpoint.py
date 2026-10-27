"""Hermetic test of tools/smoke_endpoint.py; uses only loopback HTTP."""
import importlib.util
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

PATH = Path(__file__).resolve().parents[1] / "tools" / "smoke_endpoint.py"
spec = importlib.util.spec_from_file_location("smoke_endpoint", PATH)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_json(self, content):
        data = json.dumps(content).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        if self.headers.get("Authorization") != "Bearer unit-test-only":
            self.send_error(401)
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        if self.path == "/v1/models":
            self.send_json({"data": [{"id": "glm-5.3-flash"}]})
        else:
            self.send_error(404)

    def do_POST(self):
        if not self.authorized():
            return
        request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if self.path == "/v1/messages":
            self.send_json({"content": [{"type": "text", "text": "OK"}]})
        elif self.path == "/v1/chat/completions" and request.get("stream"):
            data = (b'data: {"choices":[{"delta":{"content":"OK"},"index":0}]}\n\n'
                    b'data: [DONE]\n\n')
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/v1/chat/completions":
            self.send_json({"choices": [{"message": {"role": "assistant", "content": "OK"}}]})
        else:
            self.send_error(404)


class SmokeTests(unittest.TestCase):
    def test_rejects_unsafe_remote_url(self):
        for url in ("http://example.com/v1", "https://bob:pw@example.com/v1",
                    "https://example.com/v1?token=x", "https://example.com/path"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                smoke.normalize_base_url(url)

    def test_accepts_https_and_loopback(self):
        self.assertEqual(smoke.normalize_base_url("https://example.com/"),
                         "https://example.com/v1")
        self.assertEqual(smoke.normalize_base_url("http://127.0.0.1:8000/v1"),
                         "http://127.0.0.1:8000/v1")

    def test_mock_endpoint_contract(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            checks = smoke.run_smoke("http://127.0.0.1:" + str(server.server_port),
                                     "unit-test-only", "glm-5.3-flash", timeout=5)
            self.assertEqual(len(checks), 5)
            self.assertTrue(any("SSE" in c for c in checks))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_offline_fixture_rejects_bad_bearer_and_wrong_model(self):
        """This asserts smoke-client handling, not real GLM GET /models auth."""
        server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = "http://127.0.0.1:" + str(server.server_port) + "/v1"
            with self.assertRaisesRegex(RuntimeError, "HTTP status 401"):
                smoke.json_request(base + "/models", "wrong", timeout=3)
            with self.assertRaisesRegex(RuntimeError, "Streaming HTTP status 401"):
                smoke.sse_request(base + "/chat/completions", "wrong", "glm-5.3-flash", 3)
            with self.assertRaisesRegex(RuntimeError, "Model ID was not found"):
                smoke.run_smoke(base, "unit-test-only", "wrong-model", timeout=3)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_sse_incomplete_and_error_events_fail_closed(self):
        fixtures = [
            (b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
             "Incomplete OpenAI SSE stream"),
            (b'data: [DONE]\n\n', "Incomplete OpenAI SSE stream"),
            (b'data: {"error":{"message":"do not disclose secrets"}}\n\n'
             b'data: [DONE]\n\n', "Streaming endpoint returned an error event"),
        ]
        for payload, message in fixtures:
            with self.subTest(message=message), patch.object(
                smoke, "urlopen", return_value=io.BytesIO(payload)
            ):
                with self.assertRaisesRegex(RuntimeError, message):
                    smoke.sse_request("http://127.0.0.1/mock", "unit-test-only",
                                      "glm-5.3-flash", 3)

    def test_sse_accepts_fragmented_tool_call_events_without_rewriting(self):
        stream = (
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":'
            b'{"arguments":"{\\"message\\""}}]}}]}\n\n'
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":'
            b'{"arguments":":\\"hello\\"}"}}]}}]}\n\n'
            b'data: [DONE]\n\n'
        )
        with patch.object(smoke, "urlopen", return_value=io.BytesIO(stream)):
            self.assertEqual(
                smoke.sse_request("http://127.0.0.1/mock", "unit-test-only",
                                  "glm-5.3-flash", 3),
                2,
            )

    def test_first_sse_chunk_is_available_before_done_over_loopback(self):
        """HTTP response is intentionally incomplete when the first event arrives."""
        sent_first = threading.Event()
        release_done = threading.Event()
        sent_done = threading.Event()

        class TwoPhaseHandler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_POST(self):
                if self.headers.get("Authorization") != "Bearer unit-test-only":
                    self.send_error(401)
                    return
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                first = b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
                end = b'data: [DONE]\n\n'
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(first) + len(end)))
                self.end_headers()
                self.wfile.write(first)
                self.wfile.flush()
                sent_first.set()
                if release_done.wait(timeout=8):
                    self.wfile.write(end)
                    self.wfile.flush()
                    sent_done.set()

        server = ThreadingHTTPServer(("127.0.0.1", 0), TwoPhaseHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            req = Request(
                "http://127.0.0.1:" + str(server.server_port) + "/v1/chat/completions",
                data=b'{"stream":true}',
                headers={"Authorization": "Bearer unit-test-only",
                         "Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=4) as response:
                self.assertTrue(sent_first.wait(timeout=2))
                chunks = smoke.iter_sse_data(response)
                self.assertEqual(json.loads(next(chunks))["choices"][0]
                                 ["delta"]["content"], "first")
                self.assertFalse(sent_done.is_set(), "the body was buffered until DONE")
                release_done.set()
                self.assertEqual(next(chunks), "[DONE]")
                self.assertTrue(sent_done.wait(timeout=2))
        finally:
            release_done.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
