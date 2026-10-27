# Offline, read-only TPU resource preflight

The Windows Companion exposes a sanitized `SessionSnapshot`, but some fields
combine launcher events with settings fallbacks. It does not contain an
independent measurement of TPU device count, accelerator HBM usage, or remote
disk availability. Therefore no hardware-fit or inference-ready claim can be
established solely from the chosen model or the UI snapshot.

`tools/resource_preflight.py` produces a bounded, redacted schema-v1 report
that distinguishes configured targets, user-supplied snapshot fields and
missing hardware evidence. It supports **only** Qwen3.8-27B and GLM-5.3-Flash.
It never starts, stops, queries or allocates Kaggle TPU or GCP resources, and
does not import JAX, call Kaggle CLI, access cloudflared tunnels, or send
inference requests.

## Use

With no snapshot, create an offline capability/unknown-evidence template:

```powershell
python tools/resource_preflight.py --profile qwen38-27b
```

You can optionally pass a JSON object representing an **existing** Companion
`SessionSnapshot` with camelCase Rust serialization when one is available:

```powershell
python tools/resource_preflight.py --profile glm53-flash --snapshot-file .\private-snapshot.json
```

No session file is discovered automatically. The input is unverified,
size-limited to 256 KiB, and only selected fields are projected. Raw endpoint
URLs, API keys, topic identifiers, kernel owners, arbitrary free text, activity
logs, and input file paths are **never** included in the JSON report. Keep
private session files out of Git and shared logs.

## Meaning

- `target_device_count=8` denotes the v5e-8 **target profile**, not an
  observed allocation.
- `configured.*.source=companion_effective_or_settings_fallback` means the
  original snapshot could have used a settings fallback. It is not a
  measurement or live device configuration proof.
- `session.endpoint_live_claim` and phase are copied only as restricted
  values from unverified user input; neither certifies actual remote readiness.
- `observed.accelerator` and `observed.disk` remain `unobserved` with null
  device count, HBM and disk values; no fake or early JAX device probe is used.
- `checks.inference_requests_sent=0` and `mutating_actions=0` describe
  this tool. OpenAI SSE, Anthropic, tools and authenticated models remain
  `not_checked`; readiness always stays `inconclusive`.

These are pure offline unit tests in the required `python-contracts` job.
They cannot satisfy the [live TPU acceptance checklist](LIVE_SMOKE_TEST.md).
