#!/usr/bin/env python3
"""Local-only Kaggle Benchmarks Model Proxy adapter.

Uses Kaggle's existing OpenAI and Anthropic endpoints. No account creation,
auto-authentication, token rotation, TPU provisioning, or provider fallback.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_BODY_BYTES = 2 * 1024 * 1024
DEFAULT_ENV_FILE = Path.home() / ".kaggle" / "model-proxy.env"
ROUTES = {
    "/v1/chat/completions": ("/openapi/v1/chat/completions", "openai"),
    "/v1/responses": ("/openapi/v1/responses", "openai"),
    "/v1/messages": ("/anthropic/v1/messages", "anthropic"),
}


class ConfigError(ValueError):
    """Unsafe or missing local credentials configuration."""


@dataclass(frozen=True)
class ProxyConfig:
    origin: str
    api_key: str
    expiry: datetime
    models: tuple[str, ...]

    def expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expiry


def _model_list(raw: str) -> tuple[str, ...]:
    models = tuple(dict.fromkeys(m.strip() for m in raw.split(",") if m.strip()))
    if not models or any(
        "/" not in m or len(m) > 160 or not re.fullmatch(r"[A-Za-z0-9@._+/-]+", m)
        for m in models
    ):
        raise ConfigError("Missing or invalid LLMS_AVAILABLE; run Kaggle benchmarks init")
    return models


def _kaggle_origin(url: str) -> str:
    parts = urlsplit(url.strip().rstrip("/"))
    hostname = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError as exc:
        raise ConfigError("Invalid MODEL_PROXY_URL port") from exc
    if (
        parts.scheme != "https"
        or not hostname
        or not (
            hostname in ("kaggle.com", "kaggle.net")
            or hostname.endswith((".kaggle.com", ".kaggle.net"))
        )
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or port not in (None, 443)
    ):
        raise ConfigError("MODEL_PROXY_URL must be a Kaggle-owned HTTPS endpoint")
    path = parts.path.rstrip("/")
    for suffix in ("/openapi/v1", "/anthropic/v1", "/openapi", "/anthropic", "/genai"):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            break
    if ".." in path or "//" in path or not re.fullmatch(r"[/A-Za-z0-9._-]*", path):
        raise ConfigError("Unsupported MODEL_PROXY_URL path")
    return "https://" + hostname + path


def load_config(path: Path) -> ProxyConfig:
    """Read only four Kaggle CLI fields. Last assignment wins (CLI appends)."""
    try:
        if path.is_symlink():
            raise ConfigError("Credentials file must not be a symlink")
        if os.name == "nt":
            # A checkout under C:\Work can inherit broad Users/Authenticated
            # Users ACLs. Never accept credentials outside the user profile.
            if not path.resolve(strict=True).is_relative_to(Path.home().resolve()):
                raise ConfigError("On Windows, store Kaggle credentials inside your user profile")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        fd = os.open(path, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
                raise ConfigError("Credentials must be a small regular file")
            if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
                raise ConfigError("Restrict credentials permissions first: chmod 600")
            with os.fdopen(fd, "r", encoding="utf-8-sig") as stream:
                fd = -1
                contents = stream.read(65537)
            if len(contents) > 65536:
                raise ConfigError("Credentials file exceeds size limit")
        finally:
            if fd >= 0:
                os.close(fd)
    except (OSError, UnicodeError) as exc:
        raise ConfigError("Cannot read credentials file; run Kaggle benchmarks init") from exc
    values = {}
    for line in contents.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in ("MODEL_PROXY_URL", "MODEL_PROXY_API_KEY",
                        "MODEL_PROXY_EXPIRY_TIME", "LLMS_AVAILABLE"):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[name] = value
    if any(not values.get(k) for k in
           ("MODEL_PROXY_URL", "MODEL_PROXY_API_KEY",
            "MODEL_PROXY_EXPIRY_TIME", "LLMS_AVAILABLE")):
        raise ConfigError("Required Model Proxy fields absent; run Kaggle benchmarks init")
    try:
        expiry = datetime.fromisoformat(
            values["MODEL_PROXY_EXPIRY_TIME"].replace("Z", "+00:00")
        )
        if expiry.tzinfo is None:
            raise ValueError("No timezone")
        expiry = expiry.astimezone(timezone.utc)
    except ValueError as exc:
        raise ConfigError("Invalid MODEL_PROXY_EXPIRY_TIME") from exc
    return ProxyConfig(
        _kaggle_origin(values["MODEL_PROXY_URL"]),
        values["MODEL_PROXY_API_KEY"], expiry, _model_list(values["LLMS_AVAILABLE"])
    )


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LocalGateway(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, load, gateway_key, max_requests=20,
                 max_output_tokens=1024, timeout=90, opener=None):
        if address[0] != "127.0.0.1":
            raise ConfigError("Local gateway must bind to 127.0.0.1 only")
        if len(gateway_key) < 24:
            raise ConfigError("Set KAGGLE_GATEWAY_KEY to an independent random key (24+ chars)")
        if not 1 <= max_requests <= 1000 or not 1 <= max_output_tokens <= 32768:
            raise ConfigError("Invalid per-process request/output cap")
        self.load_config = load
        self.gateway_key = gateway_key
        self.max_requests = max_requests
        self.max_output_tokens = max_output_tokens
        self.timeout_upstream = timeout
        self.requests_made = 0
        self.request_lock = threading.Lock()
        self.opener = opener or build_opener(ProxyHandler({}), _NoRedirect())
        super().__init__(address, LocalHandler)


class LocalHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: LocalGateway

    def setup(self):
        super().setup()
        # Bound idle client connections; no unbounded localhost slowloris.
        self.connection.settimeout(30)

    def log_message(self, format, *args):
        # Never log paths, request bodies or credentials.
        return

    def _send(self, status: int, value: dict) -> None:
        data = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.close_connection = True
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, code: int, message: str) -> None:
        self._send(code, {"error": {"type": "gateway_error", "message": message}})

    def _authorized(self) -> bool:
        if self.headers.get("Origin"):
            self._error(403, "Browser-origin requests are not supported")
            return False
        header = self.headers.get("Authorization", "")
        bearer = header[7:] if header.startswith("Bearer ") else ""
        provided = bearer or self.headers.get("x-api-key", "")
        if not hmac.compare_digest(provided, self.server.gateway_key):
            self._error(401, "Invalid local gateway credentials")
            return False
        return True

    def _config(self) -> ProxyConfig | None:
        try:
            config = self.server.load_config()
            if config.expired():
                raise ConfigError("Kaggle proxy token expired; refresh it using Kaggle CLI")
            return config
        except ConfigError as exc:
            self._error(503, str(exc))
            return None

    def do_GET(self):
        if not self._authorized():
            return
        if self.path == "/health":
            self._send(200, {"status": "ok", "mode": "local-development-only"})
            return
        if self.path == "/v1/models":
            config = self._config()
            if config is None:
                return
            self._send(200, {"object": "list",
                             "data": [{"id": model, "object": "model", "owned_by": "kaggle"}
                                      for model in config.models]})
            return
        self._error(404, "Unsupported route")

    def do_POST(self):
        if not self._authorized():
            return
        route = ROUTES.get(self.path)
        if route is None:
            self._error(404, "Unsupported route")
            return
        if self.headers.get("Content-Encoding"):
            self._error(415, "Compressed requests are not supported")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._error(411, "Content-Length required")
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._error(413, "Request body must be between 1 byte and 2 MiB")
            return
        raw = self.rfile.read(length)
        try:
            request = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            self._error(400, "Malformed JSON")
            return
        if not isinstance(request, dict) or not isinstance(request.get("model"), str):
            self._error(400, "A model identifier is required")
            return
        config = self._config()
        if config is None:
            return
        if request["model"] not in config.models:
            self._error(403, "This model is not in your Kaggle local allowlist")
            return
        token_field = {
            "/v1/chat/completions": ("max_tokens", "max_completion_tokens"),
            "/v1/responses": ("max_output_tokens",),
            "/v1/messages": ("max_tokens",),
        }[self.path]
        present = [k for k in token_field if k in request]
        if not present:
            fallback = ("max_completion_tokens"
                        if self.path == "/v1/chat/completions"
                        and request["model"].startswith("openai/")
                        else token_field[0])
            request[fallback] = min(256, self.server.max_output_tokens)
        for field in present:
            value = request[field]
            if type(value) is not int or value < 1 or value > self.server.max_output_tokens:
                self._error(422, "Output token count exceeds local development cap")
                return
        if self.path == "/v1/chat/completions":
            for field in ("n", "best_of"):
                if field in request and (type(request[field]) is not int or request[field] != 1):
                    self._error(422, "Local development supports exactly one completion choice")
                    return
        if self.path == "/v1/messages":
            version = self.headers.get("anthropic-version") or "2023-06-01"
            beta = self.headers.get("anthropic-beta")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", version):
                self._error(422, "Invalid anthropic-version header")
                return
            if beta is not None and not re.fullmatch(r"[A-Za-z0-9._, -]{1,512}", beta):
                self._error(422, "Invalid anthropic-beta header")
                return
        with self.server.request_lock:
            if self.server.requests_made >= self.server.max_requests:
                self._error(429, "Local request cap reached; restart only after quota review")
                return
            self.server.requests_made += 1
        target, protocol = route
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if protocol == "anthropic":
            headers["x-api-key"] = config.api_key
            headers["anthropic-version"] = version
            if beta:
                headers["anthropic-beta"] = beta
        else:
            headers["Authorization"] = "Bearer " + config.api_key
        upstream = Request(config.origin + target, json.dumps(request).encode("utf-8"),
                           headers=headers, method="POST")
        try:
            with self.server.opener.open(upstream, timeout=self.server.timeout_upstream) as response:
                kind = response.headers.get("Content-Type", "application/json")
                if not (kind.startswith("application/json") or kind.startswith("text/event-stream")):
                    self._error(502, "Unexpected upstream content type")
                    return
                self.send_response(response.status)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                try:
                    while True:
                        chunk = response.read1(16384) if hasattr(response, "read1") else response.read(16384)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
                    # Headers already went out; never send a second JSON response.
                    self.close_connection = True
        except HTTPError as exc:
            code = exc.code if 400 <= exc.code <= 599 else 502
            self._error(code, "Kaggle Model Proxy rejected the request (see quota/model permissions)")
        except (URLError, TimeoutError, OSError):
            # Do not surface upstream exception text: it may contain the signed request URL.
            self._error(502, "Cannot reach Kaggle Model Proxy")

    def do_OPTIONS(self):
        self._error(405, "Browser-origin access is disabled")


def command_line(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(DEFAULT_ENV_FILE),
                        help="Kaggle CLI-generated file; never committed to Git")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Validate local credentials without using inference quota")
    sub.add_parser("models", help="Show only locally authorized model IDs")
    sub.add_parser("quota", help="Read account quota using Kaggle CLI; no inference request")
    start = sub.add_parser("serve", help="Start the private local gateway")
    start.add_argument("--port", type=int, default=8766)
    start.add_argument("--max-requests", type=int, default=20)
    start.add_argument("--max-output-tokens", type=int, default=1024)
    args = parser.parse_args(argv)

    if args.command == "quota":
        try:
            result = subprocess.run(["kaggle", "benchmarks", "quota", "--format", "json"],
                                    capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            print("Kaggle CLI not available; install it and run kaggle auth login", file=sys.stderr)
            return 2
        if result.returncode:
            print("Kaggle quota unavailable; check CLI authentication", file=sys.stderr)
            return 2
        try:
            payload = json.loads(result.stdout)
            rows = payload if isinstance(payload, list) else payload.get("rows", payload.get("quotas", []))
            if not isinstance(rows, list) or not rows or any(
                not isinstance(row, dict)
                or not all(k in row for k in ("period", "used", "remaining", "total", "refillAt"))
                for row in rows
            ):
                raise ValueError("Unexpected quota payload")
            for row in rows:
                print("{}: used={} remaining={} total={} refillAt={}".format(
                    row["period"], row["used"], row["remaining"],
                    row["total"], row["refillAt"]))
            return 0
        except (ValueError, AttributeError):
            print("Quota response format changed; run kaggle benchmarks quota directly", file=sys.stderr)
            return 2

    try:
        config = load_config(args.env_file)
        if config.expired():
            raise ConfigError("Model Proxy token expired; run kaggle benchmarks auth --env-file")
        if args.command == "doctor":
            print("Local Kaggle credential structure: valid")
            print("Allowed local models:", len(config.models))
            print("Token expires (UTC):", config.expiry.isoformat())
            print("No model requests sent; live permission and quota not verified")
            return 0
        if args.command == "models":
            print("\n".join(config.models))
            return 0
        key = os.environ.get("KAGGLE_GATEWAY_KEY", "")
        if key == config.api_key:
            raise ConfigError("Local gateway key must differ from Kaggle token")
        with LocalGateway(("127.0.0.1", args.port),
                          lambda: load_config(args.env_file), key,
                          args.max_requests, args.max_output_tokens) as gateway:
            print("Private gateway listening at http://127.0.0.1:{}/v1".format(args.port))
            print("No inference request sent on startup; endpoint is localhost-only")
            gateway.serve_forever()
        return 0
    except (ConfigError, OSError) as exc:
        # Error strings originate from known static checks, not credentials.
        print("Cannot start: " + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(command_line())
