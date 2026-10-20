"""Hermetic test of tools/smoke_endpoint.py; uses only loopback HTTP."""
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import unittest

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


if __name__ == "__main__":
    unittest.main()
