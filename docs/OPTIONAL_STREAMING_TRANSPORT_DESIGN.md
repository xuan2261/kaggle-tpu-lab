# Optional stable HTTPS/SSE transport — design only

**Status:** architectural proposal; **not implemented, provisioned, enabled, or
hardware-qualified**. Quick Cloudflare Tunnel remains the existing default.
No API keys, domain ownership, paid infrastructure, real TPU sessions or
Cloudflare account settings are required to read or review this document.

## Problem and evidence boundary

The current Qwen3.8 and GLM-5.3 kernels use ephemeral
`*.trycloudflare.com` Quick Tunnels. Cloudflare explicitly documents that
Quick Tunnels do **not** support Server-Sent Events (SSE); their temporary
hostnames also change across tunnel restarts. A localhost event-stream test
does not prove the public transport can incrementally deliver tokens.

An operator-controlled **named Cloudflare Tunnel** with a stable, owned HTTPS
hostname is a candidate for an **optional API-only** transport. Named tunnels
are not Quick Tunnels, but compatibility with our exact SSE, authentication
and long-lived request behavior must be tested before the application
advertises the named transport as streaming-capable.

Official references (checked 2026-10-27):

- [Quick Tunnel limitations](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
- [Cloudflare Tunnel routing and public hostnames](https://developers.cloudflare.com/tunnel/concepts/routing/)
- [Protect a self-hosted application with Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)

## Proposed boundaries

Keep the existing model origin bound to loopback, forwarding **HTTPS API
traffic only** through a separately configured, pinned `cloudflared` process:

```text
Authorized client
  -> HTTPS + optional Cloudflare Access (operator-owned stable hostname)
  -> named tunnel (outbound-only, pinned executable)
  -> 127.0.0.1:<configured model HTTP port>
  -> Qwen vLLM-TPU OR GLM custom JAX/Pallas API
```

No SSH, root logins, public admin dashboard, notebook keepalive automation,
new model catalog, model weights, runtime engine replacement, or GCP is
part of this design. This transport must not be used to extend or circumvent
Kaggle accelerator/session policies, account eligibility or verification.

## Operator opt-in and prerequisites

Before any implementation or live transport test, obtain explicit operator
authorization for the **owned Cloudflare account and domain**, exact hostname,
credentials handling, allowable network exposure, any service costs and the
test environment. A Cloudflare account or domain cannot be inferred from a
repository URL. If the operator is not eligible to use a provider account,
do not create, share, borrow or bypass that account.

The implementation must not create Cloudflare resources, DNS routes, Access
policies or public ingress automatically merely because the launcher starts.

### Auth and secret handling

1. A public hostname must have an explicit inbound access policy before
   it becomes usable; configure Access where appropriate. Validate Access
   protection at the edge/origin as recommended by Cloudflare.
2. Preserve the **separate model API key** checks at the model server,
   independently of any Cloudflare Access credential. Never use the tunnel
   token as a model API key.
3. Protect tunnel credentials at rest and in child-process environments.
   Do not put them in PRs, notebooks, logs, CLI arguments visible in process
   listings, shared JSON diagnostics or telemetry.
4. Never forward untrusted client-supplied hostnames or HTTP redirects with
   authorization headers; model origins remain fixed loopback services.
5. Avoid logs containing live public URLs paired with credentials. Retain
   the existing credential-redaction and source-pinned `cloudflared` policy.

### Lifecycle and fail-safe behavior

- Tunnel processes must be scoped to their owning session/configuration.
  Record PID and creation time/config binding before attempting recovery;
  never stop unrelated tunnels, kernels or services.
- A tunnel becoming unreachable must not be interpreted as a dead TPU or
  trigger a restart of an otherwise healthy model.
- Losing the stable tunnel must not disable local serving. Display
  `transport_unavailable` rather than claiming remote SSE success.
- Quick Tunnel may remain an explicitly labeled HTTP fallback;
  it must **not** be labeled incremental-SSE-capable.
- Preserve the model owner's explicit stop/idle limits and Kaggle's reclaim
  decisions; do not add browser inactivity-prompt automation.

## Capability reporting contract (proposed, not present)

A future UI/launcher status field could include:

```text
transport_kind: local | quick | named
transport_state: not_configured | connecting | reachable | failed
hostname_source: none | ephemeral | operator_configured
sse_qualification: not_tested | failed | verified
qualification_scope: loopback | named_transport | live_model
```

Do not infer `sse_qualification=verified` from:
- a running `cloudflared` PID or a hostname,
- a successful `GET /health` or `GET /v1/models`,
- an eventual complete SSE body with `[DONE]`,
- Model Proxy adapter CI, synthetic TPU or CPU/JAX test results.

## Acceptance layers (separate evidence)

**A. Offline protocol tests (safe now).** Use a local fixture upstream that
flushes a first `data:` event and blocks on an explicit barrier before
releasing `[DONE]`. Assert that the client receives the first event before
the producer sends the rest. Cover wrong/missing Bearer, missing
`[DONE]`, cancellation, tool-call argument fragments and secret-safe errors.
These tests do not validate remote transport.

**B. Named transport on a test-owned, non-TPU HTTP fixture (requires explicit
hostname/credential/network authorization).** Verify the *actual* end-to-end
HTTPS path incrementally delivers the first SSE event while the upstream
fixture remains paused. Verify Access policy enforcement, origin API key
enforcement, non-stream JSON, cancellation, bounded inactivity, client
disconnect and transport reconnect. Record exact asset release, origin
commit, tunnel settings and timestamp; redact sensitive fields. Qualify
`named_transport` only after this independent evidence, never merely from
provider documentation.

**C. Live Qwen and GLM TPU inference (separately deferred).** Follow
[`LIVE_SMOKE_TEST.md`](LIVE_SMOKE_TEST.md) only after the owner explicitly
authorizes use of a test-owned permitted Kaggle accelerator session. Verify
each model's READY state, correct device allocation, bounded authenticated
requests, streaming/tool behavior and cleanup. No paid TPU or identity/
quota/session-limit bypass is authorized by this proposal.

## Rollout decision

Do not alter the default kernel transport or Windows Companion settings
in this phase. The next implementable engineering task, after operator
authorization and the network-fixture acceptance rubric are approved, is
a small optional named-tunnel adapter with hermetic lifecycle tests and a
separate release gate. No implementation of that adapter is claimed here.
