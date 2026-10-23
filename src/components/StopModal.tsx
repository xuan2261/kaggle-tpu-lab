import { useEffect, useRef } from "react";
import { Stop } from "@phosphor-icons/react";
import { useApp, actions } from "../lib/store";

export default function StopModal() {
  const { snapshot, busy, showStopModal } = useApp();
  const dialogRef = useRef<HTMLDivElement>(null);
  const stoppingRef = useRef(busy === "stop");

  useEffect(() => {
    stoppingRef.current = busy === "stop";
  }, [busy]);

  useEffect(() => {
    if (!showStopModal) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const opener = document.activeElement instanceof HTMLElement
      ? document.activeElement : null;
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>(
      "button:not(:disabled)",
    )).filter((element) => element.getClientRects().length > 0);

    // Focus Cancel by default: the destructive action must not be activated
    // accidentally. Keep keyboard focus inside until the dialog is closed.
    (focusable()[0] ?? dialog).focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (!stoppingRef.current) {
          event.preventDefault();
          event.stopPropagation();
          actions.closeStopModal();
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
  }, [showStopModal]);

  if (!showStopModal) return null;
  const stopping = busy === "stop";

  return (
    <div
      ref={dialogRef}
      className="overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="stop-title"
      tabIndex={-1}
      onClick={(e) => {
        if (e.target === e.currentTarget && !stopping) actions.closeStopModal();
      }}
    >
      <div className="modal">
        <div className="modal-icon tone-red">
          <Stop size={18} weight="bold" aria-hidden />
        </div>
        <h2 id="stop-title" className="modal-title">
          Stop the TPU session?
        </h2>
        <p className="modal-body">
          This asks Kaggle to stop kernel{" "}
          <code className="mono">{snapshot?.kernel ?? "…"}</code>. The endpoint
          goes away immediately; weights stay cached, so the next start is
          faster.
        </p>
        <p className="modal-body muted">
          Stop is confirmed through the official launcher and can take a few
          minutes.
        </p>
        <div className="modal-actions">
          <button
            className="btn btn-ghost"
            onClick={actions.closeStopModal}
            disabled={stopping}
          >
            Cancel
          </button>
          <button
            className="btn btn-danger"
            onClick={() => void actions.stop()}
            disabled={stopping}
          >
            {stopping ? "Stopping…" : "Stop session"}
          </button>
        </div>
      </div>
    </div>
  );
}
