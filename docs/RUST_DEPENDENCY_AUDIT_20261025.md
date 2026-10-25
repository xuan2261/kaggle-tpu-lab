# Rust dependency advisory review — 2026-10-25

**Scope:** `src-tauri/Cargo.lock`, Windows x64 Companion 0.4.5. This is
dependency-security evidence, not an attestation of every code path or a
production security certification. No Kaggle inference, TPU or GCP was used.

## Method and results

The pre-change lockfile SHA-256 was
`feb28ce6986f7ce4cdbdd85d46a30ead116bba75aa40987318f540ecfeac8c70`.
Using Python standard-library HTTP requests, we queried the public
[OSV batch API](https://google.github.io/osv.dev/post-v1-querybatch/)
for all registry-sourced `crates.io` name/version pairs in the file.
The query covered **540 pairs**, in six batches, with no pagination indicated.
OSV initially matched **19 advisory IDs**, including aliases for the same
underlying issue and maintenance-only notices.

| Dependency | Locked before | Locked after | Rationale |
| --- | --- | --- | --- |
| `rustls` | 0.23.43 | 0.23.46 | Fixes multiple TLS handshake/secret-handling advisories |
| `rustls-webpki` | 0.103.15 | 0.103.16 | Certificate-chain verification advisory |
| `webpki-roots` | 1.0.9 | 1.0.10 | Removes affected trust anchors |
| `tokio` | 1.53.1 | 1.53.3 | Patches an I/O safety advisory affecting Unix APIs |

This was a **precise Cargo.lock-only update**, not a Rust toolchain upgrade or
unbounded dependency refresh. Git diff confirms the only registry package
version changes are the four rows above. The post-update lockfile SHA-256 is
`fc80334fee7d741bfe171d4427aa33a472c35997eff01ee13cbf649a8f11e56c`.

The same full OSV query was repeated against the revised lockfile: **11 IDs**
remained, none matching the four updated packages. OSV results are advisory
matches, not a count of independent exploitable defects. See the
[RustSec advisory database](https://github.com/rustsec/advisory-db) for upstream
details and maintenance categories.

The Windows dependency tree confirms that `rustls`, `rustls-webpki` and
`webpki-roots` are reachable through `ureq` from the Companion; `tokio` is
used by Tauri. The particular Tokio `AsyncFd` defect is specific to Unix.
`glib` and `zvariant` were not resolved in the Windows target tree and
therefore their existing lockfile advisories are **not Windows runtime
findings** for this application.

## Remaining advisories and constraints

The 11 remaining IDs consist of `glib` (two alias IDs for one soundness
advisory), one `proc-macro-error` maintenance notice, five `unic-*`
maintenance notices, and three `zbus_names`/`zvariant*` maintenance
notices. No replacement of the Linux GTK stack or transitive unmaintained
dependencies is attempted in this Windows-focused patch.

The upstream `cargo audit` binary was not installed locally. This report uses
OSV/RustSec lookups instead; it does not establish complete vulnerability
coverage for native libraries, build scripts, all target platforms, or
unpublished issues. Additional release QA should confirm the Linux target
dependency tree where supported.

**Windows tests with the patched lockfile:** `cargo test --locked
--manifest-path src-tauri/Cargo.toml` succeeded with **71 passed, 0 failed,
1 ignored**; the ignored test requires a live Kaggle session and remains
deferred. Normal Rust dead-code/unused warnings were still present.

## Next qualification

Run GitHub Rust Windows CI on the exact updated lockfile, confirm any
installer is rebuilt after the lockfile change, and preserve the owner's
AppData Settings during an explicitly scoped installed-version upgrade.
Do not treat this advisory review as signing approval or closure of the
deferred live Kaggle TPU TODO.
