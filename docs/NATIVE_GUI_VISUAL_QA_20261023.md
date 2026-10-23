# Native Windows Companion — screenshot-backed QA (2026-10-23)

**Repository:** `xuan2261/kaggle-tpu-lab`

**Baseline reviewed:** `main@4f06e121f80e26758987d5ba1d8ed36733c65eb8`

**Target:** Tauri Windows Companion 0.4.5, idle/no active Kaggle TPU session.

## Evidence provenance

The user supplied three PNG screenshots in the conversation. They are **not
copied or published in this repository**. The source-file names, actual pixel
dimensions and SHA-256 hashes identify the exact images reviewed:

| User-provided screenshot | Dimensions | SHA-256 |
| --- | --- | --- |
| `image(20261023-024126).png` | 523 × 905 | `9e97e5a231bdf297c33a176b83d98ab38884ea9fcbbbca4bf735800924281285` |
| `image(20261023-024139).png` | 518 × 916 | `eb66bb331a7a7b38e1fd388af688ae6f58a3f3971f2537906523c46e52dbb1ae` |
| `image(20261023-024244).png` | 520 × 905 | `3d36f9f48dfca3742aa3b3ba24a5d61a2afd09465ff04ed8a9569e0eb579e0d5` |

These are user-submitted captures, not an automated native-window screenshot
or proof that a particular button action completed.

## Screenshot-supported observations

| Visual contract | Observation | Verdict |
| --- | --- | --- |
| Dark and light appearance | The main Companion interface is visible in both palettes, with consistent layout, cards and bottom Start action | **VISUAL PASS** |
| Settings dialog | Centered, modal overlay; title, Save/Cancel/Reset, model selector, keepalive and profile fields are visible | **VISUAL PASS** |
| Idle state | `IDLE`, `No active session`, `WAITING` endpoint and zero activity events appear | **VISUAL PASS** |
| Qwen defaults | Qwen3.8-27B, 262,144 context, xhigh reasoning, MTP 3; Settings displays 480-minute keepalive | **VISUAL PASS** |
| Secret masking | BASE URL / API KEY show empty placeholders for the idle session | **VISUAL PASS for these captures** |
| Basic layout | 518–523px-wide portrait view; main controls are inside the screenshots; no obvious overlap or clipped modal actions | **VISUAL PASS for these sizes** |
| Native Settings Save/Cancel persistence | No before/after evidence from the real native window | **NOT VERIFIED** |
| Tray close/reopen and keyboard focus | The screenshots do not capture a complete tray or focus journey | **NOT VERIFIED** |
| Native action execution | No actual Kaggle launch/stop or live API key copying is shown | **NOT VERIFIED** |

Small muted labels and disabled controls merit a future accessibility/contrast
measurement; apparent readability in these screenshots is not a WCAG contrast
conformance test.

## Independent executable evidence

- Prior Windows smoke successfully built and launched a genuine Tauri process
  with a native WebView2 window; background capture was inconclusive because
  the window hid on focus loss.
- The committed [browser-mock suite](../tools/e2e_companion_preview.py)
  independently checks nine journeys: Qwen/GLM READY, invalid GLM stream count
  and save, Settings Cancel, keyboard focus trapping and Escape, compact CSS
  widths/DPR, Start/Stop with confirmation, Stop keyboard cancellation,
  failed session display, and theme persistence. These run in a browser **mock** backend and
  do **not** prove native Tauri IPC or real Kaggle session behavior.
- Offline mock gateway contract tests cover OpenAI Chat Completions and
  Anthropic Messages. Two additional regressions cover Anthropic SSE event
  passthrough and OpenAI tool-call request/response passthrough. Mock tests
  establish only the adapter contract: they do **not** establish whether
  Kaggle's real models will stream or choose tools as asked.
- Previous limited live Model Proxy smoke verified non-streaming requests
  through localhost gateway (2/2 HTTP 200), without validating SSE/tool use.

## Next native acceptance checklist

1. Re-open the genuine Windows Companion without starting a TPU. Confirm
   Settings opens from **Change** and defaults match its displayed profile.
2. Change one draft field (e.g. GLM streams 3 → 2), press **Cancel**, re-open
   Settings and verify the original saved value remains unchanged.
3. Re-open the dialog, intentionally **Save** a valid profile, close/reopen
   the tray panel, then re-check settings persistence. Restore the prior
   setting when finished.
4. Toggle Dark/Light, close/reopen the panel, test scrolling, keyboard
   navigation/focus, and confirm the Stop action is not offered when idle.
5. Check the display at 100%, 125% and 150% Windows scaling; inspect minimum
   text/control contrast and screen-reader labels if accessibility is required.
6. Treat live Qwen/GLM TPU sessions, native launcher credentials, SSE through
   supported networking transports, tool calls and installer installation as
   **separate release gates**.

**Safety:** No extra Kaggle inference requests, TPU starts, GCP provisioning,
or release deployment are part of this screenshot review.

## Follow-up keyboard and DPI-oriented QA

On 2026-10-23, additional browser automation revealed two missing keyboard
contracts: **Settings** did not initially move focus inside its dialog or
close on Escape, and **Stop confirmation** did not trap Tab or support Escape.
Both failed targeted browser regression checks before repair. A Stop-modal
focus-restoration failure was additionally caught by the tests and corrected.

The frontend now moves focus into both dialogs, traps Tab/Shift+Tab, lets
Escape cancel when no save/stop action is in progress, and returns focus to
the opening control when that control still exists. The destructive Stop
confirmation initially focuses **Cancel**, not Stop.

**Browser-mock checks: 9/9 PASS.** Settings, Save and Cancel were also verified
inside the simulated CSS viewport at 520px (DPR 1.0, 1.25, 1.5) and narrower
416px/347px widths, without horizontal overflow or uncaught JavaScript
errors. The simulated device-pixel ratio **is not** a Windows OS DPI change.
Physical display scaling and minimum WCAG text contrast remain unverified.

An isolated-profile Tauri run successfully started the native process and a
WebView2 window, but the local WebView2 debug port did not open, and the
native-window screenshot helper could not obtain reliable pixels. The
computer-use accessibility tree contained panes but not actionable settings
controls. Hence automated native Save/Cancel persistence and tray behavior
remain **NOT VERIFIED**, not PASS. There was no Kaggle session state and no
Start TPU action. The test process was shut down; the temporary QA profile
was fully cleaned on a subsequent verified attempt (after Windows released
its NVIDIA cache files). No user Settings file was written in the
isolated profile.

The backend native Settings persistence path is now exercised independently
with disposable JSON files, validation, rollback on write failure and reload.
See [native persistence QA](NATIVE_SETTINGS_PERSISTENCE_QA_20261023.md).
This does **not** change the native visual/interaction verdict.
