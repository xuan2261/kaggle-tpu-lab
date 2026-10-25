# Windows Companion 0.4.6 — installed QA, 2026-10-25

**Scope:** Windows x64, current-user NSIS upgrade from the previously installed
Companion 0.4.5. Tested source HEAD:
`a7f8f707af5b7538bea278766d4894846e48249d`. This is a QA-only
installation, **not a signed public release or a live Kaggle TPU acceptance**.

## Why change the version?

Previous security/persistence fixes rebuilt the installer while leaving the
executable at version 0.4.5, making older and newer binaries ambiguous without
hash inspection. The QA patch now uses `0.4.6` across npm, npm lockfile,
Cargo manifest/lockfile and Tauri configuration. The Tauri application
identifier and the NSIS `currentUser` installation mode were deliberately
preserved.

## Build and identity

The following artifacts were built directly on Windows from the pinned HEAD.

| QA artifact | SHA-256 | Result |
| --- | --- | --- |
| NSIS `Kaggle TPU Companion_0.4.6_x64-setup.exe` | `cb126ac8ec0a61968b6b9ee245ad789759eb9f6590784cd63549d91223c74d58` | Build PASS, `NotSigned` |
| MSI `Kaggle TPU Companion_0.4.6_x64_en-US.msi` | `0a3c019f330549bdd09d2c0c0cc0590f5223081b56204a650959aee4e25af181` | Build PASS, `NotSigned`; **not installed** |
| Post-NSIS installed executable | `4bab8eb1fa1af93c111b1d19e502918224456504bcfd7e0e5c19f9f266b43e50` | FileVersion 0.4.6; `NotSigned` |

The NSIS installer showed the *older version installed* page. The upgrade
explicitly selected **Do not uninstall**, retained the existing
`%LOCALAPPDATA%/Kaggle TPU Companion` destination, and displayed
**Installation Complete**. Registry HKCU uninstall metadata now reports
`DisplayVersion=0.4.6`. No per-machine MSI, forced uninstall, disk-format
operation or production release was performed.

## Native and persistence acceptance

Before the upgrade, the prior installed executable and installer checksums
were verified. The existing private
`%APPDATA%/com.lucas.kaggle-tpu-companion/settings.json` and an isolated,
user-profile-local pre-upgrade backup had matching SHA-256 and DACL (SDDL).
Only the **comparison results**, not Settings contents, are recorded here.

| Test | Observed outcome |
| --- | --- |
| Upgrade keeps Settings file bytes, SHA and DACL | **PASS** |
| Start installed 0.4.6, inspect actual WebView2 native accessibility tree | **PASS** — `IDLE`, Qwen selected, no active session |
| Inactive connection actions | **PASS** — API-key copy disabled, connection waiting |
| Open Settings, click a draft checkbox, Cancel | **PASS** for Cancel closing and file/hash/DACL unchanged; checkbox state was not separately instrumented |
| Open Settings, Save without modifying values | **PASS** — modal closed; JSON valid, semantic values and SHA/DACL unchanged |
| Hide panel to tray | **PASS** — window hidden, process retained |
| Re-open via installed executable (single-instance reuse) | **PASS** — same process, panel visible, `IDLE` |
| Live TPU launch, SSE, tool calling | **NOT RUN** — explicitly deferred |

Native GUI interaction sometimes hid the flyout when the desktop inspection
tool changed focus. After opening Settings, the panel was reopened through
the installed executable and the modal's actual Cancel/Save actions completed.
This affects automation reliability and is **not proof** of every physical
display DPI, accessibility or focus behavior. No `Start TPU` action occurred,
and no Kaggle session state file was created.

## Source verification and release boundaries

The 0.4.6 version contract passed at every manifest. Windows
`cargo test --locked --offline` passed with **71 tests and one ignored**;
`npm run build` passed and `npm audit` reported **zero** advisories.
The ignored Rust test requires a real Kaggle session and remains excluded by
the user's current testing decision. The browser-mock and other CI results
must be pinned to their actual GitHub run, not called live TPU tests.

Unfinished product-release gates: signed installers/Authenticode identity,
live Qwen/GLM TPU and networking acceptance when the owner resumes it, and
remaining Rust advisory/formatting and multi-display native QA work. Keep
production release separate from source-branch merging.
