"""Kindle cookie-status gating: an in-flight validity probe must not re-show
"接続OK" after the sign-in is cleared (login → Clear leaves it stuck otherwise).

These drive the real App methods on a bare instance (no Tk), with root.after
running callbacks synchronously and threads captured so we control when the
background probe "completes".
"""
import gui


class FakeVar:
    def __init__(self, value=""):
        self._v = value

    def set(self, value):
        self._v = value

    def get(self):
        return self._v


class FakeRoot:
    """root.after(0, fn, *args) runs fn immediately (single-threaded test)."""

    def after(self, delay, func=None, *args):
        if func is not None:
            func(*args)


class FakeThread:
    """Captures the worker instead of running it, so the test controls timing."""

    captured = []

    def __init__(self, target=None, args=(), daemon=None):
        self.target = target
        self.args = args

    def start(self):
        FakeThread.captured.append((self.target, self.args))

    @classmethod
    def run_all(cls):
        pending, cls.captured = cls.captured, []
        for target, args in pending:
            target(*args)


def _make_app(monkeypatch):
    app = gui.App.__new__(gui.App)
    app.root = FakeRoot()
    app._check_epoch = 0
    app.cookies_status = FakeVar("")
    app.cookies_valid = FakeVar("")
    app._validity_labels = []
    app._validity_color = gui.MUTED
    app._settings_win = None
    app._update_ready_state = lambda *a, **k: None
    FakeThread.captured = []
    monkeypatch.setattr(gui.threading, "Thread", FakeThread)
    monkeypatch.setattr(gui.core, "get_cookies_path", lambda: "cookies.txt")
    return app


def test_clear_discards_an_in_flight_probe_result(monkeypatch):
    app = _make_app(monkeypatch)

    # 1) Post-login probe starts while signed in (captured, not yet finished).
    monkeypatch.setattr(gui.core, "has_saved_cookies", lambda: True)
    monkeypatch.setattr(gui.core, "check_cookies", lambda *a, **k: True)
    app._check_cookies(silent=True)
    assert app.cookies_valid.get() == gui.t("checking")

    # 2) User clears the sign-in before the probe returns.
    monkeypatch.setattr(gui.core, "has_saved_cookies", lambda: False)
    app._refresh_cookie_status()
    assert app.cookies_valid.get() == ""

    # 3) The probe now finishes and would report "接続OK" — it must be discarded.
    FakeThread.run_all()
    assert app.cookies_valid.get() == ""


def test_current_probe_result_is_applied(monkeypatch):
    app = _make_app(monkeypatch)
    monkeypatch.setattr(gui.core, "has_saved_cookies", lambda: True)
    monkeypatch.setattr(gui.core, "check_cookies", lambda *a, **k: True)

    app._check_cookies(silent=True)
    FakeThread.run_all()  # completes with no intervening clear

    assert app.cookies_valid.get() == gui.t("conn_ok")
