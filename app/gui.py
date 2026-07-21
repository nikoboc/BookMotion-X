#!/usr/bin/env python3
"""CustomTkinter GUI for the Kindle → Notion app (Level 3 packaged .app entry point).

Enter your Notion token / parent page / cookies right in the window — no file
editing. Values are saved to config.json (Application Support when packaged).
"""
import subprocess
import sys
import threading
import webbrowser
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

import kindle_notion as core

# ---- Palette: cream base + gold accent, tuned to the app icon ----------------
# Every value is a (light, dark) pair. Base/sub stay warm (cream / dark brown +
# sage / amber); the accent is the icon's gold. On the gold ACCENT fills the
# label is white in light mode and near-black in dark mode (per spec). SUB fills
# are a mid-tone in both modes, so their label (ON_SUB) is dark in both. All
# pairs were checked to clear WCAG AA on the surface they sit on.
BASE   = ("#efe5cb", "#462e2e")  # window + card background   (ベース)
SUB    = ("#bfc9bd", "#ad722f")  # secondary fills: card borders, 2nd-ary buttons, progress track (サブ)
ACCENT = ("#9A6B00", "#F5B301")  # gold — primary actions, checkboxes, progress fill, selected (アクセント)

TEXT      = ("#3a2b23", "#efe5cb")  # primary text: dark brown on light / cream on dark
MUTED     = ("#7c6a58", "#cbb48f")  # secondary / hint text
ON_ACCENT = ("#FFFFFF", "#241C00")  # text + checkmark on a gold ACCENT fill (white / near-black)
ON_SUB    = "#241C00"               # text on a SUB (sage/amber) fill — dark in both modes

ACCENT_HOVER = ("#7E5700", "#E0A80D")  # hover / pressed accent fill
SUB_HOVER    = ("#adb8ab", "#96631f")  # hover / pressed secondary fill
ACCENT_LINK  = ("#8A6100", "#F5B301")  # gold link text over the window / card bg

OK_COLOR  = ("#15803D", "#22C55E")  # green — cookies still valid   (semantic, kept)
BAD_COLOR = ("#DC2626", "#F87171")  # red   — expired / re-import    (semantic, kept)


def _apply_palette():
    """Push the palette above into CustomTkinter's global theme so every widget
    adopts it by default — no need to color each label/frame by hand.

    Call once, after set_default_color_theme() (which loads the theme dict) and
    before any widget is built. Written defensively: a color key that a given
    CustomTkinter version doesn't have is skipped, never raised.
    """
    theme = ctk.ThemeManager.theme

    def put(widget, **fields):
        block = theme.get(widget)
        if not isinstance(block, dict):
            return
        for name, value in fields.items():
            block[name] = list(value) if isinstance(value, tuple) else value

    put("CTk", fg_color=BASE)
    put("CTkToplevel", fg_color=BASE)
    put("CTkFrame", fg_color=BASE, top_fg_color=BASE, border_color=SUB)
    put("CTkScrollableFrame", label_fg_color=BASE)
    put("CTkLabel", text_color=TEXT)
    put("CTkButton", fg_color=ACCENT, hover_color=ACCENT_HOVER,
        text_color=ON_ACCENT, border_color=SUB)
    put("CTkEntry", fg_color=BASE, border_color=SUB, text_color=TEXT)
    put("CTkCheckBox", fg_color=ACCENT, hover_color=ACCENT_HOVER,
        checkmark_color=ON_ACCENT, border_color=SUB, text_color=TEXT)
    put("CTkOptionMenu", fg_color=ACCENT, button_color=ACCENT_HOVER,
        button_hover_color=ACCENT_HOVER, text_color=ON_ACCENT)
    put("DropdownMenu", fg_color=BASE, hover_color=SUB, text_color=TEXT)
    put("CTkProgressBar", fg_color=SUB, progress_color=ACCENT)
    put("CTkTextbox", fg_color=BASE, text_color=TEXT, border_color=SUB)
    put("CTkScrollbar", button_color=SUB, button_hover_color=SUB_HOVER)

APPEARANCE = {"システム": "system", "ライト": "light", "ダーク": "dark"}

# External help links opened from the help window (取得方法).
NOTION_INTEGRATIONS_URL = "https://www.notion.so/my-integrations"
AMAZON_NOTEBOOK_URL = "https://read.amazon.co.jp/notebook"
COOKIES_EXT_SEARCH_URL = "https://chromewebstore.google.com/search/get%20cookies.txt"


