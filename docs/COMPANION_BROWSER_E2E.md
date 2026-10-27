# Companion browser E2E — mock only

This repeatable UI journey validates the **actual React frontend** in a real
Chrome browser using the repository's built-in synthetic backend.

**No Kaggle account, API token, TPU session, GCP billing or external inference**
is required. `PREVIEW` is an essential part of the expected UI state.

## Windows PowerShell

Run the following from **your own repository checkout root**:

~~~powershell
npm ci
npm run build
npm run preview -- --host 127.0.0.1 --port 41731 --strictPort
~~~

In another PowerShell terminal in the same repository:

~~~powershell
# Install Playwright explicitly only if you don't already have it:
# python -m pip install playwright==1.64.1
python tools/e2e_companion_preview.py --base-url http://127.0.0.1:41731
~~~

Stop the preview process with Ctrl+C in the first terminal after the tests.
The browser runner refuses non-localhost URLs and checks that the mock UI
does not make external network requests.

## Covered browser journeys

1. Qwen READY state, preview indicator, masked credential and model clipboard.
2. GLM READY state, three-stream default, rejection of invalid stream count
   and successful saving of an allowed value.
3. **Settings Cancel** discards unsaved changes after reopening the modal.
4. **Settings keyboard navigation:** focus moves into the dialog, Tab and
   Shift+Tab stay inside, Escape discards drafts, and focus returns to Change
   after Cancel, Save or Escape.
5. **Compact layouts:** Settings, Save and Cancel remain visible at 520 CSS px
   with DPR 1.0/1.25/1.5, and at 416/347 CSS px. These are viewport stress
   checks, **not** tests of physical Windows display-scaling changes.
6. Idle → mock Start → queued → Stop confirmation → mock stopped session.
7. **Stop confirmation keyboard safety:** Cancel is focused first, Tab stays in
   the dialog, Escape cancels without stopping, and focus returns to Stop.
8. Failed-session error visibility and ability to restart.
9. Theme selection survives a browser reload.

These are **browser E2E tests of the mock frontend**, not API or TPU E2E.
The `source` implementation in `src/lib/backend.ts` intentionally returns
synthetic session snapshots outside the Tauri desktop runtime.

## CI and limitations

The [browser E2E workflow](../.github/workflows/companion-browser-e2e.yml)
runs this script in Chrome on GitHub Actions for relevant PRs and changes
on `main`. It builds the frontend from the triggering revision and has read-only
repository permissions. It uses **no Kaggle credentials** or model API calls.

On Ubuntu 26.04 CI, the workflow pins Python Playwright `1.64.1`
([official release, 2026-10-22](https://github.com/microsoft/playwright-python/releases/tag/v1.64.1)),
which supports Ubuntu 26.04. It prints the Playwright and Chrome versions
for each CI run. The test intentionally uses the runner's existing
**Google Chrome Stable** via Playwright's `channel="chrome"`, not bundled
Chromium; no browser is installed or updated as part of the test. For
local Windows testing, use an already installed Chrome Stable and do not
silently replace or modify the user's browser installation.

This browser suite is not an installed Windows Tauri/tray test or a live
TPU/network test. See the [actual installed Companion 0.4.6 QA](WINDOWS_COMPANION_0_4_6_QA_20261025.md)
for its narrow native idle Save/Cancel/tray acceptance; the
[live TPU TODO](LIVE_SMOKE_TEST.md#todo-deferred-tpu-acceptance-not-a-test-pass)
still owns unverified session lifecycle, SSE/tool calling and transport.

User-supplied screenshots of the **native** Windows Companion have since been
reviewed separately. See [native visual QA](NATIVE_GUI_VISUAL_QA_20261023.md)
for screenshot-supported observations and the native interaction gaps.
