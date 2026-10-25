# Source integration provenance — 2026-10-20 baseline

**Historical integration record.** For current Windows Companion acceptance,
see [installed 0.4.6 QA](WINDOWS_COMPANION_0_4_6_QA_20261025.md); for current
CI/merge rules and remaining TPU qualifications, see the
[root README](../README.md#testing-and-release-status) and
[TPU acceptance TODO](LIVE_SMOKE_TEST.md#todo-deferred-tpu-acceptance-not-a-test-pass).

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

## Verification ownership

The [Integration checks workflow](../.github/workflows/integration.yml) owns
the executable build/test commands and its PR/push triggers. GitHub's
`main` branch-protection settings own the required-status policy; check the
actual [Actions run](https://github.com/xuan2261/kaggle-tpu-lab/actions)
for the precise revision instead of relying on a historical PASS summary.
These jobs use CPU and browser mocks, not a real Kaggle TPU or GCP VM.

## Release hold

The merge preserves source history but is **not** an approved binary release.
Genuine Kaggle TPU tests for Qwen/GLM, SSE through supported transports and
tool-use behavior are [explicitly deferred](LIVE_SMOKE_TEST.md#todo-deferred-tpu-acceptance-not-a-test-pass).
The integration baseline did not provision GCP. Later installed Windows
Companion QA is separately documented; it cannot substitute for TPU inference.

The draft model used by the GLM speculative decoder has third-party noncommercial research-use restrictions; review downstream licenses before commercial deployment.


## Automated source synchronization (review-gated)

The synchronization workflow now exists on the default `main` branch.
When enabled and permitted by GitHub Actions settings, it checks both
ARahim3 (upstream) and Haz4rdovisk (companion) once each Monday at
03:17 UTC. It creates draft pull requests with Git merge ancestry, but never
merges into main or executes any Kaggle/GCP workload. Conflicts fail closed and
require a manual fix. Existing open sync PRs prevent duplication.

Being present on `main` does not prove the scheduled workflow has run
successfully. Check the GitHub Actions run history and generated draft PRs.
GitHub's repository setting
"Allow GitHub Actions to create and approve pull requests" might need
enabling by the owner. Pull requests created with GITHUB_TOKEN can trigger
approval-required checks; review them and approve CI before merging.
See GitHub's Actions token and scheduled-workflow documentation.

The optional live endpoint smoke tool and its loopback-only regression tests
are documented in [the live smoke guide](LIVE_SMOKE_TEST.md). It cannot prove real TPU health
until run against a privately held live endpoint.
