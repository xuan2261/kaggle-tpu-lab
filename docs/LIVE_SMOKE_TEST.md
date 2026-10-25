# Live Kaggle TPU smoke test

## TODO: deferred TPU acceptance (not a test PASS)

The project owner deferred **all live Kaggle TPU testing** for the current
non-TPU engineering pass. Do not launch a TPU kernel, submit a notebook to
obtain a TPU, or consume TPU time merely to clear this checklist. This is a
deferred release qualification, **not** evidence that Qwen/GLM work on TPU.

- [ ] Complete Kaggle's official account/Persona verification when the owner
      chooses to resume TPU testing; confirm that the notebook UI actually
      allows TPU v5e-8, not just that hourly quota is available.
- [ ] Qwen3.8-27B: confirm required datasets and real 8-device TPU allocation;
      reach engine READY, then run bounded authenticated chat and verify the
      supported streaming/tool behavior through the **actual** network path.
- [ ] GLM-5.3-Flash: separately confirm permitted weights/datasets and an
      actual TPU allocation; reach READY and validate a bounded request and
      supported protocol behavior.
- [ ] Exercise the installed Windows Companion's start/status/reconnect/stop
      workflow only with a test-owned kernel, verify its cleanup, and record
      TPU-hour usage before/after. Never stop unrelated existing kernels.
- [ ] Attach redacted, source-pinned evidence before considering these items
      passed. Hosted Kaggle **Benchmarks Model Proxy** SSE/tool-call results
      are separate and cannot satisfy either self-hosted TPU item.

No GCP deployment, CLI submission to evade the identity check, or unsigned
production release is authorized by this TODO. Other non-TPU development and
testing may proceed independently.

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
