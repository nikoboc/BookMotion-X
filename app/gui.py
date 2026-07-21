#!/usr/bin/env python3
"""CustomTkinter GUI for the Kindle → Notion app (Level 3 packaged .app entry point).

Enter your Notion token / parent page / cookies right in the window — no file
editing. Values are saved to config.json (Application Support when packaged).
"""
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

import kindle_notion as core

# indigo accent, works on both light and dark backgrounds
ACCENT = "#4F46E5"
ACCENT_HOVER = "#4338CA"
MUTED = ("gray40", "gray65")  # (light, dark)
OK_COLOR = ("#15803D", "#22C55E")     # green — cookies still valid (light, dark)
BAD_COLOR = ("#DC2626", "#F87171")    # red — expired / needs re-import (light, dark)

APPEARANCE = {"システム": "system", "ライト": "light", "ダーク": "dark"}


def _fonts_dir() -> Path:
    """Directory holding the bundled .otf/.ttf files, in dev and when frozen.

    When packaged with PyInstaller (`--add-data "...:fonts"`), the files land
    under sys._MEIPASS/fonts; in dev they sit next to this script in app/fonts/.
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "fonts"
    return Path(__file__).resolve().parent / "fonts"


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
            Notification(app_id="Kindle → Notion", title=title, msg=message).show()
    except Exception:
        pass


def _apply_titlebar_theme(win) -> None:
    """Match a window's title bar to the current appearance (Windows only).

    CTkToplevel sometimes leaves the title bar light in dark mode; set the DWM
    immersive-dark-mode attribute explicitly and nudge the frame to repaint.
    Best-effort no-op on other platforms or older Windows.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        use_dark = ctypes.c_int(1 if ctk.get_appearance_mode() == "Dark" else 0)
        hwnd = ctypes.windll.user32.GetAncestor(win.winfo_id(), 2)  # GA_ROOT
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20  # 19 on pre-20H1 Windows 10
        if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(use_dark), ctypes.sizeof(use_dark)) != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(use_dark), ctypes.sizeof(use_dark))
        # Force a non-client (title-bar) repaint WITHOUT resizing — a resize
        # round-trip would double-apply CustomTkinter's DPI scaling and grow the
        # window. SWP_FRAMECHANGED redraws the frame at the same size/position.
        SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_FRAMECHANGED = 0x1, 0x2, 0x4, 0x20
        ctypes.windll.user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED)
    except Exception:
        pass


class SettingsDialog(ctk.CTkToplevel):
    """Modal dialog for the rarely-changed Notion settings (token / URL / DB ID).

    Edits the App's shared StringVars directly; "保存して閉じる" persists via
    App.save() and re-evaluates the main window's ready state.
    """

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("設定")
        self.geometry("560x780")
        self.minsize(480, 660)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self.after(10, self._grab)  # grab once the window is viewable
        # Match the title bar to the theme, after CustomTkinter's own attempt.
        self.after(120, lambda: _apply_titlebar_theme(self))

    def _grab(self):
        try:
            self.grab_set()
        except Exception:
            pass
        self.lift()
        self.focus_force()

    def _build(self):
        app = self.app
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=20, pady=18)
        outer.columnconfigure(0, weight=1)

        card = ctk.CTkFrame(outer, corner_radius=12)
        card.grid(row=0, column=0, sticky="ew")
        card.columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text="Notion 接続", font=app.f_section, anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(14, 4))

        ctk.CTkLabel(card, text="Notion トークン", font=app.f_body, anchor="w").grid(
            row=1, column=0, sticky="w", padx=(16, 8), pady=6)
        self.token_entry = ctk.CTkEntry(
            card, textvariable=app.token, font=app.f_mono,
            show="" if app.show_token.get() else "•")
        self.token_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=6)
        ctk.CTkCheckBox(card, text="表示", variable=app.show_token, width=52,
                        command=self._toggle_token, font=app.f_small).grid(
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
            text=("空欄のまま同期すると、新しいデータベースを自動作成します。\n"
                  "既存の DB を使うには、その DB を Notion のブラウザで開き、URL "
                  "「notion.so/…/xxxx?v=…」の xxxx（32 桁の英数字）を貼り付けてください。"),
        ).grid(row=4, column=1, columnspan=2, sticky="w", padx=(0, 16), pady=(0, 16))

        # --- card: 取得設定 (cookie management) ---
        c2 = ctk.CTkFrame(outer, corner_radius=12)
        c2.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        c2.columnconfigure(0, weight=1)
        ctk.CTkLabel(c2, text="取得設定", font=app.f_section, anchor="w").grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(c2, text="Cookie（cookies.txt）", font=app.f_body, anchor="w").grid(
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
        c3 = ctk.CTkFrame(outer, corner_radius=12)
        c3.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        c3.columnconfigure(1, weight=1)
        ctk.CTkLabel(c3, text="外観", font=app.f_section, anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(c3, text="テーマ", font=app.f_body, anchor="w").grid(
            row=1, column=0, sticky="w", padx=(16, 8), pady=(0, 14))
        ctk.CTkOptionMenu(
            c3, values=list(APPEARANCE), variable=app.appearance_mode, width=140,
            font=app.f_small, command=app._set_appearance, fg_color=ACCENT,
            button_color=ACCENT, button_hover_color=ACCENT_HOVER).grid(
            row=1, column=1, sticky="w", padx=(0, 16), pady=(0, 14))

        # --- card: 通知 ---
        c4 = ctk.CTkFrame(outer, corner_radius=12)
        c4.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        c4.columnconfigure(0, weight=1)
        ctk.CTkLabel(c4, text="通知", font=app.f_section, anchor="w").grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 4))
        ctk.CTkCheckBox(c4, text="同期完了時にデスクトップ通知を出す",
                        variable=app.notify_on_complete, font=app.f_body).grid(
            row=1, column=0, sticky="w", padx=16, pady=(0, 14))

        br = ctk.CTkFrame(outer, fg_color="transparent")
        br.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        br.columnconfigure(0, weight=1)
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
        self.app.save()
        self.app._update_ready_state()
        self._close()

    def _close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.app._unregister_validity_label(self.valid_lbl)
        self.app._settings_win = None
        self.destroy()