def _fonts_dir() -> Path:
    """Directory holding the bundled .otf/.ttf files, in dev and when frozen.

    When packaged with PyInstaller (`--add-data "...:fonts"`), the files land
    under sys._MEIPASS/fonts; in dev they sit next to this script in app/fonts/.
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "fonts"
    return Path(__file__).resolve().parent / "fonts"


def _icons_dir() -> Path:
    """Directory holding the bundled brand logos (kindle.png / notion.png).

    Same frozen/dev resolution as _fonts_dir: PyInstaller drops them under
    sys._MEIPASS/icons (see the build scripts' `--add-data ...:icons`); in dev
    they sit in app/icons/ next to this script.
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "icons"
    return Path(__file__).resolve().parent / "icons"


def _register_font_file(path: str) -> bool:
    """Load one font file into THIS process only (no system-wide install).

    Windows uses AddFontResourceEx with FR_PRIVATE; macOS uses CoreText's
    CTFontManagerRegisterFontsForURL at process scope. Best-effort: any failure
    returns False and the caller falls back to a system font.
    """
    try:
        if sys.platform.startswith("win"):
            import ctypes

            FR_PRIVATE = 0x10
            added = ctypes.windll.gdi32.AddFontResourceExW(
                ctypes.c_wchar_p(path), FR_PRIVATE, 0)
            return added > 0
        if sys.platform == "darwin":
            import ctypes
            import ctypes.util

            ct = ctypes.CDLL(ctypes.util.find_library("CoreText"))
            cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
            cf.CFStringCreateWithCString.restype = ctypes.c_void_p
            cf.CFStringCreateWithCString.argtypes = [
                ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
            cf.CFURLCreateWithFileSystemPath.restype = ctypes.c_void_p
            cf.CFURLCreateWithFileSystemPath.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long, ctypes.c_bool]
            cf.CFRelease.argtypes = [ctypes.c_void_p]
            ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
            ct.CTFontManagerRegisterFontsForURL.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
            kCFStringEncodingUTF8 = 0x08000100
            kCFURLPOSIXPathStyle = 0
            kCTFontManagerScopeProcess = 1
            s = cf.CFStringCreateWithCString(
                None, path.encode("utf-8"), kCFStringEncodingUTF8)
            url = cf.CFURLCreateWithFileSystemPath(
                None, s, kCFURLPOSIXPathStyle, False)
            ok = ct.CTFontManagerRegisterFontsForURL(
                url, kCTFontManagerScopeProcess, None)
            cf.CFRelease(url)
            cf.CFRelease(s)
            return bool(ok)
    except Exception:
        return False
    return False  # Linux: rely on a system-installed Noto Sans CJK JP instead.


def register_bundled_fonts() -> None:
    """Register the bundled Noto Sans JP so Windows and macOS render identically.

    Must run BEFORE the Tk root is created so the new families are visible to
    Tk's font enumerator. Best-effort: if the files are missing or the OS call
    fails, _resolve_fonts falls back to the best per-OS system font.
    """
    d = _fonts_dir()
    if not d.is_dir():
        return
    for f in sorted(d.iterdir()):
        if f.suffix.lower() in (".otf", ".ttf"):
            _register_font_file(str(f))


def _resolve_fonts(root):
    """Pick UI font families, preferring the bundled Noto Sans JP.

    The bundled font is registered at startup (register_bundled_fonts), so on
    both Windows and macOS "Noto Sans JP" is present and the app renders alike.
    If it isn't available — running from source without the font files, or the
    OS registration failed — fall back to the best per-OS system font.

    Returns (regular_family, medium_family). medium_family == regular_family
    when no distinct medium-weight face exists, in which case the caller falls
    back to a bold weight for emphasis.
    """
    fams = set(tkfont.families(root))
    if "Noto Sans JP" in fams:
        med = "Noto Sans JP Medium" if "Noto Sans JP Medium" in fams else "Noto Sans JP"
        return "Noto Sans JP", med
    if sys.platform == "darwin":
        # Match the OS: reuse whatever family Tk's default (system) font resolves to.
        try:
            base = tkfont.nametofont("TkDefaultFont").actual("family")
        except Exception:
            base = "Helvetica Neue"
        return base, base
    if sys.platform.startswith("win"):
        reg = next((f for f in ("Yu Gothic UI", "Meiryo UI", "Segoe UI")
                    if f in fams), "Segoe UI")
        return reg, reg
    reg = next((f for f in ("Noto Sans CJK JP", "Noto Sans")
                if f in fams), "TkDefaultFont")
    return reg, reg


def _resolve_mono(root):
    """Monospace family for the token / URL / DB-ID fields.

    Prefer the bundled Noto Sans Mono (registered at startup) so those fields
    read identically on Windows and macOS; otherwise fall back to a per-OS
    monospace, then Tk's built-in fixed font.
    """
    fams = set(tkfont.families(root))
    if "Noto Sans Mono" in fams:
        return "Noto Sans Mono"
    for f in ("Consolas", "SF Mono", "Menlo", "DejaVu Sans Mono", "Courier New"):
        if f in fams:
            return f
    try:
        return tkfont.nametofont("TkFixedFont").actual("family")
    except Exception:
        return "Courier"


def desktop_notify(title: str, message: str) -> None:
    """Show a native desktop notification. Best-effort — never raises.

    macOS uses the built-in `osascript` (no dependency); Windows uses the
    lightweight `winotify` package (Windows-only, see requirements.txt). On any
    other platform, or if the tool/library is unavailable, it's a silent no-op.
    Safe to call from a worker thread — it touches no Tk state.
    """
    try:
        if sys.platform == "darwin":
            def esc(s):
                return s.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{esc(message)}" with title "{esc(title)}"'],
                check=False, capture_output=True, timeout=5)
        elif sys.platform.startswith("win"):
            from winotify import Notification
            Notification(app_id="Booklight", title=title, msg=message).show()
    except Exception:
        pass


def _colorref(pair, dark):
    """(#RRGGBB light, #RRGGBB dark) -> Win32 COLORREF (0x00BBGGRR) for the mode."""
    h = (pair[1] if dark else pair[0]).lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)


