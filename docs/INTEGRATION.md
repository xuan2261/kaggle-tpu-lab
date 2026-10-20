# Integration status — 2026-10-20

## Sources and provenance

- Inference upstream: [ARahim3/kaggle-tpu-lab](https://github.com/ARahim3/kaggle-tpu-lab), `9a31b8519a80821bcffc5424f6444a9a69bd2711`.
- Desktop companion: [Haz4rdovisk/kaggle-tpu-lab](https://github.com/Haz4rdovisk/kaggle-tpu-lab), `6c0ef490e050c36506be93d985a845b58acd9136`.
- Integration is a true two-parent Git merge preserving both histories. No force-push was used.
- The GLM inference engine and `gcp/` come from newer upstream; the Tauri 2 Windows UI and Qwen companion modifications come from Haz4rdovisk.

## Contract changes

1. GLM defaults to three streams, not four, because upstream's speculative decoder supports three at the maximum 262,144-token context. Existing persisted profiles above three are clamped to three on load.
2. The default GLM serve dataset is `rahim3/glm53-flash-serve-v3`.
3. Qwen/GLM readiness events no longer carry session API keys to the public ntfy service. The launcher reads its key from local state; on POSIX that state file is created with owner-only permissions.
4. Rust diagnostic redaction now handles both `sk-` and `glm-` session keys while preserving the `glm-5.3-flash` model identifier.

## Verification commands

```bash
python -m unittest discover -s tests -v
python -m compileall -q launch.py qwen38-27b/kernel glm53-flash/kernel glm53-flash/engine/glm53
npm ci && npm run build
cargo test --locked --manifest-path src-tauri/Cargo.toml
```

GitHub Actions runs these checks on integration branch pushes and pull requests. Tests do not launch Kaggle kernels or GCP instances.

## Release hold

The merge preserves source history but is **not** an approved binary release. A genuine Kaggle TPU test is still needed to confirm Qwen, GLM, model IDs, notebook/kernel parity, SSE streaming, tool calling, start/stop and reconnect behavior. No cloud TPU/GCP execution has been performed during this integration.

The draft model used by the GLM speculative decoder has third-party noncommercial research-use restrictions; review downstream licenses before commercial deployment.