class App:
    def __init__(self, root: ctk.CTk):
        self.root = root
        root.title("Kindle → Notion")
        root.geometry("720x820")
        root.minsize(640, 700)
        cfg = core.load_config()
        self._indeterminate = False
        self._syncing = False
        self._notify_pref = True  # snapshot taken on the main thread at sync start

        self.token = tk.StringVar(value=cfg.get("notion_token", ""))
        self.parent = tk.StringVar(value=cfg.get("notion_parent_page_id", ""))
        self.dbid = tk.StringVar(value=cfg.get("notion_database_id", ""))
        # Desktop-notification preference (settings dialog toggle); default on.
        self.notify_on_complete = tk.BooleanVar(
            value=bool(cfg.get("notify_on_complete", True)))
        # Theme choice lives in the settings dialog; keep it here so the dialog's
        # dropdown reflects the current selection each time it opens.
        self.appearance_mode = tk.StringVar(value="システム")
        self.cookies_status = tk.StringVar(value="")
        self.cookies_valid = tk.StringVar(value="")
        self._settings_win = None
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
    def _card(self, row, title, expand=False):
        card = ctk.CTkFrame(self.outer, corner_radius=12)
        card.grid(row=row, column=0, sticky="nsew" if expand else "ew", pady=(0, 12))
        card.columnconfigure(0, weight=1)
        card.columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text=title, font=self.f_section, anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(14, 4))
        return card

    def _ghost(self, parent, text, command, width=0):
        kw = {"width": width} if width else {}
        return ctk.CTkButton(
            parent, text=text, command=command, font=self.f_btn,
            fg_color="transparent", border_width=1,
            text_color=("gray20", "gray90"),
            border_color=("gray70", "gray45"),
            hover_color=("gray90", "gray25"), **kw,
        )

    def _accent(self, parent, text, command):
        return ctk.CTkButton(
            parent, text=text, command=command, font=self.f_btn,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#FFFFFF",
        )

    def _label(self, parent, text, row):
        ctk.CTkLabel(parent, text=text, font=self.f_body, anchor="w").grid(
            row=row, column=0, sticky="w", padx=(16, 8), pady=6)

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
        ctk.CTkLabel(titles, text="📚  Kindle → Notion", font=self.f_title,
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(titles, text="Kindle のハイライトを Notion に同期します",
                     font=self.f_sub, text_color=MUTED, anchor="w").pack(anchor="w")

        # --- settings-incomplete banner (row 1); hidden once token + URL are set ---
        self.warn = ctk.CTkLabel(
            self.outer, font=self.f_small, text_color=BAD_COLOR, anchor="w",
            text="⚠ トークンと親ページ URL が未設定です。「⚙ 設定」から入力してください。")
        self.warn.grid(row=1, column=0, sticky="w", pady=(0, 10))

        # --- card: Cookie (read-only status;管理は「⚙ 設定」ダイアログで) ---
        c2 = self._card(2, "Cookie")
        cf = ctk.CTkFrame(c2, fg_color="transparent")
        cf.grid(row=1, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 14))
        cf.columnconfigure(0, weight=1)
        ctk.CTkLabel(cf, textvariable=self.cookies_status, font=self.f_small,
                     text_color=MUTED, anchor="w").grid(row=0, column=0, sticky="w")
        # Colored validity line — updated by the startup probe and manual checks.
        lbl = ctk.CTkLabel(cf, textvariable=self.cookies_valid, font=self.f_small,
                           text_color=MUTED, anchor="w")
        lbl.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._register_validity_label(lbl)

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
        self.pbar = ctk.CTkProgressBar(pf, progress_color=ACCENT)
        self.pbar.grid(row=0, column=0, sticky="ew")
        self.pbar.set(0)
        self.status = ctk.CTkLabel(pf, text="", font=self.f_small, text_color=MUTED,
                                   anchor="w")
        self.status.grid(row=1, column=0, sticky="w", pady=(6, 0))

        # --- log card (collapsible like <details>; collapsed by default) ---
        lc = ctk.CTkFrame(self.outer, corner_radius=12)
        lc.grid(row=5, column=0, sticky="nsew", pady=(0, 12))
        lc.columnconfigure(0, weight=1)
        lc.rowconfigure(1, weight=1)
        self._log_open = False
        self.log_toggle = ctk.CTkButton(
            lc, text="▸ ログ", command=self._toggle_log, font=self.f_section,
            anchor="w", height=32, corner_radius=8, fg_color="transparent",
            text_color=("gray20", "gray90"), hover_color=("gray90", "gray25"))
        self.log_toggle.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.logbox = ctk.CTkTextbox(lc, font=self.f_log, corner_radius=8,
                                     wrap="word", height=220)
        # The textbox stays ungridded until expanded (default: collapsed).

        # Reflect the saved-cookie status on the Cookie row.
        self._refresh_cookie_status()
        # Notice an expired cookie without waiting for a full sync: probe once at
        # startup (in the background) if we have saved cookies.
        if core.has_saved_cookies():
            self.root.after(400, lambda: self._check_cookies(silent=True))

        # Gate the sync button on the required settings (token + parent URL),
        # live as they change in the settings dialog.
        self.token.trace_add("write", self._update_ready_state)
        self.parent.trace_add("write", self._update_ready_state)
        self._update_ready_state()

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
        n = core.saved_cookies_count()
        if saved:
            self.cookies_status.set(f"取り込み済み（{n} 件）" if n else "取り込み済み")
        else:
            self.cookies_status.set("未取り込み")
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
                self.root.after(0, self._set_validity, "✓ ログイン有効", OK_COLOR)
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

    def _set_appearance(self, choice):
        ctk.set_appearance_mode(APPEARANCE.get(choice, "system"))
        win = self._settings_win
        if win is not None and win.winfo_exists():
            win.after(60, lambda: _apply_titlebar_theme(win))

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
        """Open (or focus) the modal settings dialog."""
        win = self._settings_win
        if win is not None and win.winfo_exists():
            win.lift()
            win.focus_force()
            return
        self._settings_win = SettingsDialog(self)

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
        if not messagebox.askyesno("確認", "保存済みの Cookie を削除しますか？"):
            return
        core.clear_saved_cookies()
        self._refresh_cookie_status()
        self.log("保存済みの Cookie を削除しました。")

    def _toggle_log(self):
        """Expand/collapse the log area (like a <details> element)."""
        self._log_open = not self._log_open
        if self._log_open:
            self.logbox.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
            self.log_toggle.configure(text="▾ ログ")
            self.outer.rowconfigure(5, weight=1)  # fill remaining space
        else:
            self.logbox.grid_remove()
            self.log_toggle.configure(text="▸ ログ")
            self.outer.rowconfigure(5, weight=0)  # shrink to just the header

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
                desktop_notify("Kindle → Notion 同期完了", summary)
        except Exception as e:
            self.log("エラー: " + str(e))
            self.root.after(0, self._finish_progress, "エラー")
            if self._notify_pref:
                desktop_notify("Kindle → Notion 同期エラー", str(e))
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
    register_bundled_fonts()  # before ctk.CTk() so Tk sees the new families
    ctk.set_default_color_theme("blue")
    ctk.set_appearance_mode("system")
    root = ctk.CTk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
