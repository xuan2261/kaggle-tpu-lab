# Native Settings persistence QA — 2026-10-23

**Scope:** Windows Tauri Companion 0.4.5 Settings persistence backend
(src-tauri/src/state/settings.rs and src-tauri/src/commands/mod.rs).
Baseline: main@4fb417c62f80597125af9c4a455a9fd1d32bc210.

## Confirmed defect

Before this patch, the native save_settings command wrote new values into
the running AppState Settings mutex **before** calling Settings::save().
If the filesystem write failed, the command returned an error, while
subsequent get_settings calls still observed the unpersisted values.
Those values would not reliably survive restarting the application.

The operation now holds the Settings lock, validates the candidate, persists
it successfully, and only then changes in-memory state. If validation or
the filesystem write fails, the previous in-memory values remain intact.

## Isolated Rust tests

The new Rust test helpers run the real Settings JSON encoding, loading,
legacy-profile migration and disk-saving logic against explicit temporary
file paths. They **never** change USERPROFILE, HOME, or an existing
AppData/Roaming/com.lucas.kaggle-tpu-companion/settings.json.
Disposable files are removed by test fixture cleanup.

| Contract | Validation |
| --- | --- |
| GLM/Qwen profile and keepalive survive save → file → reload | Rust unit test |
| Missing or malformed file falls back to defaults | Rust unit test |
| A genuine filesystem write error leaves memory unchanged | Rust regression test |
| Successful disk save updates memory and survives reload | Rust regression test |
| Invalid GLM streams do not reach persistence | Rust regression test |

Run from the Windows repository checkout:

~~~powershell
cargo test --locked --offline --manifest-path src-tauri/Cargo.toml settings
cargo test --locked --offline --manifest-path src-tauri/Cargo.toml
~~~

## QA observations on Windows

- Targeted native Settings tests: **12/12 PASS** (including five added
  persistence and transaction tests).
- Full Rust unit tests: **66 PASS, 0 FAIL, 1 ignored**.
- Python unit/integration: **36/36 PASS**.
- TypeScript/Vite production build: **PASS**.
- Chrome UI mock E2E: **9/9 PASS**.
- npm audit: **0 reported findings**.
- Build of the actual unsigned Windows installers: **PASS**, both NSIS
  and MSI generated under src-tauri/target/release/bundle. No installer was
  launched and no operating-system installation was performed.

| QA bundle | Bytes | SHA-256 |
| --- | ---: | --- |
| NSIS: Kaggle TPU Companion_0.4.5_x64-setup.exe | 2,592,541 | 22085c827edb7b5b358a1081751137a39dafde322c38d8439f59bb0574661c04 |
| MSI: Kaggle TPU Companion_0.4.5_x64_en-US.msi | 3,534,848 | 5496793975b0aa72afd5c47ba65772ba8a958c61425d63f4815e97622a66b3f2 |

Both installer signatures were verified as **NotSigned**. The separate
Rust release build and both installers succeeded, but installation/uninstall,
native screen interaction, and OS-managed user-profile migration remain
unverified. Packaging does not establish production readiness.

The repository-wide cargo fmt --check reports formatting differences in
untouched source files as well as touched modules. Formatting was not
mass-applied; this is a separate existing style-quality item, not a
reported passing check.

## Independent acceptance gates

- These tests cover **native Rust persistence**, not real WebView2 dialog
  interactions. Cancel/Save, focus, tray behavior and DPI still require
  native end-to-end acceptance on Windows.
- At the **2026-10-23 baseline**, file saving was not a replace-style write.
  Later work on the PR added staging/replacement; see
  [the subsequent QA record](NON_TPU_QA_20261025.md). Full power-loss
  durability remains a separate qualification.
- MSI/NSIS installation, Kaggle TPU jobs and real hosted SSE/tool calling
  remain separate release gates.

No Kaggle credential was read or model inference request sent.
