# Companion browser E2E — mock only

This repeatable UI journey validates the **actual React frontend** in a real
Chrome browser using the repository's built-in synthetic backend.

**No Kaggle account, API token, TPU session, GCP billing or external inference**
is required. `PREVIEW` is an essential part of the expected UI state.

## Windows PowerShell

Run the following from `C:\Work\kaggle-tpu-lab`:

~~~powershell
npm ci
npm run build
npm run preview -- --host 127.0.0.1 --port 41731 --strictPort
~~~

In another PowerShell terminal in the same repository:

~~~powershell
# Install Playwright explicitly only if you don't already have it:
# python -m pip install playwright==1.57.0
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
4. Idle → mock Start → queued → Stop confirmation → mock stopped session.
5. Failed-session error visibility and ability to restart.
6. Theme selection survives a browser reload.

These are **browser E2E tests of the mock frontend**, not API or TPU E2E.
The `source` implementation in `src/lib/backend.ts` intentionally returns
synthetic session snapshots outside the Tauri desktop runtime.

## CI and limitations

The `companion-browser-e2e.yml` workflow runs this script in Chrome on
GitHub Actions, builds the frontend from the PR revision and has read-only
repository permissions. It uses **no Kaggle credentials** or model API calls.

Actual Windows Tauri UI, native tray behavior, local credential integration,
real Kaggle start/stop, Anthropic/OpenAI streaming and TPU/GCP allocation
remain independent release gates.

User-supplied screenshots of the **native** Windows Companion have since been
reviewed separately. See [native visual QA](NATIVE_GUI_VISUAL_QA_20261023.md)
for screenshot-supported observations and the native interaction gaps.
