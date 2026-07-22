#!/usr/bin/env python3
"""In-app Kindle login (Windows / macOS) — get cookies without cookies.txt.

Opens a real browser window via pywebview (WebView2 on Windows, WKWebView on
macOS) at the Amazon Kindle notebook page. The user signs in normally — 2FA /
CAPTCHA included, since it is a real browser engine — and once the Amazon auth
cookies appear we harvest them
and save them to the app's cookie store, the same place a cookies.txt import
writes. The rest of the sync pipeline (build_session → requests) is unchanged.

Run as a short-lived subprocess: gui.py re-invokes the app with --kindle-login,
so pywebview can own the process's main thread without fighting the Tk loop.
Exit code 0 = cookies saved, non-zero = cancelled / unavailable / failed.
"""
import time
from email.utils import parsedate_to_datetime

import kindle_notion as core

LOGIN_URL = "https://read.amazon.co.jp/notebook"
# Amazon sets an access-token cookie — "at-main" on .com, "at-acbjp" on .co.jp,
# and the like — only after a successful sign-in (password, OTP, or passkey). Its
# presence is the reliable "signed in" signal. NOTE: session-token / x-main are
# set earlier in the flow, so treating them as success closed the login window
# before the user had finished signing in — only the at-* access token counts.
AUTH_COOKIE_PREFIX = "at-"
POLL_SECONDS = 0.5
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

    Works on Windows (WebView2) and macOS (WKWebView) via pywebview. Returns 0 if
    cookies were saved, else non-zero: 3 = no pywebview backend available, 1 = the
    user cancelled or it timed out. See the module docstring for the overall flow.
    """
    try:
        import webview
    except Exception:
        return 3

    state = {"saved": 0}

    def try_harvest(window):
        """Save the Kindle cookies if the browser session is now signed in.

        Returns True once cookies are saved. Skips while still on the Amazon
        sign-in flow (/ap/ or signin URLs). Any sign-in method — password, OTP or
        passkey / Windows Hello — ends on the notebook page, where the auth
        cookies become readable, so this works regardless of how the user logs in.
        """
        if state["saved"]:
            return True
        try:
            url = window.get_current_url() or ""
            if "/ap/" in url or "signin" in url:
                return False  # still signing in — wait
            cookies = _flatten(window.get_cookies())
        except Exception:
            return False
        if any((c.get("name") or "").startswith(AUTH_COOKIE_PREFIX) for c in cookies):
            try:
                state["saved"] = core.save_cookies(cookies)
            except Exception:
                state["saved"] = 0
            return bool(state["saved"])
        return False

    def close(window):
        try:
            window.destroy()
        except Exception:
            pass

    def harvest(window):
        # Backstop poll. The loaded/closing events below catch the sign-in the
        # instant it happens, so success no longer depends on the window staying
        # open long enough for the next poll tick.
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while time.monotonic() < deadline and not state["saved"]:
            time.sleep(POLL_SECONDS)
            if try_harvest(window):
                break
        close(window)

    try:
        window = webview.create_window(
            "Kindle — ログイン / Sign in", LOGIN_URL, width=520, height=760)

        def _on_loaded(*a):
            # Grab the cookies as soon as a post-login page finishes loading and
            # close the window immediately — covers password, OTP and passkey.
            if try_harvest(window):
                close(window)

        def _on_closing(*a):
            # If the window is closed right after a successful sign-in (e.g. the
            # user closes it), make one last attempt to capture the session.
            try_harvest(window)

        try:
            window.events.loaded += _on_loaded
            window.events.closing += _on_closing
        except Exception:
            pass

        webview.start(harvest, window)
    except Exception:
        return 1
    return 0 if state["saved"] else 1


if __name__ == "__main__":
    raise SystemExit(run())
