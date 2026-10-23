# Kaggle Benchmarks Model Proxy — local development gateway

This is an **optional, single-user development adapter**, separate from the
self-hosted Qwen/GLM Kaggle TPU engine and Windows Companion. It uses Kaggle's
**existing** OpenAI and Anthropic API endpoints, without model download,
provider impersonation, paid GCP, or any TPU session lifecycle commands.

**Scope:** Only for benchmark/local development use authorized by your Kaggle
account and the current Kaggle terms. Do not expose this to the Internet,
resell access, distribute a Kaggle key, or use it to bypass quota/model limits.

## Official API sources and limitations

Kaggle documents these upstream paths in its benchmark starter template:

| Gateway local route | Kaggle upstream | HTTP method |
| --- | --- | --- |
| /v1/chat/completions | /openapi/v1/chat/completions | POST |
| /v1/responses | /openapi/v1/responses | POST |
| /v1/messages | /anthropic/v1/messages | POST |
| /v1/models | Local filtered catalog from LLMS_AVAILABLE | GET |
| /health | Local process check | GET |

- CLI instructions: [Kaggle/kaggle-cli/docs/benchmarks.md](https://github.com/Kaggle/kaggle-cli/blob/main/docs/benchmarks.md).
- Protocol samples: [Kaggle Benchmark Harbor Starter](https://github.com/Kaggle/kaggle-benchmark-harbor-starter-template/blob/main/README.md).
- **Important:** the local proxy token is restricted to the curated
  LLMS_AVAILABLE list produced by Kaggle Benchmarks init. The full catalog
  returned by kaggle benchmarks tasks models is **not** your local allowlist.
- Daily/Monthly AI Models quota is measured in USD; Kaggle GPU/TPU quota is a
  separate hourly allowance. Neither quota represents cash credited to you.

The gateway passes through the API formats; it does not claim complete parity
with the official OpenAI or Anthropic services, and it does not fabricate
streaming or tool-call responses.

## 1. Acquire credentials yourself (Windows PowerShell)

Install the Kaggle CLI and sign in using your own Kaggle account:

~~~powershell
python -m pip install --upgrade kaggle
kaggle auth login
kaggle benchmarks quota --format json
~~~

Keep the Kaggle-generated credentials **outside the repository**. A project
checkout under `C:\Work` may inherit read or modify permissions for other
Windows accounts. The adapter defaults to your private user-profile path
`~/.kaggle/model-proxy.env`. Initialize from a temporary directory to avoid
leaving generated example tasks in the repository:

~~~powershell
$privateDir = Join-Path $env:USERPROFILE ".kaggle"
New-Item -ItemType Directory -Force -Path $privateDir | Out-Null
$privateFile = Join-Path $privateDir "model-proxy.env"
Push-Location $env:TEMP
try {
    kaggle benchmarks init -y --env-file $privateFile
} finally {
    Pop-Location
}
~~~

The CLI may also create a sample benchmark and reference document in the
temporary directory. The model proxy key and expiration are stored at
`$privateFile` outside Git. Inspect its Windows ACL using
`icacls $privateFile`; do not use it if other ordinary accounts have access.
The adapter requires the credential path to remain under your user profile
on Windows. This reduces risk but is **not** an independent audit of the ACL.
NEVER commit the credential file, post its contents or enter either key in chat.

On Linux/macOS, also restrict file permissions:

~~~bash
chmod 600 ~/.kaggle/model-proxy.env
~~~

Check the configuration without making a model request:

~~~powershell
# Use the SAME venv Python where you installed and authenticated Kaggle CLI.
$py = Join-Path (Get-Location) ".venv\Scripts\python.exe"
& $py tools/kaggle_model_proxy.py doctor
& $py tools/kaggle_model_proxy.py models
& $py tools/kaggle_model_proxy.py quota
~~~

The doctor checks basic credential shape, expected Kaggle HTTPS origin,
expiration and local model allowlist. It does not contact or authenticate with
the inference endpoint. The quota command explicitly calls the Kaggle CLI,
**not** a model; if the CLI's JSON schema changes, run Kaggle's quota command
directly instead. The quota subprocess runs `python -m kaggle` using the
same interpreter as the adapter; the global Windows `PATH` need not contain
the `kaggle` executable.

## 2. Start localhost gateway (optional)

**Direct access is simpler** for one-off benchmark requests: point an OpenAI
client to MODEL_PROXY_URL/openapi/v1 or an Anthropic client to
MODEL_PROXY_URL/anthropic, using MODEL_PROXY_API_KEY. The local gateway is only
for developers who want a fixed localhost base URL, separate client key and
request cap while their Kaggle credentials stay server-side.

Generate a **different local gateway key** in PowerShell. Keep the variable
within your private shell session:

~~~powershell
$env:KAGGLE_GATEWAY_KEY = python -c "import secrets; print(secrets.token_urlsafe(32))"
python tools/kaggle_model_proxy.py serve --port 8766 --max-requests 20 --max-output-tokens 1024
~~~

The command stays running until interrupted (Ctrl+C). Use another terminal or
your preferred private process manager for the client, supplying the **same
local gateway key**, never the Kaggle Model Proxy key.

The server binds **only to 127.0.0.1**, requires a 24+-character independent
KAGGLE_GATEWAY_KEY, rejects browser origins, does not enable CORS and does not
log credentials or request bodies. It refuses remote models not present in the
Kaggle-generated allowlist, refuses expired Kaggle credentials, and rejects
large requests or output-token budgets above the configured local cap.
It forwards the sanitized `anthropic-beta` negotiation header for approved
Anthropic requests and restricts multi-choice OpenAI generation to `n=1`.

The default request cap is 20 accepted requests per process. **This is NOT
a USD cost limit.** Read Kaggle Benchmarks quota before and during any
authorized benchmark testing. There is no automatic token refresh or
fallback to another provider.

## 3. Connect OpenAI or Anthropic clients (authorized benchmarks only)

For the OpenAI SDK, use the **local** credential and base URL:

~~~python
import os
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8766/v1",
    api_key=os.environ["KAGGLE_GATEWAY_KEY"],
)
# Free of inference usage: the catalog is produced from LLMS_AVAILABLE locally.
print([entry.id for entry in client.models.list().data])
# An actual .chat.completions.create(...) call spends Kaggle AI Models quota.
~~~

For the Anthropic SDK:

~~~python
import os
from anthropic import Anthropic

client = Anthropic(
    base_url="http://127.0.0.1:8766",
    api_key=os.environ["KAGGLE_GATEWAY_KEY"],
)
# Client expects /v1/messages. Only choose a model from your local allowlist.
~~~

Supported provider/model IDs must match the Kaggle token's local allowlist.
The adapter **does not silently map bare model names** or allow otherwise
unauthorized models. If the original client does not support the correct
endpoint, choose a protocol-compatible client configuration; do not assume
Claude Code/Codex/OpenCode implements identical streaming and tools.

When Kaggle's short-lived key expires, stop new requests and explicitly renew
it in your private terminal:

~~~powershell
$privateFile = Join-Path (Join-Path $env:USERPROFILE ".kaggle") "model-proxy.env"
kaggle benchmarks auth -y --env-file $privateFile
python tools/kaggle_model_proxy.py doctor
~~~

The server reads the local file again for each request, so it can pick up
a manually refreshed key. If your allowlist is missing, use
kaggle benchmarks init instead; auth alone need not create LLMS_AVAILABLE.

## Expected local errors

| HTTP status | Meaning |
| --- | --- |
| 401 | Wrong/missing independent local gateway key |
| 403 | Browser origin denied or model not in LLMS_AVAILABLE |
| 413 | Request body too large |
| 422 | Output budget, multi-choice or Anthropic negotiation header is invalid |
| 429 | Local request count reached |
| 503 | Missing/unsafe file or expired Kaggle proxy key |
| 502 | Network error or unexpected upstream response |

Upstream errors are reported without forwarding remote error bodies, as those
may contain credentials or sensitive prompt data. No provider fallback, retry,
quota reset manipulation, permanent credential caching or public bind exists.

## Verification status

The hermetic test suite runs only on 127.0.0.1 mock upstream servers:

~~~bash
python -m unittest discover -s tests -p 'test_kaggle_model_proxy.py' -v
~~~

It covers both API paths, streaming pass-through, headers, token and model
guards, credential file checks, output caps and refusal after a request cap.

**Not yet verified:** real Kaggle login, available models and spend quota on
the account, live tool-use/stream parity, Kaggle terms for a given use case, or
behavior of external coding agents. Live requests must be initiated by you
with private credentials, and quota consumption must be monitored directly.
