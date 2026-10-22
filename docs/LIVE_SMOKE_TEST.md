# Live Kaggle TPU smoke test

This tool never starts or stops a TPU; it sends a few inference requests only to an
already-running endpoint belonging to you. Running it consumes some inference quota.

From Windows PowerShell, after READY:

~~~powershell
python tools/smoke_endpoint.py --base-url https://your-own-tunnel.trycloudflare.com/v1 --model qwen3.8-27b
~~~

The program prompts for the API key with hidden input, unless OPENAI_API_KEY is already
set locally. To test GLM, provide its own tunnel URL and choose glm-5.3-flash.
Never paste API keys, local session files or unredacted notebook output in GitHub issues.

Checks: authenticated models list, OpenAI chat completions, OpenAI SSE streaming,
Anthropic messages and acceptance of a tool-enabled request. A successful tool
request does not guarantee the model actually selected a tool. Use --skip-tools
to omit that optional check. No retries are performed.

**Streaming caveat:** Cloudflare documents that its free, ephemeral
[Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
do not support Server-Sent Events (SSE). A successful localhost/API-mock
streaming test is therefore **not** evidence that a live Quick Tunnel can
stream. Keep streaming compatibility and tool-loop support unverified until
tested through an appropriately supported, authorized transport.

Record separately for Qwen and GLM: pinned commit, TPU device count, dataset
revisions, startup, actual streaming behavior, tool-call selection, and Companion
start/stop/reconnect. Keep the PR in draft on any failed live verification.
Merged source code is not a production release; track any remaining live
verification failure in a separate review or release checklist.
