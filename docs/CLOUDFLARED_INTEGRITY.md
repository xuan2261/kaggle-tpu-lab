# cloudflared executable integrity

Both standalone Kaggle kernels use Cloudflare Quick Tunnel for optional HTTPS
access. Downloading `releases/latest` directly into an executable cache is
not acceptable: a changed or incomplete download must never become runnable.

## Pinned release

| Property | Value |
|---|---|
| Provider and source | [Cloudflare GitHub release 2026.10.4](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.4) |
| Asset | `cloudflared-linux-amd64` (raw executable, not DEB/RPM/FIPS) |
| Release date | 2026-10-26 |
| Size | 40,247,428 bytes |
| SHA-256 | `ae5e8add7884b0531d66bbca4570d1de491ff6da51e4ebe7eb160cdf241d9e42` |

The SHA-256 and size were read from that asset's GitHub Releases API metadata.
This pins downloaded *bytes*; it is not independent provenance attestation or
proof that the binary is free from upstream vulnerabilities.

## Runtime behavior

- A cached `/tmp/cloudflared` is reused only if its size and SHA-256 match.
  On POSIX, it must also be owner-executable and not group/other-writable.
  A cache with matching bytes but unsafe mode is restaged atomically as 0755
  without a network download. A mismatched cache is never executed.
- A new download or a Qwen environment-dataset bundle copy is written to a
  temporary file in the cache directory, checked in full, granted executable
  permissions, then atomically renamed into place.
- Failed, truncated, oversized or mismatched transfers leave existing cache
  bytes unchanged and clean up the staging file.
- The Qwen notebook prefers a verified bundled executable to avoid unnecessary
  Internet downloads. A Qwen maintainer bundle build fails unless a verified
  executable is exported; its manifest records exact version, asset, SHA-256
  and size. GLM only downloads when the tunnel feature is enabled.
- The executable is validated again before spawning the tunnel. If it cannot
  be validated, that tunnel must not start. Qwen falls back to its local
  endpoint on tunnel failure; GLM retains its prior startup behavior if the
  configured tunnel binary cannot be acquired.

## Upgrade procedure

1. Select an explicit release tag and the exact **Linux amd64 raw executable**
   asset from the official Cloudflare GitHub releases.
2. Read the asset's size and SHA-256 digest from the official release metadata.
   Never copy a checksum from an untrusted log, third-party mirror or model.
3. Update `CLOUDFLARED_VERSION`, `CLOUDFLARED_SHA256` and
   `CLOUDFLARED_BYTES` identically in:
   - `qwen38-27b/kernel/serve_qwen38.py`
   - `glm53-flash/kernel/serve_glm53.py`
4. Synchronize the complete `%%writefile serve_*.py` code cells in both
   notebooks with their corresponding kernel files.
5. Update this document and the exact release pin assertions in
   `tests/test_cloudflared_integrity.py`.
6. Run `python -m unittest discover -s tests -v`, Python compilation and
   `git diff --check`. Require the repository's normal CI on the final PR SHA.

The offline tests extract only isolated source functions from kernel ASTs.
They never execute cloudflared or access Kaggle/GCP. A verified executable
is **not** evidence of live TPU inference, Quick Tunnel connectivity or
incremental SSE. Those require separately authorized real-environment QA.
