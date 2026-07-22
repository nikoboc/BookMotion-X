#!/usr/bin/env python3
"""In-app Kindle login (Windows / WebView2) — get cookies without cookies.txt.

Opens a real browser window (WebView2 via pywebview) at the Amazon Kindle
notebook page. The user signs in normally — 2FA / CAPTCHA included, since it is a
real browser engine — and once the Amazon auth cookies appear we harvest them
and save them to the app's cookie store, the same place a cookies.txt import
writes. The rest of the sync pipeline (build_session → requests) is unchanged.

Run as a short-lived subprocess: gui.py re-invokes the app with --kindle-login,
so pywebview can own the process's main thread without fighting the Tk loop.
Exit code 0 = cookies saved, non-zero = cancelled / unavailable / failed.
"""
import sys
import time
from email.utils import parsedate_to_datetime

import kindle_notion as core

LOGIN_URL = "https://read.amazon.co.jp/notebook"
# Amazon auth cookies — any one of these means the browser session is signed in.
AUTH_COOKIES = ("at-main", "sess-at-main", "x-main", "session-token")
POLL_SECONDS = 1.0
TIMEOUT_SECONDS = 300


def _epoch(expires):
    """Parse a cookie ``expires`` (RFC-1123 string) to epoch seconds, or None."""
    if not expires:
        return None
    try:
        return int(parsedate_to_datetime(expires).timestamp())
    except Exception:
        return None


def _flatten(simple_cookies):
    """pywebview returns a list of http.cookies.SimpleCookie; flatten to dicts."""
    out = []
    for sc in simple_cookies or []:
        items = getattr(sc, "items", None)
        if not items:
            continue
        for name, m in sc.items():
            out.append({
                "name": name,
                "value": m.value,
                "domain": m["domain"] or "",
                "path": m["path"] or "/",
                "expires": _epoch(m["expires"]),
                "secure": bool(m["secure"]),
            })
    return out


def run() -> int:
    """Open the login window, harvest the Kindle cookies, and save them.

    Returns 0 if cookies were saved, else non-zero: 2 = not Windows, 3 = no
    pywebview available, 1 = the user cancelled or it timed out. See the module
    docstring for the overall flow.
    """
    if not sys.platform.startswith("win"):
        return 2
    try:
        import webview
    except Exception:
        return 3

    state = {"saved": 0}

    def harvest(window):
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while time.monotonic() < deadline and not state["saved"]:
            time.sleep(POLL_SECONDS)
            try:
                url = window.get_current_url() or ""
                if "/ap/" in url or "signin" in url:
                    continue  # still on the sign-in flow — wait
                cookies = _flatten(window.get_cookies())
            except Exception:
                continue
            if any(c["name"] in AUTH_COOKIES for c in cookies):
                try:
                    state["saved"] = core.save_cookies(cookies)
                except Exception:
                    state["saved"] = 0
                break
        try:
            window.destroy()
        except Exception:
            pass

    try:
        window = webview.create_window(
            "Kindle — ログイン / Sign in", LOGIN_URL, width=520, height=760)
        webview.start(harvest, window)
    except Exception:
        return 1
    return 0 if state["saved"] else 1


if __name__ == "__main__":
    raise SystemExit(run())
