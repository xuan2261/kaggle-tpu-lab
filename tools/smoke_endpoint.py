#!/usr/bin/env python3
"""Read-only API smoke test against an EXISTING live endpoint.

Does NOT start, stop or provision Kaggle TPU. Never prints the API key.
"""
import argparse
from getpass import getpass
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def normalize_base_url(value):
    value = value.strip().rstrip("/")
    url = urlsplit(value)
    if url.username or url.password or url.query or url.fragment:
        raise ValueError("Base URL must not contain credentials, query or fragment")
    local = url.hostname in ("localhost", "127.0.0.1", "::1")
    if url.scheme != "https" and not (url.scheme == "http" and local):
        raise ValueError("Use HTTPS remotely; HTTP is only permitted on localhost")
    if not url.hostname or url.path not in ("", "/", "/v1"):
        raise ValueError("Base URL must be the tunnel root or end in /v1")
    return value if value.endswith("/v1") else value + "/v1"


def json_request(url, token, method="GET", body=None, timeout=60, extra_headers=None):
    headers = {"Authorization": "Bearer " + token}
    if body is not None:
        headers["Content-Type"] = "application/json"
    headers.update(extra_headers or {})
    request = Request(url,
                      data=json.dumps(body).encode("utf-8") if body is not None else None,
                      headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as err:
        raise RuntimeError("HTTP status " + str(err.code)) from None
    except (URLError, TimeoutError) as err:
        raise RuntimeError("Network error or timeout: " + type(err).__name__) from None


def iter_sse_data(response, deadline=None):
    """Yield one SSE data payload as each complete HTTP response line arrives.

    This deliberately does not buffer the entire body. It does not by itself
    qualify a remote tunnel for incremental SSE transport.
    """
    for chunk in response:
        # Check the wall-clock limit even for SSE comments/blank/non-data
        # lines, which a remote peer could otherwise send indefinitely.
        if deadline is not None and time.monotonic() > deadline:
            raise RuntimeError("Streaming exceeded the time limit")
        line = chunk.decode("utf-8", "replace").strip()
        if line.startswith("data:"):
            yield line[5:].strip()


def sse_request(url, token, model, timeout):
    body = {"model": model, "messages": [{"role": "user", "content": "Say OK."}],
            "max_tokens": 40, "stream": True}
    request = Request(url, data=json.dumps(body).encode("utf-8"),
                      headers={"Authorization": "Bearer " + token,
                               "Content-Type": "application/json",
                               "Accept": "text/event-stream"}, method="POST")
    events, ended = 0, False
    start = time.monotonic()
    try:
        with urlopen(request, timeout=timeout) as response:
            for data in iter_sse_data(response, start + timeout):
                if time.monotonic() - start > timeout:
                    raise RuntimeError("Streaming exceeded the time limit")
                if data == "[DONE]":
                    ended = True
                    break
                event = json.loads(data)
                if event.get("error"):
                    raise RuntimeError("Streaming endpoint returned an error event")
                if event.get("choices"):
                    events += 1
    except HTTPError as err:
        raise RuntimeError("Streaming HTTP status " + str(err.code)) from None
    except (URLError, TimeoutError) as err:
        raise RuntimeError("Streaming network error: " + type(err).__name__) from None
    if not ended or events == 0:
        raise RuntimeError("Incomplete OpenAI SSE stream")
    return events


def run_smoke(base_url, token, model, timeout=90, check_tools=True):
    base = normalize_base_url(base_url)
    if not token:
        raise ValueError("API key is empty")
    results = []
    models = json_request(base + "/models", token, timeout=timeout)
    ids = [m.get("id") for m in models.get("data", []) if isinstance(m, dict)]
    if model not in ids:
        raise RuntimeError("Model ID was not found at /v1/models")
    # Some engines expose /v1/models publicly; passing Bearer here does not
    # prove that the server enforces authentication on this read-only route.
    results.append("Model ID advertised (Bearer supplied)")

    chat = {"model": model, "messages": [{"role": "user", "content": "Say OK."}],
            "max_tokens": 40, "stream": False}
    response = json_request(base + "/chat/completions", token, "POST", chat, timeout)
    if not response.get("choices"):
        raise RuntimeError("Chat completions response lacks choices")
    results.append("OpenAI chat")

    sse_request(base + "/chat/completions", token, model, timeout)
    results.append("OpenAI SSE")

    anthropic = json_request(base + "/messages", token, "POST",
                             {"model": model,
                              "messages": [{"role": "user", "content": "Say OK."}],
                              "max_tokens": 40},
                             timeout, {"anthropic-version": "2023-06-01"})
    if not isinstance(anthropic.get("content"), list):
        raise RuntimeError("Anthropic messages response lacks content blocks")
    results.append("Anthropic messages")

    if check_tools:
        req = {
            "model": model,
            "messages": [{"role": "user", "content": "Call echo_safe with message hello."}],
            "max_tokens": 80,
            "tools": [{"type": "function", "function": {
                "name": "echo_safe", "description": "Echo a harmless message",
                "parameters": {"type": "object", "properties": {
                    "message": {"type": "string"}}, "required": ["message"]}}}],
            "tool_choice": "auto",
        }
        tool_response = json_request(base + "/chat/completions", token, "POST", req, timeout)
        if not tool_response.get("choices"):
            raise RuntimeError("Tool-enabled response lacks choices")
        results.append("Tool request accepted (tool selection not guaranteed)")
    return results


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", ""))
    p.add_argument("--model", required=True, choices=["qwen3.8-27b", "glm-5.3-flash"])
    p.add_argument("--timeout", type=int, default=90)
    p.add_argument("--skip-tools", action="store_true")
    args = p.parse_args()
    if not args.base_url:
        p.error("Provide --base-url or the OPENAI_BASE_URL environment variable")
    if not 10 <= args.timeout <= 300:
        p.error("--timeout must be between 10 and 300 seconds")
    token = os.environ.get("OPENAI_API_KEY") or getpass("API key (hidden): ")
    try:
        for check in run_smoke(args.base_url, token, args.model, args.timeout,
                               check_tools=not args.skip_tools):
            print("PASS:", check)
        print("SMOKE SUCCESS (existing endpoint only)")
        return 0
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as err:
        print("SMOKE FAILED:", str(err), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
