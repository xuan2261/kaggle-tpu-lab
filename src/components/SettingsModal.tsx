import { useEffect, useRef, useState } from "react";
import { ArrowCounterClockwise, X } from "@phosphor-icons/react";
import type { ModelId, Settings } from "../types/session";
import { useApp, actions } from "../lib/store";

const DEFAULTS: Settings = {
  projectRoot: null,
  model: "qwen38-27b",
  keepaliveMin: 480,
  qwen: {
    context: 262144,
    mtp: 3,
    thinking: "xhigh",
    fastStart: true,
    textOnly: true,
    noAsyncScheduling: false,
  },
  glm: {
    context: 262144,
    streams: 3,
    thinking: "low",
    textOnly: false,
  },
};

export default function SettingsModal() {
  const { settings, showSettings, busy } = useApp();
  const [draft, setDraft] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const busyRef = useRef(busy != null);

  useEffect(() => {
    busyRef.current = busy != null;
  }, [busy]);

  useEffect(() => {
    // The dialog stays mounted while hidden. Discard uncommitted changes when
    // closing it, so Cancel and backdrop-close really cancel the draft.
    if (!showSettings) {
      setDraft(null);
      setError(null);
    }
  }, [showSettings]);

  useEffect(() => {
    if (!showSettings) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const opener = document.activeElement instanceof HTMLElement
      ? document.activeElement : null;
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
    )).filter((element) => element.getClientRects().length > 0);

    // Move keyboard focus into the modal; prevent Tab from reaching the page
    // behind it. Return focus to the opener on Cancel, Save or Escape.
    (focusable()[0] ?? dialog).focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (!busyRef.current) {
          event.preventDefault();
          event.stopPropagation();
          actions.closeSettings();
        }
        return;
      }
      if (event.key !== "Tab") return;
      const elements = focusable();
      if (!elements.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = elements[0];
      const last = elements[elements.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !dialog.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !dialog.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (opener?.isConnected) opener.focus();
    };
  }, [showSettings]);

  if (!showSettings) return null;
  const base = draft ?? settings ?? DEFAULTS;
  const saving = busy != null;

  function patch(p: Partial<Settings>) {
    setDraft({ ...base, ...p });
    setError(null);
  }

  function patchQwen(p: Partial<Settings["qwen"]>) {
    patch({ qwen: { ...base.qwen, ...p } });
  }

  function patchGlm(p: Partial<Settings["glm"]>) {
    patch({ glm: { ...base.glm, ...p } });
  }

  function submit() {
    if (base.keepaliveMin < 30 || base.keepaliveMin > 540)
      return setError("Keepalive must be between 30 and 540 minutes.");

    if (base.model === "qwen38-27b") {
      if (base.qwen.context !== 131072 && base.qwen.context !== 262144)
        return setError("Qwen context must be 131,072 or 262,144.");
      if (Number.isNaN(base.qwen.mtp) || base.qwen.mtp < 0 || base.qwen.mtp > 5)
        return setError("Qwen MTP must be between 0 and 5.");
      if (!["xhigh", "medium", "low"].includes(base.qwen.thinking))
        return setError("Qwen reasoning effort must be xhigh, medium or low.");
    } else {
      if (base.glm.context !== 131072 && base.glm.context !== 262144)
        return setError("GLM context must be 131,072 or 262,144.");
      if (Number.isNaN(base.glm.streams) || base.glm.streams < 1 || base.glm.streams > 3)
        return setError("GLM streams must be between 1 and 3.");
      if (!["high", "low"].includes(base.glm.thinking))
        return setError("GLM reasoning effort must be high or low.");
    }
    void actions.saveSettings(base);
  }

  return (
    <div
      ref={dialogRef}
      className="overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-title"
      tabIndex={-1}
      onClick={(e) => {
        if (e.target === e.currentTarget) actions.closeSettings();
      }}
    >
      <div className="modal modal-wide">
        <div className="modal-head-row">
          <h2 id="settings-title" className="modal-title">Settings</h2>
          <button className="icon-btn" onClick={actions.closeSettings} aria-label="Close settings">
            <X size={15} aria-hidden />
          </button>
        </div>

        <p className="modal-body muted">
          Applied to the next Start. A running Kaggle job keeps its current model and profile.
        </p>

        <div className="field-grid">
          <label className="field">
            <span>Model</span>
            <select
              value={base.model}
              onChange={(e) => patch({ model: e.target.value as ModelId })}
            >
              <option value="qwen38-27b">Qwen3.8-27B</option>
              <option value="glm53-flash">GLM-5.3-Flash</option>
            </select>
          </label>

          <label className="field">
            <span>Keepalive (min, 30–540)</span>
            <input
              type="number"
              min={30}
              max={540}
              value={base.keepaliveMin}
              onChange={(e) => patch({ keepaliveMin: Number(e.target.value) })}
            />
          </label>

          {base.model === "qwen38-27b" ? (
            <>
              <label className="field">
                <span>Max model len</span>
                <select
                  value={base.qwen.context}
                  onChange={(e) => patchQwen({ context: Number(e.target.value) })}
                >
                  <option value={131072}>131,072</option>
                  <option value={262144}>262,144</option>
                </select>
              </label>
              <label className="field">
                <span>MTP tokens (0–5)</span>
                <input
                  type="number"
                  min={0}
                  max={5}
                  value={base.qwen.mtp}
                  onChange={(e) => patchQwen({ mtp: Number(e.target.value) })}
                />
              </label>
              <label className="field">
                <span>Reasoning effort</span>
                <select
                  value={base.qwen.thinking}
                  onChange={(e) => patchQwen({ thinking: e.target.value })}
                >
                  <option value="xhigh">xhigh</option>
                  <option value="medium">medium</option>
                  <option value="low">low</option>
                </select>
              </label>
              <div className="field-check-row">
                <label className="field field-check">
                  <input
                    type="checkbox"
                    checked={base.qwen.textOnly}
                    onChange={(e) => patchQwen({ textOnly: e.target.checked })}
                  />
                  <span>Text only</span>
                </label>
                <label className="field field-check">
                  <input
                    type="checkbox"
                    checked={base.qwen.fastStart}
                    onChange={(e) => patchQwen({ fastStart: e.target.checked })}
                  />
                  <span>Fast start</span>
                </label>
                <label className="field field-check">
                  <input
                    type="checkbox"
                    checked={base.qwen.noAsyncScheduling}
                    onChange={(e) => patchQwen({ noAsyncScheduling: e.target.checked })}
                  />
                  <span>No async scheduling</span>
                </label>
              </div>
            </>
          ) : (
            <>
              <label className="field">
                <span>Max model len</span>
                <select
                  value={base.glm.context}
                  onChange={(e) => patchGlm({ context: Number(e.target.value) })}
                >
                  <option value={131072}>131,072</option>
                  <option value={262144}>262,144</option>
                </select>
              </label>
              <label className="field">
                <span>Streams</span>
                <input
                  type="number"
                  min={1}
                  max={3}
                  value={base.glm.streams}
                  onChange={(e) => patchGlm({ streams: Number(e.target.value) })}
                />
              </label>
              <label className="field">
                <span>Reasoning effort</span>
                <select
                  value={base.glm.thinking}
                  onChange={(e) => patchGlm({ thinking: e.target.value })}
                >
                  <option value="low">low</option>
                  <option value="high">high</option>
                </select>
              </label>
              <label className="field field-check">
                <input
                  type="checkbox"
                  checked={base.glm.textOnly}
                  onChange={(e) => patchGlm({ textOnly: e.target.checked })}
                />
                <span>Text only</span>
              </label>
            </>
          )}
        </div>

        {base.model === "glm53-flash" && (
          <p className="modal-body muted">
            GLM uses the launcher's serve-dataset default.
          </p>
        )}

        {error && <div className="form-error" role="alert">{error}</div>}

        <div className="modal-actions">
          <button
            className="btn btn-ghost"
            onClick={() => {
              setDraft(structuredClone(DEFAULTS));
              setError(null);
            }}
          >
            <ArrowCounterClockwise size={13} aria-hidden />
            Reset
          </button>
          <button className="btn btn-ghost" onClick={actions.closeSettings} disabled={saving}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
