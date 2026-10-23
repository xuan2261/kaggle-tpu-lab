#!/usr/bin/env python3
"""Real-browser E2E checks of the Companion's local mock frontend.

Runs only against a pre-existing localhost Vite preview. It never starts a
Kaggle kernel, contacts a Kaggle account or handles real API credentials.

Prerequisites: a supported Chrome browser and Python Playwright installed.
Run: python tools/e2e_companion_preview.py --base-url http://127.0.0.1:41731
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def localhost_url(value: str) -> str:
    parts = urlsplit(value.rstrip("/"))
    if (parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "localhost")
            or parts.username or parts.password or parts.query or parts.fragment):
        raise ValueError("The E2E runner accepts only http://127.0.0.1 or localhost")
    if parts.path not in ("", "/") or not parts.port:
        raise ValueError("Supply the root URL and explicit local preview port")
    return value.rstrip("/")


def open_preview(browser, base: str, model: str, phase: str, *,
                 width: int = 610, scale: float = 1.0):
    context = browser.new_context(
        viewport={"width": width, "height": 960},
        device_scale_factor=scale,
        permissions=["clipboard-read", "clipboard-write"],
    )
    page = context.new_page()
    errors: list[str] = []
    outside: list[str] = []
    page.on("pageerror", lambda error: errors.append(type(error).__name__))

    def track_request(request):
        if urlsplit(request.url).hostname not in ("127.0.0.1", "localhost"):
            outside.append(urlsplit(request.url).hostname or "unknown-host")

    page.on("request", track_request)
    page.goto(
        f"{base}/?model={model}&mock={phase}&static=1",
        wait_until="networkidle",
        timeout=15000,
    )
    expect(page.get_by_text("PREVIEW", exact=True)).to_be_visible()
    return context, page, errors, outside


def verify_safety(page, errors: list[str], outside: list[str]):
    if errors:
        raise AssertionError(f"Uncaught browser errors: {len(errors)}")
    if outside:
        raise AssertionError(f"Unexpected external browser requests: {outside}")
    if "sk-preview-only" in page.locator("body").inner_text():
        raise AssertionError("Mock credential unexpectedly visible in page body")


def case_qwen_ready(browser, base):
    ctx, page, errors, outside = open_preview(browser, base, "qwen38-27b", "ready")
    try:
        body = page.locator("body").inner_text()
        for label in ("Qwen3.8-27B", "READY", "MTP 3", "qwen3.8-27b"):
            if label not in body:
                raise AssertionError(f"Expected Qwen READY label absent: {label}")
        expect(page.get_by_role("button", name="Copy API key")).to_be_enabled()
        page.get_by_role("button", name="Copy model name").click()
        copied = page.evaluate("navigator.clipboard.readText()")
        if copied != "qwen3.8-27b":
            raise AssertionError("Mock model name clipboard did not match Qwen")
        verify_safety(page, errors, outside)
    finally:
        ctx.close()


def case_glm_profile_and_validation(browser, base):
    ctx, page, errors, outside = open_preview(browser, base, "glm53-flash", "ready")
    try:
        body = page.locator("body").inner_text()
        for label in ("GLM-5.3-Flash", "3 streams", "READY", "glm-5.3-flash"):
            if label not in body:
                raise AssertionError(f"Expected GLM READY label absent: {label}")
        trigger = page.get_by_role("button", name="Change")
        trigger.click()
        modal = page.get_by_role("dialog", name="Settings")
        expect(modal).to_be_visible()
        streams = modal.get_by_label("Streams")
        expect(streams).to_have_value("3")
        streams.fill("4")
        modal.get_by_role("button", name="Save").click()
        expect(modal.get_by_role("alert")).to_contain_text(
            "GLM streams must be between 1 and 3"
        )
        streams.fill("2")
        modal.get_by_role("button", name="Save").click()
        expect(modal).not_to_be_visible()
        expect(trigger).to_be_focused()
        expect(page.get_by_text("2 streams")).to_be_visible()
        verify_safety(page, errors, outside)
    finally:
        ctx.close()


def case_cancel_discards_settings(browser, base):
    ctx, page, errors, outside = open_preview(browser, base, "glm53-flash", "ready")
    try:
        trigger = page.get_by_role("button", name="Change")
        trigger.click()
        modal = page.get_by_role("dialog", name="Settings")
        streams = modal.get_by_label("Streams")
        expect(streams).to_have_value("3")
        streams.fill("2")
        modal.get_by_role("button", name="Cancel").click()
        expect(modal).not_to_be_visible()
        expect(trigger).to_be_focused()
        trigger.click()
        reopened = page.get_by_role("dialog", name="Settings")
        expect(reopened.get_by_label("Streams")).to_have_value("3")
        verify_safety(page, errors, outside)
    finally:
        ctx.close()


def case_settings_keyboard_navigation(browser, base):
    """ARIA modal: focus enters, stays trapped, Escape cancels and restores focus."""
    ctx, page, errors, outside = open_preview(browser, base, "glm53-flash", "ready")
    try:
        trigger = page.get_by_role("button", name="Change")
        trigger.focus()
        trigger.press("Enter")
        dialog = page.get_by_role("dialog", name="Settings")
        expect(dialog).to_be_visible()
        close_button = dialog.get_by_role("button", name="Close settings")
        expect(close_button).to_be_focused()
        page.keyboard.press("Shift+Tab")
        expect(dialog.get_by_role("button", name="Save")).to_be_focused()
        page.keyboard.press("Tab")
        expect(close_button).to_be_focused()

        dialog.get_by_label("Streams").fill("2")
        page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()
        expect(trigger).to_be_focused()
        trigger.press("Enter")
        expect(page.get_by_role("dialog", name="Settings")
               .get_by_label("Streams")).to_have_value("3")
        verify_safety(page, errors, outside)
    finally:
        ctx.close()


def case_settings_compact_viewports(browser, base):
    """CSS layout stress checks; these do not claim to change native Windows DPI."""
    for width, scale in ((520, 1.0), (520, 1.25), (520, 1.5),
                         (416, 1.0), (347, 1.0)):
        ctx, page, errors, outside = open_preview(
            browser, base, "glm53-flash", "ready", width=width, scale=scale,
        )
        try:
            page.get_by_role("button", name="Change").click()
            dialog = page.get_by_role("dialog", name="Settings")
            expect(dialog).to_be_visible()
            for label, element in (
                ("Settings dialog", dialog),
                ("Save action", dialog.get_by_role("button", name="Save")),
                ("Cancel action", dialog.get_by_role("button", name="Cancel")),
            ):
                rect = element.bounding_box()
                if rect is None or rect["x"] < -1 or rect["y"] < -1 or (
                    rect["x"] + rect["width"] > width + 1
                ) or rect["y"] + rect["height"] > 961:
                    raise AssertionError(
                        f"{label} clips viewport {width}px at {scale} DPR"
                    )
            scroll_width, viewport_width = page.evaluate(
                "() => [document.documentElement.scrollWidth, window.innerWidth]"
            )
            if scroll_width > viewport_width + 1:
                raise AssertionError(
                    f"Unexpected horizontal overflow at {width}px/{scale} DPR"
                )
            page.keyboard.press("Escape")
            expect(dialog).not_to_be_visible()
            verify_safety(page, errors, outside)
        finally:
            ctx.close()


def case_start_and_stop(browser, base):
    ctx, page, errors, outside = open_preview(browser, base, "qwen38-27b", "idle")
    try:
        expect(page.get_by_role("button", name="Start Qwen3.8-27B")).to_be_visible()
        page.get_by_role("button", name="Start Qwen3.8-27B").click()
        expect(page.get_by_role("button", name="Stop session")).to_be_visible()
        page.get_by_role("button", name="Stop session").click()
        modal = page.get_by_role("dialog", name="Stop the TPU session?")
        expect(modal).to_be_visible()
        modal.get_by_role("button", name="Cancel").click()
        expect(modal).not_to_be_visible()
        page.get_by_role("button", name="Stop session").click()
        modal.get_by_role("button", name="Stop session").click()
        expect(page.get_by_role("button", name="Start Qwen3.8-27B")).to_be_visible()
        if "TPU session stopped" not in page.locator("body").inner_text():
            raise AssertionError("Stop action did not update the mock session state")
        verify_safety(page, errors, outside)
    finally:
        ctx.close()


def case_stop_confirmation_keyboard(browser, base):
    """A destructive confirmation must keep focus and permit Escape to cancel."""
    ctx, page, errors, outside = open_preview(browser, base, "qwen38-27b", "idle")
    try:
        page.get_by_role("button", name="Start Qwen3.8-27B").click()
        opener = page.get_by_role("button", name="Stop session")
        opener.focus()
        opener.press("Enter")
        dialog = page.get_by_role("dialog", name="Stop the TPU session?")
        expect(dialog).to_be_visible()
        cancel = dialog.get_by_role("button", name="Cancel")
        expect(cancel).to_be_focused()
        page.keyboard.press("Shift+Tab")
        expect(dialog.get_by_role("button", name="Stop session")).to_be_focused()
        page.keyboard.press("Tab")
        expect(cancel).to_be_focused()
        page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()
        expect(opener).to_be_focused()
        # Escape never confirms the destructive action.
        expect(opener).to_be_visible()
        verify_safety(page, errors, outside)
    finally:
        ctx.close()


def case_failed_state(browser, base):
    ctx, page, errors, outside = open_preview(browser, base, "qwen38-27b", "failed")
    try:
        expect(page.get_by_role("button", name="Start Qwen3.8-27B")).to_be_visible()
        if "vLLM exited" not in page.locator("body").inner_text():
            raise AssertionError("Failed-session diagnostics are not visible")
        verify_safety(page, errors, outside)
    finally:
        ctx.close()


def case_theme(browser, base):
    ctx, page, errors, outside = open_preview(browser, base, "glm53-flash", "ready")
    try:
        before = page.locator("html").get_attribute("data-theme")
        if before not in ("dark", "light"):
            raise AssertionError(f"Unknown initial UI theme: {before!r}")
        opposite = "light" if before == "dark" else "dark"
        page.get_by_role("button", name=f"Switch to {opposite} theme").click()
        expect(page.locator("html")).to_have_attribute("data-theme", opposite)
        page.reload(wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("data-theme", opposite)
        verify_safety(page, errors, outside)
    finally:
        ctx.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Already-running local Vite preview")
    parser.add_argument("--browser", default="chrome", help="Installed Playwright Chrome channel")
    args = parser.parse_args(argv)
    base = localhost_url(args.base_url)
    cases = [
        ("Qwen READY and mock model clipboard", case_qwen_ready),
        ("GLM READY/settings validation/save", case_glm_profile_and_validation),
        ("Cancel settings discards changes", case_cancel_discards_settings),
        ("Settings keyboard focus trap and Escape cancel", case_settings_keyboard_navigation),
        ("Settings stays usable at compact CSS widths and DPR", case_settings_compact_viewports),
        ("Start / cancel stop / confirm stop", case_start_and_stop),
        ("Stop confirmation keyboard trap and Escape", case_stop_confirmation_keyboard),
        ("Failed session error visibility", case_failed_state),
        ("Theme toggle persists", case_theme),
    ]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.browser, headless=True)
        try:
            for label, callback in cases:
                try:
                    callback(browser, base)
                    print("PASS:", label, flush=True)
                except Exception as exc:
                    print("FAIL:", label, type(exc).__name__, str(exc)[:400],
                          file=sys.stderr, flush=True)
                    return 1
        finally:
            browser.close()
    print(json.dumps({"cases": len(cases), "passed": len(cases),
                      "mode": "browser-mock", "real_kaggle_requests": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
