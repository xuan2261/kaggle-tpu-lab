# Contributing

Thanks for wanting to help. A few notes so your time is well spent.

- **Use a pull request for proposed changes.** GitHub Issues are currently disabled
  in this fork. For a substantial idea, open a **Draft PR** describing the purpose,
  scope and acceptance evidence before investing in implementation. TPU
  performance claims inherited from upstream are not independently reproduced
  acceptance results for this integration.
- **Small fixes** are welcome as direct PRs: a typo, a broken link, a wrong number with the
  measurement behind it.
- **New recipes** need a model-specific README, kernel, reproducible notebook
  provenance and clearly attributed performance evidence. Propose the model in
  a Draft PR first. Do not label an unrun TPU benchmark or browser mock as live.
- **What will not be merged:** changing a recipe's default model or weights to a variant
  (abliterated, quantized, a third-party mirror), ports to GPUs or other platforms, and large
  rewrites without prior design review. Forks may maintain other variants.
- **Bug reports:** include the model, source commit, expected/observed behavior
  and a **redacted** log excerpt only. Never attach raw notebook output, API
  keys, tunnel URLs paired with keys, private session files, or other credentials.
  If a real TPU was permitted and used, report its device count separately
  (the expected v5e-8 count is eight); a mock CPU device count is not TPU evidence.
- **Validation:** use the existing [integration CI workflow](.github/workflows/integration.yml)
  and model-specific tests as executable sources of truth. The current GitHub
  branch protection determines merge checks. Green CI is **not** approval to
  launch a TPU, use billable cloud infrastructure or publish a signed release.
  Real TPU acceptance is [deferred](docs/LIVE_SMOKE_TEST.md#todo-deferred-tpu-acceptance-not-a-test-pass).
- **Linux CI runner images:** integration, browser-mock and Model Proxy jobs pin
  explicit Ubuntu versions instead of the moving `ubuntu-latest` label. Compare
  both images in CI before changing a pin, and preserve existing check names.
  Do not dispatch the write-capable [source-sync workflow](.github/workflows/source-sync.yml)
  merely to test a runner; use non-writing checks.
- **Cloudflare Tunnel binary:** Qwen and GLM kernels and their standalone notebooks
  must retain the same pinned `cloudflared` release/digest/size. See the
  [binary integrity and update procedure](docs/CLOUDFLARED_INTEGRITY.md).
  Integrity tests are offline, not evidence that a public tunnel or SSE is working.