def _style_titlebar(window, color_mode):
    """Paint a window's title bar to match BASE, with TEXT-colored caption text.

    Uses the Windows 11 DWM caption-color attributes (need build 22000+); older
    Windows silently keeps just the immersive dark/light fallback. No-op off
    Windows or on any failure — purely cosmetic.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        dark = str(color_mode).lower() == "dark"
        hwnd = ctypes.windll.user32.GetAncestor(window.winfo_id(), 2)  # GA_ROOT
        dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
        flag = ctypes.c_int(1 if dark else 0)
        if dwm(hwnd, 20, ctypes.byref(flag), ctypes.sizeof(flag)) != 0:
            dwm(hwnd, 19, ctypes.byref(flag), ctypes.sizeof(flag))  # pre-20H1
        cap = ctypes.c_int(_colorref(BASE, dark))
        dwm(hwnd, 35, ctypes.byref(cap), ctypes.sizeof(cap))  # DWMWA_CAPTION_COLOR
        txt = ctypes.c_int(_colorref(TEXT, dark))
        dwm(hwnd, 36, ctypes.byref(txt), ctypes.sizeof(txt))  # DWMWA_TEXT_COLOR
        SWP = 0x1 | 0x2 | 0x4 | 0x20  # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP)
    except Exception:
        pass


class _TitlebarMixin:
    """Give a CTk / CTkToplevel a title bar painted to match BASE.

    Overrides CustomTkinter's `_windows_set_titlebar_color`, which withdraws +
    re-deiconifies to force a repaint (that withdraw could leave a dialog hidden
    when the theme is switched from its own dropdown). We repaint in place and
    re-apply once the current update settles so the caption color reliably sticks.
    CustomTkinter calls this on creation and on every appearance-mode change, so
    light / dark and "system" flips are covered automatically.
    """

    def _windows_set_titlebar_color(self, color_mode):
        if not sys.platform.startswith("win"):
            return
        self._tb_mode = color_mode
        _style_titlebar(self, color_mode)
        try:  # re-apply after CTk's update settles so the repaint sticks
            self.after(
                50, lambda: _style_titlebar(self, getattr(self, "_tb_mode", color_mode)))
        except Exception:
            pass


class _AppRoot(_TitlebarMixin, ctk.CTk):
    """Main window — a CTk root whose title bar tracks BASE."""


class SettingsDialog(_TitlebarMixin, ctk.CTkToplevel):
    """Modal dialog for the rarely-changed Notion settings (token / URL / DB ID).

    Edits the App's shared StringVars directly; "保存して閉じる" persists via
    App.save() and re-evaluates the main window's ready state.
    """

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        # Snapshot the current (saved) values so cancel can discard edits and
        # nothing persists until "保存して閉じる".
        self._orig = {
            "token": app.token.get(),
            "parent": app.parent.get(),
            "dbid": app.dbid.get(),
            "notify": app.notify_on_complete.get(),
            "appearance": app.appearance_mode.get(),
        }
        self.title("設定")
        self.geometry("560x780")
        self.minsize(480, 660)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self.after(10, self._raise_dialog)  # bring to front once viewable

    def _raise_dialog(self):
        # NOTE: no grab_set() — a modal grab deadlocks with the CTkOptionMenu
        # dropdown (tk_popup) on Windows and freezes the app. Keep it non-modal;
        # `transient` still keeps it above the main window.
        self.lift()
        self.focus_force()

    def _build(self):
        app = self.app
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=20, pady=18)
        outer.columnconfigure(0, weight=1)

        # Notion 接続情報 sits below Kindle 接続情報 (row 0); see c2 below.
        card = ctk.CTkFrame(outer, corner_radius=12, border_width=1)
        card.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        card.columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text="Notion 接続情報", font=app.f_section, anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(14, 4))

        ctk.CTkLabel(card, text="Notion トークン", font=app.f_body, anchor="w").grid(
            row=1, column=0, sticky="w", padx=(16, 8), pady=6)
        self.token_entry = ctk.CTkEntry(
            card, textvariable=app.token, font=app.f_mono,
            show="" if app.show_token.get() else "•")
        self.token_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=6)
        ctk.CTkCheckBox(card, text="表示", variable=app.show_token, width=52,
                        command=self._toggle_token, font=app.f_small,
                        fg_color=ACCENT, hover_color=ACCENT_HOVER,
                        checkmark_color=ON_ACCENT).grid(
            row=1, column=2, sticky="w", padx=(0, 16), pady=6)

        ctk.CTkLabel(card, text="親ページ URL", font=app.f_body, anchor="w").grid(
            row=2, column=0, sticky="w", padx=(16, 8), pady=6)
        ctk.CTkEntry(card, textvariable=app.parent, font=app.f_mono).grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=(0, 16), pady=6)

        ctk.CTkLabel(card, text="DB ID（任意）", font=app.f_body, anchor="w").grid(
            row=3, column=0, sticky="w", padx=(16, 8), pady=6)
        ctk.CTkEntry(card, textvariable=app.dbid, font=app.f_mono).grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=(0, 16), pady=(6, 2))
        ctk.CTkLabel(
            card, font=app.f_small, text_color=MUTED, anchor="w", justify="left",
            wraplength=380,
            text="空欄のまま同期すると、新しいデータベースを自動作成します。",
        ).grid(row=4, column=1, columnspan=2, sticky="w", padx=(0, 16), pady=(0, 16))

        # --- card: Kindle 接続情報 (cookie management) — top of the dialog ---
        c2 = ctk.CTkFrame(outer, corner_radius=12, border_width=1)
        c2.grid(row=0, column=0, sticky="ew")
        c2.columnconfigure(0, weight=1)
        ctk.CTkLabel(c2, text="Kindle 接続情報", font=app.f_section, anchor="w").grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(c2, text="cookies.txt", font=app.f_body, anchor="w").grid(
            row=1, column=0, sticky="w", padx=16, pady=(0, 4))
        ff = ctk.CTkFrame(c2, fg_color="transparent")
        ff.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 14))
        ff.columnconfigure(0, weight=1)
        ctk.CTkLabel(ff, textvariable=app.cookies_status, font=app.f_small,
                     text_color=MUTED, anchor="w").grid(row=0, column=0, sticky="w")
        self.cookies_check_btn = app._ghost(ff, "接続確認", app._check_cookies, width=88)
        self.cookies_check_btn.grid(row=0, column=1, padx=(8, 0))
        app._ghost(ff, "取り込み…", app._import_cookies, width=104).grid(
            row=0, column=2, padx=(8, 0))
        self.cookies_clear_btn = app._ghost(ff, "クリア", app._clear_cookies, width=72)
        self.cookies_clear_btn.grid(row=0, column=3, padx=(8, 0))
        self.valid_lbl = ctk.CTkLabel(ff, textvariable=app.cookies_valid,
                                      font=app.f_small, text_color=MUTED, anchor="w")
        self.valid_lbl.grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
        app._register_validity_label(self.valid_lbl)
        self.refresh_cookie_buttons(core.has_saved_cookies())

        # --- card: 外観 (theme) ---
        c3 = ctk.CTkFrame(outer, corner_radius=12, border_width=1)
        c3.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        c3.columnconfigure(1, weight=1)
        ctk.CTkLabel(c3, text="外観", font=app.f_section, anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(c3, text="テーマ", font=app.f_body, anchor="w").grid(
            row=1, column=0, sticky="w", padx=(16, 8), pady=(0, 14))
        ctk.CTkOptionMenu(
            c3, values=list(APPEARANCE), variable=app.appearance_mode, width=140,
            font=app.f_small, dropdown_font=app.f_small,
            command=app._set_appearance, fg_color=ACCENT,
            button_color=ACCENT_HOVER, button_hover_color=ACCENT_HOVER,
            text_color=ON_ACCENT).grid(
            row=1, column=1, sticky="w", padx=(0, 16), pady=(0, 14))

        # --- card: 通知 ---
        c4 = ctk.CTkFrame(outer, corner_radius=12, border_width=1)
        c4.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        c4.columnconfigure(0, weight=1)
        ctk.CTkLabel(c4, text="通知", font=app.f_section, anchor="w").grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 4))
        ctk.CTkCheckBox(c4, text="同期完了時にデスクトップ通知を出す",
                        variable=app.notify_on_complete, font=app.f_body,
                        fg_color=ACCENT, hover_color=ACCENT_HOVER,
                        checkmark_color=ON_ACCENT).grid(
            row=1, column=0, sticky="w", padx=16, pady=(0, 14))

        br = ctk.CTkFrame(outer, fg_color="transparent")
        br.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        br.columnconfigure(0, weight=1)
        help_btn = app._ghost(br, "❓ 取得方法", self._open_help)
        help_btn.configure(height=38)
        help_btn.grid(row=0, column=0, sticky="w")
        save_btn = app._accent(br, "保存して閉じる", self._save_close)
        save_btn.configure(height=38)
        save_btn.grid(row=0, column=1, sticky="e")

    def refresh_cookie_buttons(self, saved):
        """Enable Clear / 接続確認 only when cookies are actually saved."""
        st = "normal" if saved else "disabled"
        for b in (self.cookies_clear_btn, self.cookies_check_btn):
            try:
                b.configure(state=st)
            except Exception:
                pass

    def _toggle_token(self):
        self.token_entry.configure(show="" if self.app.show_token.get() else "•")

    def _save_close(self):
        # The only place settings are persisted.
        self.app.save()
        self.app._update_ready_state()
        self.app._check_notion()  # refresh the main-window Notion status
        self._teardown()

    def _close(self):
        # Cancel (X / window close): discard unsaved edits by restoring the
        # values captured when the dialog opened, including the live theme.
        a, o = self.app, self._orig
        a.token.set(o["token"])
        a.parent.set(o["parent"])
        a.dbid.set(o["dbid"])
        a.notify_on_complete.set(o["notify"])
        revert_theme = a.appearance_mode.get() != o["appearance"]
        self._teardown()
        if revert_theme:
            # After teardown so only the main window recolors (the dialog is gone).
            a._set_appearance(o["appearance"])

    def _teardown(self):
        self.app._unregister_validity_label(self.valid_lbl)
        self.app._settings_win = None
        self.destroy()

    def _open_help(self):
        self.app.open_help(self)


class HelpDialog(_TitlebarMixin, ctk.CTkToplevel):
    """Read-only "how to obtain" window: token / parent URL / DB ID / cookies.txt.

    Opened from the settings dialog's「❓ 取得方法」button. Values are still
    entered in the settings dialog — this window only explains where each value
    comes from and opens the relevant external pages in the default browser.
    """

    def __init__(self, app, parent=None):
        super().__init__(parent or app.root)
        self.app = app
        self.title("取得方法 / ヘルプ")
        self.geometry("620x720")
        self.minsize(520, 480)
        self.transient(parent or app.root)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self.after(10, self._raise_dialog)

    def _raise_dialog(self):
        self.lift()
        self.focus_force()

    def _close(self):
        self.app._help_win = None
        self.destroy()

    # -- content helpers -----------------------------------------------------
    def _section(self, parent, title):
        """A titled card; returns the inner frame to add steps/links/notes to."""
        card = ctk.CTkFrame(parent, corner_radius=12, border_width=1)
        card.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(card, text=title, font=self.app.f_section, anchor="w").pack(
            fill="x", padx=16, pady=(14, 6))
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=16, pady=(0, 14))
        return body

    def _step(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=self.app.f_body, anchor="w",
                     justify="left", wraplength=500).pack(fill="x", pady=3)

    def _note(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=self.app.f_small, text_color=MUTED,
                     anchor="w", justify="left", wraplength=500).pack(
            fill="x", pady=(6, 0))

    def _link(self, parent, text, url):
        ctk.CTkButton(
            parent, text=text, font=self.app.f_small, anchor="w", height=28,
            fg_color="transparent", text_color=ACCENT_LINK,
            hover_color=("gray90", "gray25"),
            command=lambda u=url: webbrowser.open(u)).pack(fill="x", pady=(4, 2))

    def _build(self):
        app = self.app
        wrap = ctk.CTkScrollableFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=16, pady=(16, 8))

        ctk.CTkLabel(
            wrap, font=app.f_small, text_color=MUTED, anchor="w", justify="left",
            wraplength=500,
            text=("同期には ① Notion トークン ② 親ページ URL ③（任意）DB ID "
                  "④ cookies.txt が必要です。入力は「⚙ 設定」で行います。")).pack(
            fill="x", pady=(0, 12))

        # ① Notion トークン
        b = self._section(wrap, "① Notion トークンの取得")
        self._step(b, "1. 下のリンクから「マイインテグレーション」を開きます。")
        self._link(b, "🔗 notion.so/my-integrations を開く", NOTION_INTEGRATIONS_URL)
        self._step(b, "2. 「新しいインテグレーション」を作成します（種類は内部/Internal）。")
        self._step(b, "3. 表示された「Internal Integration Token」（ntn_… または "
                      "secret_… で始まる文字列）をコピーします。")
        self._step(b, "4. 「⚙ 設定」の「Notion トークン」欄に貼り付けます。")
        self._note(b, "⚠ トークンを作っただけでは書き込めません。②の親ページに、この "
                      "インテグレーションを「連携」から追加してください（忘れると 404 エラー）。")

        # ② 親ページ URL
        b = self._section(wrap, "② 親ページ URL の取得と連携")
        self._step(b, "1. データベースを置きたい Notion のページを開きます"
                      "（新しい空ページを作ってもOK）。")
        self._link(b, "🔗 Notion を開く", "https://www.notion.so")
        self._step(b, "2. そのページの URL をコピーし、「⚙ 設定」の「親ページ URL」欄に"
                      "貼り付けます。")
        self._step(b, "3. ページ右上の「•••」→「連携（コネクト）」→ ①で作った"
                      "インテグレーションを追加します。")
        self._note(b, "この「連携」を忘れると、トークンが正しくても 404 で失敗します。")

        # ③ データベース ID
        b = self._section(wrap, "③ データベース ID（任意）")
        self._step(b, "空欄のまま同期すると、新しいデータベースを自動作成します。"
                      "通常は空欄でOKです。")
        self._step(b, "既存のデータベースに追記したい場合のみ、その DB を Notion の"
                      "ブラウザで開きます。")
        self._step(b, "URL「notion.so/…/xxxxxxxx?v=…」の xxxxxxxx（32 桁の英数字）が "
                      "DB ID です。これを「⚙ 設定」の「DB ID」欄に貼り付けます。")
        self._note(b, "最後のスラッシュの後ろ・「?v=」より前が DB ID です"
                      "（末尾のページ名部分は無視されます）。")

        # ④ cookies.txt
        b = self._section(wrap, "④ cookies.txt の取得")
        self._step(b, "1. ブラウザで read.amazon.co.jp にログインしておきます。")
        self._link(b, "🔗 read.amazon.co.jp/notebook を開く", AMAZON_NOTEBOOK_URL)
        self._step(b, "2. Cookie 書き出し用の拡張機能を入れます"
                      "（例:「Get cookies.txt LOCALLY」）。")
        self._link(b, "🔗 Chrome ウェブストアで「get cookies.txt」を検索",
                   COOKIES_EXT_SEARCH_URL)
        self._step(b, "3. read.amazon.co.jp を開いた状態で拡張機能を起動し、cookies.txt "
                      "をエクスポート（Export／Download）します。")
        self._step(b, "4. 「⚙ 設定」の「Kindle 接続情報」→「取り込み…」から、その "
                      "cookies.txt を選びます。")
        self._note(b, "取り込み後は元ファイル不要です。「✕ 期限切れ」と表示されたら、"
                      "ログインし直して cookies.txt を取り直し、もう一度「取り込み…」して"
                      "ください。")

        br = ctk.CTkFrame(self, fg_color="transparent")
        br.pack(fill="x", padx=16, pady=(0, 14))
        close = app._accent(br, "閉じる", self._close)
        close.configure(width=100, height=36)
        close.pack(side="right")


class App:
    def __init__(self, root: ctk.CTk):
        self.root = root
        root.title("Booklight")
        root.geometry("720x820")
        # Low min-height so the window can shrink to fit the collapsed log.
        root.minsize(640, 340)
        self._set_window_icon()
        cfg = core.load_config()
        self._indeterminate = False
        self._syncing = False
        self._notify_pref = True  # snapshot taken on the main thread at sync start
        self._expanded_h = 820    # logical height to restore when the log expands

        self.token = tk.StringVar(value=cfg.get("notion_token", ""))
        self.parent = tk.StringVar(value=cfg.get("notion_parent_page_id", ""))
        self.dbid = tk.StringVar(value=cfg.get("notion_database_id", ""))
        # Desktop-notification preference (settings dialog toggle); default on.
        self.notify_on_complete = tk.BooleanVar(
            value=bool(cfg.get("notify_on_complete", True)))
        # Theme choice lives in the settings dialog; persisted in config and
        # restored here so it survives a restart.
        saved_theme = cfg.get("appearance_mode", "システム")
        if saved_theme not in APPEARANCE:
            saved_theme = "システム"
        self.appearance_mode = tk.StringVar(value=saved_theme)
        ctk.set_appearance_mode(APPEARANCE[saved_theme])
        self.cookies_status = tk.StringVar(value="")
        self.cookies_valid = tk.StringVar(value="")
        # Notion connection status, shown on the right of the main window and
        # probed at startup like the cookies (left side).
        self.notion_setup = tk.StringVar(value="")
        self.notion_valid = tk.StringVar(value="")
        self._notion_valid_lbl = None
        self._settings_win = None
        self._help_win = None
        # Cookie validity is shown on the main screen AND (when open) the settings
        # dialog; both labels share the StringVars, and _set_validity recolors every
        # registered label. _validity_color remembers the latest color for labels
        # that register later (e.g. the dialog's).
        self._validity_labels = []
        self._validity_color = MUTED

        # One-time migration: adopt a previously-referenced cookies.txt into the
        # app data dir so upgrading users keep working without re-importing.
        legacy = (cfg.get("cookies_file") or "").strip()
        if legacy and not core.has_saved_cookies():
            try:
                core.import_cookies_file(legacy)
            except Exception:
                pass
        self.show_token = tk.BooleanVar(value=False)

        self._setup_fonts()
        self._build()
        # Guard against quitting mid-sync (accidental close).
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- fonts ---------------------------------------------------------------
    def _setup_fonts(self):
        reg, med = _resolve_fonts(self.root)
        self.f_title = ctk.CTkFont(family=reg, size=22, weight="bold")
        self.f_sub = ctk.CTkFont(family=reg, size=13)
        self.f_body = ctk.CTkFont(family=reg, size=13)
        self.f_small = ctk.CTkFont(family=reg, size=12)
        self.f_log = ctk.CTkFont(family=reg, size=12)
        # Monospace for token / URL / DB-ID — easier to read IDs and spot typos.
        self.f_mono = ctk.CTkFont(family=_resolve_mono(self.root), size=13)
        # Prefer a true Medium face for headings/buttons; else fall back to bold.
        self.f_section = (ctk.CTkFont(family=med, size=14) if med != reg
                          else ctk.CTkFont(family=reg, size=14, weight="bold"))
        self.f_btn = (ctk.CTkFont(family=med, size=13) if med != reg
                      else ctk.CTkFont(family=reg, size=13, weight="bold"))

    # -- reusable widgets ----------------------------------------------------
    def _ghost(self, parent, text, command, width=0):
        # Secondary button: a tonal SUB fill with dark text (SUB is a mid-tone in
        # both modes, so dark text stays legible either way).
        kw = {"width": width} if width else {}
        return ctk.CTkButton(
            parent, text=text, command=command, font=self.f_btn,
            fg_color=SUB, hover_color=SUB_HOVER, text_color=ON_SUB, **kw,
        )

    def _accent(self, parent, text, command):
        # Primary button. The light-mode accent is a pale powder-blue that barely
        # separates from the cream page, so a same-hue border gives it an edge.
        return ctk.CTkButton(
            parent, text=text, command=command, font=self.f_btn,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=ON_ACCENT,
            border_width=1, border_color=ACCENT_HOVER,
        )

    def _label(self, parent, text, row):
        ctk.CTkLabel(parent, text=text, font=self.f_body, anchor="w").grid(
            row=row, column=0, sticky="w", padx=(16, 8), pady=6)

    def _brand_icon(self, filename, size=(22, 22)):
        """Load a bundled brand logo (Kindle / Notion) as a CTkImage, or None.

        Best-effort like the fonts: a missing file or load error just returns
        None and the caller falls back to an emoji heading. The same raster
        serves both themes — each logo carries its own background.
        """
        try:
            from PIL import Image

            p = _icons_dir() / filename
            if not p.is_file():
                return None
            img = Image.open(p).convert("RGBA")
            return ctk.CTkImage(light_image=img, dark_image=img, size=size)
        except Exception:
            return None

    def _app_icon(self, size=(40, 40)):
        """The app icon (book badge) as a round CTkImage for the header title.

        appicon.png is a square with a dark vignette in the corners; we mask it
        to a circle so only the cream badge shows — clean on the cream (light)
        and dark-brown (dark) backgrounds alike. Best-effort: returns None on any
        failure, and the caller then shows the title text with no icon.
        """
        try:
            from PIL import Image, ImageDraw

            p = _icons_dir() / "appicon.png"
            if not p.is_file():
                return None
            img = Image.open(p).convert("RGBA")
            w, h = img.size
            mask = Image.new("L", (w, h), 0)
            inset = round(min(w, h) * 0.10)  # crop past the dark ring around the badge
            ImageDraw.Draw(mask).ellipse((inset, inset, w - inset, h - inset), fill=255)
            img.putalpha(mask)
            return ctk.CTkImage(light_image=img, dark_image=img, size=size)
        except Exception:
            return None

    def _set_window_icon(self):
        """Best-effort: show the app icon in the title bar / taskbar at runtime.

        The packaged exe/.app already carries the icon via PyInstaller --icon;
        this makes the running *window* match too (notably when run from source).
        On Windows, iconbitmap only sets a small icon (the taskbar then upscales
        it), so we also push crisp big/small HICONs via WM_SETICON. Other
        platforms fall back to a PhotoImage. Any failure is a silent no-op.
        """
        d = _icons_dir()
        try:
            if sys.platform.startswith("win"):
                ico = d / "appicon.ico"
                if ico.is_file():
                    self.root.iconbitmap(default=str(ico))  # child dialogs inherit it
                    self._set_win_taskbar_icon(str(ico))
                    return
            png = d / "appicon.png"
            if png.is_file():
                self._win_icon = tk.PhotoImage(file=str(png))
                self.root.iconphoto(True, self._win_icon)
        except Exception:
            pass

    def _set_win_taskbar_icon(self, ico_path):
        """Give the window a crisp large icon for the taskbar / Alt-Tab.

        Tk's iconbitmap only sets a small class icon, which the taskbar then
        upscales (very blurry on hi-DPI). The taskbar reads the window's *class*
        icon (GCLP_HICON), so we replace it — and the WM_SETICON icons — with real
        256/32 px frames loaded from the .ico. Re-asserted after the window is
        mapped in case Tk re-sets its own. argtypes are explicit so the 64-bit
        HICON handles aren't truncated.
        """
        import ctypes

        u = ctypes.windll.user32
        u.LoadImageW.restype = ctypes.c_void_p
        u.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        u.SendMessageW.restype = ctypes.c_void_p
        u.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                   ctypes.c_void_p, ctypes.c_void_p]
        u.SetClassLongPtrW.restype = ctypes.c_void_p
        u.SetClassLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        u.GetAncestor.restype = ctypes.c_void_p
        u.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]

        IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x00000010, 0x0080
        ICON_SMALL, ICON_BIG = 0, 1
        GCLP_HICON, GCLP_HICONSM = -14, -34
        self._hicon_small = u.LoadImageW(None, ico_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        self._hicon_big = u.LoadImageW(None, ico_path, IMAGE_ICON, 256, 256, LR_LOADFROMFILE)

        def apply():
            hwnd = u.GetAncestor(self.root.winfo_id(), 2)  # GA_ROOT (top-level frame)
            if self._hicon_small:
                u.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, self._hicon_small)
                u.SetClassLongPtrW(hwnd, GCLP_HICONSM, self._hicon_small)
            if self._hicon_big:
                u.SendMessageW(hwnd, WM_SETICON, ICON_BIG, self._hicon_big)
                u.SetClassLongPtrW(hwnd, GCLP_HICON, self._hicon_big)  # taskbar reads this

        apply()
        # Re-assert after the window is realized/mapped so Tk can't override it.
        self.root.after(200, apply)

    def _build(self):
        self.outer = ctk.CTkFrame(self.root, fg_color="transparent")
        self.outer.pack(fill="both", expand=True, padx=20, pady=18)
        self.outer.columnconfigure(0, weight=1)
        # Row 5 (log) gains weight only when the log is expanded; collapsed by
        # default, so the extra space sits at the bottom until the user opens it.
        self.outer.rowconfigure(5, weight=0)

        # --- header ---
        hdr = ctk.CTkFrame(self.outer, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        hdr.columnconfigure(0, weight=1)
        titles = ctk.CTkFrame(hdr, fg_color="transparent")
        titles.grid(row=0, column=0, sticky="w")
        # App icon (left) + one-line description (right). The app name lives in
        # the title bar now, so the header carries no title text — just the icon.
        self._header_icon = self._app_icon(size=(40, 40))
        if self._header_icon is not None:
            ctk.CTkLabel(titles, text="", image=self._header_icon).pack(
                side="left", padx=(0, 12))
        ctk.CTkLabel(titles, text="Kindle のハイライトを Notion に同期します",
                     font=self.f_sub, text_color=MUTED, anchor="w").pack(side="left")

        # --- settings-incomplete banner (row 1); hidden once token + URL are set ---
        self.warn = ctk.CTkLabel(
            self.outer, font=self.f_small, text_color=BAD_COLOR, anchor="w",
            text="⚠ トークンと親ページ URL が未設定です。「⚙ 設定」から入力してください。")
        self.warn.grid(row=1, column=0, sticky="w", pady=(0, 10))

        # --- card: 接続状態 — Kindle (left) / Notion (right), both probed at
        # startup. Read-only; the actual settings live in the「⚙ 設定」dialog. ---
        sc = ctk.CTkFrame(self.outer, corner_radius=12, border_width=1)
        sc.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        sc.columnconfigure(0, weight=1, uniform="status")
        sc.columnconfigure(1, weight=1, uniform="status")

        # Real brand logos (fall back to an emoji if the files are missing).
        self._icon_kindle = self._brand_icon("kindle.png")
        self._icon_notion = self._brand_icon("notion.png")

        # left: Kindle (cookie import + login validity)
        kc = ctk.CTkFrame(sc, fg_color="transparent")
        kc.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=14)
        ctk.CTkLabel(
            kc, image=self._icon_kindle, compound="left",
            text="  Kindle" if self._icon_kindle else "📚 Kindle",
            font=self.f_section, anchor="w").pack(anchor="w")
        ctk.CTkLabel(kc, textvariable=self.cookies_status, font=self.f_small,
                     text_color=MUTED, anchor="w", justify="left",
                     wraplength=280).pack(anchor="w", pady=(4, 0))
        klbl = ctk.CTkLabel(kc, textvariable=self.cookies_valid, font=self.f_small,
                            text_color=MUTED, anchor="w", justify="left",
                            wraplength=280)
        klbl.pack(anchor="w", pady=(2, 0))
        self._register_validity_label(klbl)

        # right: Notion (token presence + connection validity)
        nc = ctk.CTkFrame(sc, fg_color="transparent")
        nc.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=14)
        ctk.CTkLabel(
            nc, image=self._icon_notion, compound="left",
            text="  Notion" if self._icon_notion else "🔗 Notion",
            font=self.f_section, anchor="w").pack(anchor="w")
        ctk.CTkLabel(nc, textvariable=self.notion_setup, font=self.f_small,
                     text_color=MUTED, anchor="w", justify="left",
                     wraplength=280).pack(anchor="w", pady=(4, 0))
        self._notion_valid_lbl = ctk.CTkLabel(
            nc, textvariable=self.notion_valid, font=self.f_small,
            text_color=MUTED, anchor="w", justify="left", wraplength=280)
        self._notion_valid_lbl.pack(anchor="w", pady=(2, 0))

        # --- action row ---
        ar = ctk.CTkFrame(self.outer, fg_color="transparent")
        ar.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        ar.columnconfigure(1, weight=1)
        self._ghost(ar, "⚙ 設定", self.open_settings, width=120).grid(
            row=0, column=0, sticky="w")
        self.sync_btn = self._accent(ar, "Notion へ同期", self.sync)
        self.sync_btn.configure(width=168, height=40)
        self.sync_btn.grid(row=0, column=2, sticky="e")

        # --- progress ---
        pf = ctk.CTkFrame(self.outer, fg_color="transparent")
        pf.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        pf.columnconfigure(0, weight=1)
        self.pbar = ctk.CTkProgressBar(pf, fg_color=SUB, progress_color=ACCENT)
        self.pbar.grid(row=0, column=0, sticky="ew")
        self.pbar.set(0)
        self.status = ctk.CTkLabel(pf, text="", font=self.f_small, text_color=MUTED,
                                   anchor="w")
        self.status.grid(row=1, column=0, sticky="w", pady=(6, 0))

        # --- log card (collapsible like <details>; collapsed by default) ---
        lc = ctk.CTkFrame(self.outer, corner_radius=12, border_width=1)
        lc.grid(row=5, column=0, sticky="nsew", pady=(0, 12))
        lc.columnconfigure(0, weight=1)
        lc.rowconfigure(1, weight=1)
        self._log_open = False
        self.log_toggle = ctk.CTkButton(
            lc, text="▸ ログ", command=self._toggle_log, font=self.f_section,
            anchor="w", height=32, corner_radius=8, fg_color="transparent",
            text_color=TEXT, hover_color=SUB)
        self.log_toggle.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.logbox = ctk.CTkTextbox(lc, font=self.f_log, corner_radius=8,
                                     border_width=1, wrap="word", height=220)
        # The textbox stays ungridded until expanded (default: collapsed).

        # Reflect the saved-cookie status on the Cookie row.
        self._refresh_cookie_status()
        # Notice an expired cookie without waiting for a full sync: probe once at
        # startup (in the background) if we have saved cookies.
        if core.has_saved_cookies():
            self.root.after(400, lambda: self._check_cookies(silent=True))
        # Same for Notion: show the token's presence immediately, then probe it.
        self.notion_setup.set("アカウント情報設定済み" if self.token.get().strip()
                              else "アカウント情報未設定")
        self.root.after(400, self._check_notion)

        # Gate the sync button on the required settings (token + parent URL),
        # live as they change in the settings dialog.
        self.token.trace_add("write", self._update_ready_state)
        self.parent.trace_add("write", self._update_ready_state)
        self._update_ready_state()

        # Start compact: the log is collapsed, so fit the window to its content.
        self._fit_height_to_content()

    # -- cookie status / validity -------------------------------------------
    def _register_validity_label(self, lbl):
        """Track a label that mirrors cookie validity, and color it to match."""
        self._validity_labels.append(lbl)
        try:
            lbl.configure(text_color=self._validity_color)
        except Exception:
            pass

    def _unregister_validity_label(self, lbl):
        if lbl in self._validity_labels:
            self._validity_labels.remove(lbl)

    def _refresh_cookie_status(self):
        """Show whether cookies are saved; refresh the dialog buttons if it's open."""
        saved = core.has_saved_cookies()
        if saved:
            self.cookies_status.set("アカウント情報設定済み")
        else:
            self.cookies_status.set("アカウント情報未設定")
            self._set_validity("", MUTED)  # no cookies → nothing to validate
        win = self._settings_win
        if win is not None and win.winfo_exists():
            win.refresh_cookie_buttons(saved)

    def _set_validity(self, text, color):
        """Update the shared validity text and recolor every registered label."""
        self.cookies_valid.set(text)
        self._validity_color = color
        for lbl in list(self._validity_labels):
            try:
                lbl.configure(text_color=color)
            except Exception:
                self._validity_labels.remove(lbl)

    def _set_check_btn_state(self, state):
        """Toggle the dialog's 接続確認 button if the dialog is currently open."""
        win = self._settings_win
        if win is not None and win.winfo_exists():
            try:
                win.cookies_check_btn.configure(state=state)
            except Exception:
                pass

    def _check_cookies(self, silent=False):
        """Probe Amazon to see whether the saved cookies still log us in.

        silent=True is used for the automatic startup check: it skips the
        "import first" dialog so a fresh install stays quiet.
        """
        if not core.has_saved_cookies():
            if not silent:
                messagebox.showinfo("接続確認", "先に cookies.txt を取り込んでください。")
            return
        self._set_check_btn_state("disabled")
        self._set_validity("確認中…", MUTED)
        threading.Thread(target=self._run_check, daemon=True).start()

    def _run_check(self):
        try:
            ok = core.check_cookies(str(core.get_cookies_path()), log=lambda *_: None)
            if ok:
                self.root.after(0, self._set_validity, "✓ 接続OK", OK_COLOR)
            else:
                self.root.after(
                    0, self._set_validity,
                    "✕ 期限切れ — 設定の「取り込み…」から新しい cookies.txt を入れ直してください",
                    BAD_COLOR)
        except Exception:
            self.root.after(
                0, self._set_validity,
                "接続を確認できませんでした（ネットワーク未接続など）", MUTED)
        finally:
            self.root.after(0, self._set_check_btn_state, "normal")

    # -- notion status / validity -------------------------------------------
    def _set_notion_validity(self, text, color):
        """Update the Notion status line and recolor it (main window, right side)."""
        self.notion_valid.set(text)
        try:
            self._notion_valid_lbl.configure(text_color=color)
        except Exception:
            pass

    def _check_notion(self):
        """Probe Notion to see whether the saved token is valid.

        Called at startup and after saving settings. Mirrors _check_cookies:
        the network call runs on a worker thread; results hop back to the UI.
        With no token there is nothing to probe, so just show 未設定.
        """
        token = self.token.get().strip()
        self.notion_setup.set("アカウント情報設定済み" if token else "アカウント情報未設定")
        if not token:
            self._set_notion_validity("", MUTED)
            return
        self._set_notion_validity("確認中…", MUTED)
        threading.Thread(
            target=self._run_notion_check, args=(token,), daemon=True).start()

    def _run_notion_check(self, token):
        try:
            ok = core.check_notion(token)
            if ok:
                self.root.after(0, self._set_notion_validity, "✓ 接続OK", OK_COLOR)
            else:
                self.root.after(
                    0, self._set_notion_validity,
                    "✕ トークンが無効です — 設定で確認してください", BAD_COLOR)
        except Exception:
            self.root.after(
                0, self._set_notion_validity,
                "接続を確認できませんでした（ネットワーク未接続など）", MUTED)

    def _set_appearance(self, choice):
        self.appearance_mode.set(choice)
        # Live preview only — persisted on "保存して閉じる", reverted on cancel.
        # SettingsDialog overrides the title-bar recolor so switching the theme
        # no longer withdraws the open dialog.
        ctk.set_appearance_mode(APPEARANCE.get(choice, "system"))

    def _settings_ready(self) -> bool:
        """Token and parent-page URL are the two required settings; DB ID is optional."""
        return bool(self.token.get().strip()) and bool(self.parent.get().strip())

    def _update_ready_state(self, *_):
        """Enable sync only when required settings are present; else show a banner."""
        if self._settings_ready():
            self.warn.grid_remove()
            self.sync_btn.configure(state="normal")
        else:
            self.warn.grid()
            self.sync_btn.configure(state="disabled")

    def open_settings(self):
        """Open, or re-show and focus, the settings dialog.

        Self-heals: if the existing dialog was withdrawn (e.g. by an appearance
        recolor) deiconify it; if it's in a bad state, recreate it.
        """
        win = self._settings_win
        if win is not None and win.winfo_exists():
            try:
                win.deiconify()  # recover it if it got withdrawn
                win.lift()
                win.focus_force()
                return
            except Exception:
                try:
                    win.destroy()
                except Exception:
                    pass
                self._settings_win = None
        self._settings_win = SettingsDialog(self)

    def open_help(self, parent=None):
        """Open, or re-show and focus, the help window (取得方法).

        Mirrors open_settings' self-healing: re-show a withdrawn window, and
        recreate one left in a bad state.
        """
        win = self._help_win
        if win is not None and win.winfo_exists():
            try:
                win.deiconify()
                win.lift()
                win.focus_force()
                return
            except Exception:
                try:
                    win.destroy()
                except Exception:
                    pass
                self._help_win = None
        self._help_win = HelpDialog(self, parent)

    def _import_cookies(self):
        """Read a cookies.txt and store it as app data; the original is then unneeded."""
        p = filedialog.askopenfilename(
            title="cookies.txt を取り込む",
            filetypes=[("cookies.txt", "*.txt"), ("すべて", "*.*")],
        )
        if not p:
            return
        try:
            n = core.import_cookies_file(p)
        except Exception as e:
            messagebox.showerror(
                "取り込みエラー", f"cookies.txt を読み込めませんでした:\n{e}")
            return
        self._refresh_cookie_status()
        self.log(f"Cookie を取り込みました（{n} 件）。以後この元ファイルは不要です → "
                 f"{core.get_cookies_path()}")
        self._check_cookies(silent=True)  # confirm the fresh cookies actually work

    def _clear_cookies(self):
        """Delete the app's saved cookies."""
        if not core.has_saved_cookies():
            return
        if not messagebox.askyesno("確認", "保存済みの Kindle 接続情報を削除しますか？"):
            return
        core.clear_saved_cookies()
        self._refresh_cookie_status()
        self.log("保存済みの Cookie を削除しました。")

    def _logical_wh(self):
        """Current window (width, height) in logical px (geometry() is scaled back)."""
        w, h = self.root.geometry().split("+")[0].split("x")
        return int(w), int(h)

    def _fit_height_to_content(self):
        """Shrink the window to exactly fit its content (used when collapsed).

        winfo_reqheight is in physical px; divide by the window scaling to get
        the logical height CTk's geometry() expects (else it double-scales).
        """
        self.root.update_idletasks()
        scaling = ctk.ScalingTracker.get_window_scaling(self.root)
        h = round(self.root.winfo_reqheight() / scaling)
        w, _ = self._logical_wh()
        self.root.geometry(f"{w}x{h}")

    def _toggle_log(self):
        """Expand/collapse the log; the window height follows (accordion)."""
        self._log_open = not self._log_open
        if self._log_open:
            self.logbox.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
            self.log_toggle.configure(text="▾ ログ")
            self.outer.rowconfigure(5, weight=1)  # fill remaining space
            w, _ = self._logical_wh()
            self.root.geometry(f"{w}x{self._expanded_h}")  # restore expanded height
        else:
            self._expanded_h = self._logical_wh()[1]  # remember it for next expand
            self.logbox.grid_remove()
            self.log_toggle.configure(text="▸ ログ")
            self.outer.rowconfigure(5, weight=0)  # shrink to just the header
            self._fit_height_to_content()

    def log(self, msg):
        self.root.after(0, self._append, str(msg))

    def _append(self, msg):
        # The textbox keeps buffering even while collapsed; it shows on expand.
        self.logbox.insert("end", msg + "\n")
        self.logbox.see("end")

    # -- progress (called from the worker thread; hop to the UI thread) --
    def on_progress(self, phase, current, total):
        self.root.after(0, self._apply_progress, phase, current, total)

    def _apply_progress(self, phase, current, total):
        if total and total > 0:
            if self._indeterminate:
                self.pbar.stop()
                self.pbar.configure(mode="determinate")
                self._indeterminate = False
            self.pbar.set(current / total)
            self.status.configure(text=f"{phase} {current}/{total}")
        else:
            if not self._indeterminate:
                self.pbar.configure(mode="indeterminate")
                self.pbar.start()
                self._indeterminate = True
            self.status.configure(text=phase + " …")

    def _reset_progress(self):
        if self._indeterminate:
            self.pbar.stop()
            self.pbar.configure(mode="determinate")
            self._indeterminate = False
        self.pbar.set(0)
        self.status.configure(text="")

    def _finish_progress(self, text):
        if self._indeterminate:
            self.pbar.stop()
            self.pbar.configure(mode="determinate")
            self._indeterminate = False
        self.pbar.set(1)
        self.status.configure(text=text)

    def _cfg_from_fields(self):
        return {
            "notion_token": self.token.get().strip(),
            "notion_parent_page_id": self.parent.get().strip(),
            "notion_database_id": self.dbid.get().strip(),
            "notify_on_complete": bool(self.notify_on_complete.get()),
            "appearance_mode": self.appearance_mode.get(),
        }

    def save(self):
        core.save_config(self._cfg_from_fields())
        self.log("設定を保存しました: " + str(core.get_config_path()))

    def sync(self):
        if not self._settings_ready():
            self._update_ready_state()  # re-assert the banner / disabled button
            return
        self.save()
        self._syncing = True
        # Snapshot the preference on the main thread; the worker reads this bool.
        self._notify_pref = bool(self.notify_on_complete.get())
        self.sync_btn.configure(state="disabled")
        self._reset_progress()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            cfg = self._cfg_from_fields()
            if not core.has_saved_cookies():
                raise RuntimeError(
                    "cookies.txt が取り込まれていません。「取り込み…」から取り込んでください。")
            cookies_file = str(core.get_cookies_path())
            res = core.run_sync(
                cfg, cookies_file, None, log=self.log, progress=self.on_progress
            )
            self.root.after(0, lambda: self.dbid.set(cfg.get("notion_database_id", "")))
            summary = (f"新規 {res['inserted']} / 重複 {res['skipped']} / "
                       f"失敗 {res['failed']}")
            self.log(f"完了: 対象 {res['total']} / " + summary)
            self.root.after(0, self._finish_progress, "完了")
            if self._notify_pref:
                desktop_notify("Booklight 同期完了", summary)
        except Exception as e:
            self.log("エラー: " + str(e))
            self.root.after(0, self._finish_progress, "エラー")
            if self._notify_pref:
                desktop_notify("Booklight 同期エラー", str(e))
        finally:
            self._syncing = False
            self.root.after(0, self._update_ready_state)

    def _on_close(self):
        """Confirm before quitting mid-sync; a normal close just exits."""
        if self._syncing:
            if not messagebox.askyesno(
                "同期中",
                "同期を実行中です。中断して終了しますか？\n"
                "（登録済みの分は残り、次回の実行で続きから再開できます）"):
                return
        self.root.destroy()


def main():
    if sys.platform.startswith("win"):
        try:  # own taskbar identity (+icon), not grouped under python.exe
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Booklight.App")
        except Exception:
            pass
    register_bundled_fonts()  # before ctk.CTk() so Tk sees the new families
    ctk.set_default_color_theme("blue")  # base structure; recolored by _apply_palette
    _apply_palette()
    ctk.set_appearance_mode("system")
    root = _AppRoot()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
