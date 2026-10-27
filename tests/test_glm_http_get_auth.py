"""Hermetic GET-route contracts for the self-hosted GLM HTTP handler.

Only the H class AST is evaluated, never the executable TPU kernel module.
The HTTP server binds to an ephemeral 127.0.0.1 port and handles GET only.
This is not an inference, Cloudflare or Kaggle hardware acceptance test.
"""

import ast
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT / "glm53-flash/kernel/serve_glm53.py"
NOTEBOOK = ROOT / "glm53-flash/notebook/glm53-tpu-serve.ipynb"
TOKEN = "unit-test-glm-http-get-key"
MODEL = "glm-5.3-flash"


def handler_from_source():
    source = KERNEL.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(KERNEL))
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "H"]
    if len(classes) != 1:
        raise AssertionError("Expected exactly one GLM HTTP handler class")
    isolated = ast.fix_missing_locations(ast.Module(body=classes, type_ignores=[]))
    namespace = {
        "BaseHTTPRequestHandler": BaseHTTPRequestHandler,
        "API_KEY": TOKEN,
        "MODEL": MODEL,
        "json": json,
        "secrets": secrets,
    }
    exec(compile(isolated, str(KERNEL), "exec"), namespace)
    return namespace["H"], classes[0], source


class GlmGetAuthContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler, cls.handler_node, cls.source = handler_from_source()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def get(self, path, headers=None):
        req = Request(
            f"http://127.0.0.1:{self.server.server_port}{path}",
            headers=headers or {},
            method="GET",
        )
        try:
            with urlopen(req, timeout=3) as resp:
                return resp.status, json.load(resp)
        except HTTPError as err:
            with err:
                return err.code, json.load(err)

    def test_unauthenticated_health_is_exact_and_minimal(self):
        status, payload = self.get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ok"})
        req = Request(f"http://127.0.0.1:{self.server.server_port}/health")
        with urlopen(req, timeout=3) as response:
            self.assertEqual(response.headers.get("Server"), "KaggleTPU")
            self.assertNotIn("Python/", response.headers.get("Server", ""))
        for path in ("/healthz", "/health/metrics", "/health?debug=1"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 404)

    def test_models_requires_existing_bearer_or_x_api_key(self):
        for headers in ({}, {"Authorization": "Bearer wrong"},
                        {"x-api-key": "wrong"}, {"Authorization": "Bearer é"}):
            with self.subTest(headers=list(headers)):
                status, data = self.get("/v1/models", headers)
                self.assertEqual(status, 401)
                self.assertEqual(data["error"]["type"], "authentication_error")
                self.assertNotIn(MODEL, json.dumps(data))

        for headers in ({"Authorization": f"Bearer {TOKEN}"},
                        {"x-api-key": TOKEN}):
            with self.subTest(headers=list(headers)):
                status, data = self.get("/v1/models", headers)
                self.assertEqual(status, 200)
                self.assertEqual([item["id"] for item in data["data"]], [MODEL])

    def test_missing_server_key_fails_closed_even_for_matching_empty_header(self):
        # The runtime normally generates a key, but its loss must not turn
        # protected GET/POST routes into public endpoints.
        h = object.__new__(self.server.RequestHandlerClass)
        h.headers = {"Authorization": "", "x-api-key": ""}
        namespace = self.server.RequestHandlerClass._auth.__globals__
        original = namespace["API_KEY"]
        try:
            namespace["API_KEY"] = ""
            self.assertFalse(h._auth())
        finally:
            namespace["API_KEY"] = original

    def test_prefix_routes_are_not_accepted_even_with_valid_token(self):
        for path in ("/v1/models-extra", "/v1/models/anything", "/v1/models?debug=1"):
            with self.subTest(path=path):
                self.assertEqual(
                    self.get(path, {"Authorization": f"Bearer {TOKEN}"})[0], 404,
                )

    def test_post_auth_stays_before_request_body_and_tunnel_probe_uses_health(self):
        methods = {n.name: n for n in self.handler_node.body
                   if isinstance(n, ast.FunctionDef)}
        post = methods["do_POST"]
        self.assertIsInstance(post.body[0], ast.If)
        self.assertEqual(
            ast.unparse(post.body[0].test), "not self._auth()",
        )
        self.assertIn('urllib.request.urlopen(f"{u}/health", timeout=10)', self.source)

    def test_notebook_embedded_handler_matches_standalone_kernel(self):
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        magic = "%%writefile serve_glm53.py\n"
        cells = ["".join(c.get("source", [])) for c in notebook["cells"]
                 if "".join(c.get("source", [])).startswith(magic)]
        self.assertEqual(cells, [magic + self.source])


if __name__ == "__main__":
    unittest.main()
