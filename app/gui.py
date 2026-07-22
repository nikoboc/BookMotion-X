#!/usr/bin/env python3
"""CustomTkinter GUI for the Kindle → Notion app (Level 3 packaged .app entry point).

Enter your Notion token / parent page / cookies right in the window — no file
editing. Values are saved to config.json (Application Support when packaged).
"""
import locale
import subprocess
import sys
import threading
import webbrowser
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

import kindle_notion as core

# ---- Palette: soft, low-saturation cool neutrals + a muted blue accent -------
# Every value is a (light, dark) pair. The base is nearly white in light mode and
# nearly black in dark mode, with only a faint cool (blue-grey) tint; the accent
# is a muted blue. On the ACCENT fills the label is white in light mode and a dark
# navy in dark mode (the dark-mode accent is a soft light blue). SUB fills are a
# mid-tone in both modes, so their label (ON_SUB) is dark in both. All pairs were
# checked to clear WCAG AA on the surface they sit on.
BASE   = ("#eef1f5", "#191b1f")  # window + card background — near white / near black (ベース)
SUB    = ("#d4d9df", "#7f858c")  # secondary fills: card borders, 2nd-ary buttons, progress track (サブ)
ACCENT = ("#3f6291", "#93b8db")  # muted blue — primary actions, checkboxes, progress, selected (アクセント)

TEXT      = ("#2f333a", "#e5e8ec")  # primary text: cool charcoal on light / cool off-white on dark
MUTED     = ("#6f757d", "#9aa0a8")  # secondary / hint text
ON_ACCENT = ("#FFFFFF", "#15202B")  # text + checkmark on a blue ACCENT fill (white / dark navy)
ON_SUB    = "#1E232A"               # text on a SUB fill — dark in both modes

ACCENT_HOVER = ("#34527A", "#7FA8CE")  # hover / pressed accent fill
SUB_HOVER    = ("#C4CBD3", "#8F959C")  # hover / pressed secondary fill
ACCENT_LINK  = ("#3A5F8A", "#8FB2D6")  # muted-blue link text over the window / card bg

OK_COLOR  = ("#3F7D4F", "#7FB389")  # muted green — cookies still valid   (semantic)
BAD_COLOR = ("#B0473C", "#D99A90")  # muted red   — expired / re-login     (semantic)


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

# ---- UI language (auto-detected from the OS; overridable in Settings) --------
def _detect_os_lang():
    """'ja' if the OS UI language is Japanese, else 'en'. Best-effort; 'ja' on error."""
    try:
        if sys.platform.startswith("win"):
            import ctypes

            prim = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            return "ja" if prim == 0x11 else "en"  # 0x11 = Japanese primary language
        code = ""
        try:
            code = locale.getlocale()[0] or ""
        except Exception:
            code = ""
        if not code:
            code = (locale.getdefaultlocale() or ["", ""])[0] or ""
        return "ja" if str(code).lower().startswith("ja") else "en"
    except Exception:
        return "ja"


LANG = "ja"  # active UI language; set once at startup by set_language().


def set_language(pref):
    """pref: 'auto' (follow the OS), 'ja', or 'en'. Returns the resolved language."""
    global LANG
    LANG = _detect_os_lang() if pref not in ("ja", "en") else pref
    return LANG


def t(key):
    """Translate a UI-string key into the active language (returns the key if unknown)."""
    pair = _TR.get(key)
    if not pair:
        return key
    return pair[1] if LANG == "en" else pair[0]


# (ja, en) for every user-facing string. Developer comments and progress/log
# phrases emitted by the core engine (kindle_notion.py) are out of scope.
_TR = {
    # main window
    "app_subtitle": ("Kindle のハイライトを Notion に同期します",
                     "Sync your Kindle highlights to Notion"),
    "last_sync_label": ("最終同期", "Last sync"),
    "warn_incomplete": ("⚠ Notion のトークンと親ページ URL が未設定です。「⚙ 設定」から入力してください。",
                        "⚠ Notion token and parent page URL aren't set. Enter them in “⚙ Settings”."),
    "warn_need_kindle": ("⚠ Kindle にサインインしていません。「⚙ 設定」からサインインしてください。",
                         "⚠ You're not signed in to Kindle. Sign in from “⚙ Settings”."),
    "warn_need_both": ("⚠ Notion と Kindle の設定が未完了です。「⚙ 設定」から設定してください。",
                       "⚠ Notion and Kindle setup isn't complete. Finish it in “⚙ Settings”."),
    "btn_settings": ("⚙ 設定", "⚙ Settings"),
    "btn_sync": ("Notion へ同期", "Sync to Notion"),
    "btn_open_notion": ("Notion で開く", "Open in Notion"),
    "log_label": ("ログ", "Log"),
    # connection status
    "acct_set": ("アカウント情報設定済み", "Account configured"),
    "acct_unset": ("アカウント情報未設定", "Account not configured"),
    "conn_ok": ("✓ 接続OK", "✓ Connected"),
    "checking": ("確認中…", "Checking…"),
    "cookies_expired": ("✕ 期限切れ — 設定から再度サインインしてください",
                        "✕ Expired — please sign in again in Settings"),
    "conn_failed": ("接続を確認できませんでした（ネットワーク未接続など）",
                    "Couldn't check the connection (no network, etc.)"),
    "token_invalid": ("✕ トークンが無効です — 設定で確認してください",
                      "✕ Invalid token — check it in Settings"),
    # settings dialog
    "settings_title": ("設定", "Settings"),
    "notion_conn": ("Notion 接続情報", "Notion connection"),
    "notion_token": ("Notion トークン", "Notion token"),
    "show": ("表示", "Show"),
    "parent_url": ("親ページ URL", "Parent page URL"),
    "db_id_optional": ("DB ID（任意）", "Database ID (optional)"),
    "db_id_hint": ("空欄のまま同期すると、新しいデータベースを自動作成します。",
                   "Leave blank to auto-create a new database on sync."),
    "kindle_conn": ("Kindle 接続情報", "Kindle connection"),
    "btn_kindle_login": ("Kindle にログイン", "Sign in to Kindle"),
    "login_running": ("ログイン中…（開いたブラウザ窓で操作してください）",
                      "Signing in… (use the browser window that opened)"),
    "login_cancelled": ("ログインは完了しませんでした", "Sign-in didn't complete"),
    "btn_check": ("接続確認", "Test"),
    "btn_clear": ("クリア", "Clear"),
    "appearance": ("外観", "Appearance"),
    "theme": ("テーマ", "Theme"),
    "theme_system": ("システム", "System"),
    "theme_light": ("ライト", "Light"),
    "theme_dark": ("ダーク", "Dark"),
    "language": ("言語", "Language"),
    "lang_auto": ("自動", "Auto"),
    "lang_restart_note": ("言語の変更は再起動後に反映されます。",
                          "Language changes take effect after a restart."),
    "notifications": ("通知", "Notifications"),
    "notify_toggle": ("同期完了時にデスクトップ通知を出す",
                      "Show a desktop notification when a sync finishes"),
    "btn_help": ("❓ 取得方法", "❓ Setup guide"),
    "btn_save_close": ("保存して閉じる", "Save & close"),
    "btn_close": ("閉じる", "Close"),
    # help dialog
    "help_title": ("取得方法 / ヘルプ", "Setup guide / Help"),
    "help_intro": ("同期には ① Notion トークン ② 親ページ URL ③（任意）DB ID ④ Kindle へのサインイン が必要です。設定は「⚙ 設定」で行います。",
                   "You need ① a Notion token, ② a parent page URL, ③ (optional) a DB ID, and ④ to sign in to Kindle. Set them up in “⚙ Settings”."),
    "help1_title": ("① Notion トークンの取得", "① Get a Notion token"),
    "help1_s1": ("1. 下のリンクから「マイインテグレーション」を開きます。",
                 "1. Open “My integrations” from the link below."),
    "help1_l1": ("🔗 notion.so/my-integrations を開く", "🔗 Open notion.so/my-integrations"),
    "help1_s2": ("2. 「新しいインテグレーション」を作成します（種類は内部/Internal）。",
                 "2. Create a “New integration” (type: Internal)."),
    "help1_s3": ("3. 表示された「Internal Integration Token」（ntn_… または secret_… で始まる文字列）をコピーします。",
                 "3. Copy the “Internal Integration Token” shown (it starts with ntn_… or secret_…)."),
    "help1_s4": ("4. 「⚙ 設定」の「Notion トークン」欄に貼り付けます。",
                 "4. Paste it into the “Notion token” field in “⚙ Settings”."),
    "help1_note": ("⚠ トークンを作っただけでは書き込めません。②の親ページに、このインテグレーションを「連携」から追加してください（忘れると 404 エラー）。",
                   "⚠ Creating the token isn't enough — add this integration to the parent page (②) via “Connections”, or writes fail with a 404."),
    "help2_title": ("② 親ページ URL の取得と連携", "② Get the parent page URL and connect it"),
    "help2_s1": ("1. データベースを置きたい Notion のページを開きます（新しい空ページを作ってもOK）。",
                 "1. Open the Notion page where the database should live (a new empty page is fine)."),
    "help2_l1": ("🔗 Notion を開く", "🔗 Open Notion"),
    "help2_s2": ("2. そのページの URL をコピーし、「⚙ 設定」の「親ページ URL」欄に貼り付けます。",
                 "2. Copy that page's URL and paste it into the “Parent page URL” field in “⚙ Settings”."),
    "help2_s3": ("3. ページ右上の「•••」→「連携（コネクト）」→ ①で作ったインテグレーションを追加します。",
                 "3. Top-right “•••” → “Connections” → add the integration you made in ①."),
    "help2_note": ("この「連携」を忘れると、トークンが正しくても 404 で失敗します。",
                   "Skip this “Connection” and it fails with a 404 even with a valid token."),
    "help3_title": ("③ データベース ID（任意）", "③ Database ID (optional)"),
    "help3_s1": ("空欄のまま同期すると、新しいデータベースを自動作成します。通常は空欄でOKです。",
                 "Leave it blank to auto-create a new database on sync. Blank is fine for most cases."),
    "help3_s2": ("既存のデータベースに追記したい場合のみ、その DB を Notion のブラウザで開きます。",
                 "Only if you want to append to an existing database, open that DB in the Notion browser."),
    "help3_s3": ("URL「notion.so/…/xxxxxxxx?v=…」の xxxxxxxx（32 桁の英数字）が DB ID です。これを「⚙ 設定」の「DB ID」欄に貼り付けます。",
                 "In the URL “notion.so/…/xxxxxxxx?v=…”, the xxxxxxxx (32 hex chars) is the DB ID. Paste it into the “DB ID” field in “⚙ Settings”."),
    "help3_note": ("最後のスラッシュの後ろ・「?v=」より前が DB ID です（末尾のページ名部分は無視されます）。",
                   "The DB ID is the part after the last slash and before “?v=” (any trailing page-name part is ignored)."),
    "help4_login_title": ("④ Kindle にサインイン", "④ Sign in to Kindle"),
    "help4_login_s1": ("「⚙ 設定」の「Kindle にログイン」を押し、開いたウィンドウで Amazon にログインします（2要素認証もそのまま通ります）。",
                       "In “⚙ Settings”, click “Sign in to Kindle” and log in to Amazon in the window that opens (2-factor auth works too)."),
    "help4_login_note": ("ログインは自動で保存され、同期のたびに更新されます。cookies.txt は不要です。",
                         "The sign-in is saved automatically and refreshed on every sync — no cookies.txt needed."),
    # dialogs / message boxes
    "mb_check_title": ("接続確認", "Test connection"),
    "mb_import_first": ("先に「Kindle にログイン」でサインインしてください。",
                        "Please sign in with “Sign in to Kindle” first."),
    "mb_confirm_title": ("確認", "Confirm"),
    "mb_clear_confirm": ("保存済みの Kindle 接続情報を削除しますか？", "Delete the saved Kindle connection info?"),
    "mb_syncing_title": ("同期中", "Sync in progress"),
    "mb_quit_confirm": ("同期を実行中です。中断して終了しますか？\n（登録済みの分は残り、次回の実行で続きから再開できます）",
                        "A sync is running. Stop it and quit?\n(Already-saved items remain; the next run resumes where it left off.)"),
    # log / progress / notifications
    "log_cookie_cleared": ("保存済みの Cookie を削除しました。", "Deleted the saved cookies."),
    "log_config_saved": ("設定を保存しました: {path}", "Settings saved: {path}"),
    "log_done": ("完了: 対象 {total} / {summary}", "Done: {total} items / {summary}"),
    "log_error": ("エラー: {e}", "Error: {e}"),
    "summary_fmt": ("新規 {inserted} / 重複 {skipped} / 失敗 {failed}",
                    "New {inserted} / Dup {skipped} / Failed {failed}"),
    "sync_err_cookies": ("Kindle にログインしていません。「Kindle にログイン」からサインインしてください。",
                         "You're not signed in to Kindle. Click “Sign in to Kindle” to sign in."),
    "prog_done": ("完了", "Done"),
    "prog_error": ("エラー", "Error"),
    "notif_done_title": ("Booklight 同期完了", "Booklight — Sync complete"),
    "notif_err_title": ("Booklight 同期エラー", "Booklight — Sync error"),
}


# ---- Theme (canonical values stored in config; labels are localized) ---------
THEME_VALUES = ("system", "light", "dark")
_LEGACY_THEME = {"システム": "system", "ライト": "light", "ダーク": "dark"}


def theme_label(value):
    return t("theme_" + value)


def theme_value(label):
    for v in THEME_VALUES:
        if theme_label(v) == label:
            return v
    return "system"


def normalize_theme(saved):
    v = _LEGACY_THEME.get(saved, saved)
    return v if v in THEME_VALUES else "system"


# ---- Language preference (Settings selector) ---------------------------------
LANG_PREFS = ("auto", "ja", "en")


def langpref_label(pref):
    return {"auto": t("lang_auto"), "ja": "日本語", "en": "English"}.get(pref, t("lang_auto"))


def langpref_value(label):
    for p in LANG_PREFS:
        if langpref_label(p) == label:
            return p
    return "auto"

# External help links opened from the help window (取得方法).
NOTION_INTEGRATIONS_URL = "https://www.notion.so/my-integrations"


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
        """Repaint the title bar for the given appearance mode (no-op off Windows)."""
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

    The Notion fields (token / parent URL / DB ID) are edited in the dialog's
    OWN StringVars, so typing here never touches the main window; they're copied
    into the App and persisted only on "保存して閉じる", which then refreshes the
    main window's status / banner / sync button.
    """

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        # Notion fields edit local copies so the main window doesn't react while
        # you type (no live error banner); they're applied on Save & close.
        self.token_var = tk.StringVar(value=app.token.get())
        self.parent_var = tk.StringVar(value=app.parent.get())
        self.dbid_var = tk.StringVar(value=app.dbid.get())
        # These two ARE bound live (theme previews, notify toggles in place), so
        # snapshot them for cancel. Nothing else persists until "保存して閉じる".
        self._orig = {
            "notify": app.notify_on_complete.get(),
            "appearance": app.appearance_mode.get(),
        }
        self.title(t("settings_title"))
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
        """Build the settings dialog: Kindle sign-in, Notion fields, theme/language, notifications."""
        app = self.app
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=20, pady=18)
        outer.columnconfigure(0, weight=1)

        # Notion 接続情報 sits below Kindle 接続情報 (row 0); see c2 below.
        card = ctk.CTkFrame(outer, corner_radius=12, border_width=1)
        card.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        card.columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text=t("notion_conn"), font=app.f_section, anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(14, 4))

        ctk.CTkLabel(card, text=t("notion_token"), font=app.f_body, anchor="w").grid(
            row=1, column=0, sticky="w", padx=(16, 8), pady=6)
        self.token_entry = ctk.CTkEntry(
            card, textvariable=self.token_var, font=app.f_mono,
            show="" if app.show_token.get() else "•")
        self.token_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=6)
        ctk.CTkCheckBox(card, text=t("show"), variable=app.show_token, width=52,
                        command=self._toggle_token, font=app.f_small,
                        fg_color=ACCENT, hover_color=ACCENT_HOVER,
                        checkmark_color=ON_ACCENT).grid(
            row=1, column=2, sticky="w", padx=(0, 16), pady=6)

        ctk.CTkLabel(card, text=t("parent_url"), font=app.f_body, anchor="w").grid(
            row=2, column=0, sticky="w", padx=(16, 8), pady=6)
        ctk.CTkEntry(card, textvariable=self.parent_var, font=app.f_mono).grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=(0, 16), pady=6)

        ctk.CTkLabel(card, text=t("db_id_optional"), font=app.f_body, anchor="w").grid(
            row=3, column=0, sticky="w", padx=(16, 8), pady=6)
        ctk.CTkEntry(card, textvariable=self.dbid_var, font=app.f_mono).grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=(0, 16), pady=(6, 2))
        ctk.CTkLabel(
            card, font=app.f_small, text_color=MUTED, anchor="w", justify="left",
            wraplength=380,
            text=t("db_id_hint"),
        ).grid(row=4, column=1, columnspan=2, sticky="w", padx=(0, 16), pady=(0, 16))

        # --- card: Kindle 接続情報 — sign in with the in-app browser (WebView2) ---
        c2 = ctk.CTkFrame(outer, corner_radius=12, border_width=1)
        c2.grid(row=0, column=0, sticky="ew")
        c2.columnconfigure(0, weight=1)
        ctk.CTkLabel(c2, text=t("kindle_conn"), font=app.f_section, anchor="w").grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 6))

        # Sign in with the in-app browser (WebView2 on Windows, WKWebView on macOS).
        top = ctk.CTkFrame(c2, fg_color="transparent")
        top.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 2))
        self.login_btn = app._accent(top, t("btn_kindle_login"), app._kindle_login)
        self.login_btn.configure(height=36)
        self.login_btn.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(top, textvariable=app.cookies_status, font=app.f_small,
                     text_color=MUTED, anchor="w").pack(side="left")
        self.valid_lbl = ctk.CTkLabel(c2, textvariable=app.cookies_valid,
                                      font=app.f_small, text_color=MUTED, anchor="w")
        self.valid_lbl.grid(row=2, column=0, sticky="w", padx=16, pady=(2, 0))
        app._register_validity_label(self.valid_lbl)

        # Test the current sign-in / clear it (sign out or switch account).
        ff = ctk.CTkFrame(c2, fg_color="transparent")
        ff.grid(row=3, column=0, sticky="w", padx=16, pady=(8, 14))
        self.cookies_check_btn = app._ghost(ff, t("btn_check"), app._check_cookies, width=88)
        self.cookies_check_btn.pack(side="left", padx=(0, 8))
        self.cookies_clear_btn = app._ghost(ff, t("btn_clear"), app._clear_cookies, width=72)
        self.cookies_clear_btn.pack(side="left")
        self.refresh_cookie_buttons(core.has_saved_cookies())

        # --- card: 外観 / 言語 (appearance + language) ---
        c3 = ctk.CTkFrame(outer, corner_radius=12, border_width=1)
        c3.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        c3.columnconfigure(1, weight=1)
        ctk.CTkLabel(c3, text=t("appearance"), font=app.f_section, anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(c3, text=t("theme"), font=app.f_body, anchor="w").grid(
            row=1, column=0, sticky="w", padx=(16, 8), pady=(0, 8))
        ctk.CTkOptionMenu(
            c3, values=[theme_label(v) for v in THEME_VALUES],
            variable=app.appearance_mode, width=160,
            font=app.f_small, dropdown_font=app.f_small,
            command=app._set_appearance, fg_color=ACCENT,
            button_color=ACCENT_HOVER, button_hover_color=ACCENT_HOVER,
            text_color=ON_ACCENT).grid(
            row=1, column=1, sticky="w", padx=(0, 16), pady=(0, 8))
        ctk.CTkLabel(c3, text=t("language"), font=app.f_body, anchor="w").grid(
            row=2, column=0, sticky="w", padx=(16, 8), pady=(0, 4))
        ctk.CTkOptionMenu(
            c3, values=[langpref_label(p) for p in LANG_PREFS],
            variable=app.ui_language, width=160,
            font=app.f_small, dropdown_font=app.f_small,
            fg_color=ACCENT, button_color=ACCENT_HOVER,
            button_hover_color=ACCENT_HOVER, text_color=ON_ACCENT).grid(
            row=2, column=1, sticky="w", padx=(0, 16), pady=(0, 4))
        ctk.CTkLabel(c3, text=t("lang_restart_note"), font=app.f_small,
                     text_color=MUTED, anchor="w", justify="left",
                     wraplength=380).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 14))

        # --- card: 通知 ---
        c4 = ctk.CTkFrame(outer, corner_radius=12, border_width=1)
        c4.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        c4.columnconfigure(0, weight=1)
        ctk.CTkLabel(c4, text=t("notifications"), font=app.f_section, anchor="w").grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 4))
        ctk.CTkCheckBox(c4, text=t("notify_toggle"),
                        variable=app.notify_on_complete, font=app.f_body,
                        fg_color=ACCENT, hover_color=ACCENT_HOVER,
                        checkmark_color=ON_ACCENT).grid(
            row=1, column=0, sticky="w", padx=16, pady=(0, 14))

        br = ctk.CTkFrame(outer, fg_color="transparent")
        br.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        br.columnconfigure(0, weight=1)
        help_btn = app._ghost(br, t("btn_help"), self._open_help)
        help_btn.configure(height=38)
        help_btn.grid(row=0, column=0, sticky="w")
        save_btn = app._accent(br, t("btn_save_close"), self._save_close)
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
        # The only place settings are persisted — and the only place the staged
        # Notion edits reach the main window. Push the dialog's own vars into the
        # app first, then save and refresh the main-window status/banner/button.
        a = self.app
        a.token.set(self.token_var.get())
        a.parent.set(self.parent_var.get())
        a.dbid.set(self.dbid_var.get())
        a.save()
        a._update_ready_state()
        a._check_notion()  # refresh the main-window Notion status
        self._teardown()

    def _close(self):
        # Cancel (X / window close): the Notion fields were edited in the dialog's
        # own vars, so there's nothing to undo there. Only restore the live-bound
        # values captured when the dialog opened (notify toggle, theme preview).
        a, o = self.app, self._orig
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
        self.title(t("help_title"))
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
        """Build the scrollable "how to set up" guide (token / URL / DB ID / cookies)."""
        app = self.app
        wrap = ctk.CTkScrollableFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=16, pady=(16, 8))

        ctk.CTkLabel(
            wrap, font=app.f_small, text_color=MUTED, anchor="w", justify="left",
            wraplength=500, text=t("help_intro")).pack(fill="x", pady=(0, 12))

        # ① Notion token
        b = self._section(wrap, t("help1_title"))
        self._step(b, t("help1_s1"))
        self._link(b, t("help1_l1"), NOTION_INTEGRATIONS_URL)
        self._step(b, t("help1_s2"))
        self._step(b, t("help1_s3"))
        self._step(b, t("help1_s4"))
        self._note(b, t("help1_note"))

        # ② Parent page URL
        b = self._section(wrap, t("help2_title"))
        self._step(b, t("help2_s1"))
        self._link(b, t("help2_l1"), "https://www.notion.so")
        self._step(b, t("help2_s2"))
        self._step(b, t("help2_s3"))
        self._note(b, t("help2_note"))

        # ③ Database ID
        b = self._section(wrap, t("help3_title"))
        self._step(b, t("help3_s1"))
        self._step(b, t("help3_s2"))
        self._step(b, t("help3_s3"))
        self._note(b, t("help3_note"))

        # ④ Sign in to Kindle (in-app browser)
        b = self._section(wrap, t("help4_login_title"))
        self._step(b, t("help4_login_s1"))
        self._note(b, t("help4_login_note"))

        br = ctk.CTkFrame(self, fg_color="transparent")
        br.pack(fill="x", padx=16, pady=(0, 14))
        close = app._accent(br, t("btn_close"), self._close)
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
        set_language(cfg.get("ui_language", "auto"))  # before any t() in the UI
        core.set_language(LANG)  # the engine's runtime messages follow the same language
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
        # Theme + language choices live in the settings dialog; persisted in
        # config and restored here. Theme is stored canonically (system/light/
        # dark); the StringVar holds the localized label shown in the menu.
        saved_theme = normalize_theme(cfg.get("appearance_mode", "system"))
        self.appearance_mode = tk.StringVar(value=theme_label(saved_theme))
        ctk.set_appearance_mode(saved_theme)
        self.ui_language = tk.StringVar(
            value=langpref_label(cfg.get("ui_language", "auto")))
        ls = cfg.get("last_sync")
        self.last_sync = ls if isinstance(ls, dict) else None
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
        # Epoch for the async cookie-validity probe: bumped whenever the cookies
        # change (cleared / re-signed-in) or a new probe starts, so a stale probe
        # that finishes late can't overwrite the current status (e.g. re-showing
        # "接続OK" after a Clear). _run_check captures it and only applies its
        # result while it's still current.
        self._check_epoch = 0

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
        """Create the CTkFonts used across the UI, preferring the bundled Noto Sans JP."""
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
        """Build the main window: header, connection status, actions, progress, and log."""
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
        ctk.CTkLabel(titles, text=t("app_subtitle"),
                     font=self.f_sub, text_color=MUTED, anchor="w").pack(side="left")
        # Right-aligned "last sync" summary (empty until the first sync).
        self.last_sync_lbl = ctk.CTkLabel(hdr, text="", font=self.f_small,
                                          text_color=MUTED, anchor="e")
        self.last_sync_lbl.grid(row=0, column=1, sticky="e")
        self._update_last_sync_label()

        # --- settings-incomplete banner (row 1); hidden once token + URL are set ---
        self.warn = ctk.CTkLabel(
            self.outer, font=self.f_small, text_color=BAD_COLOR, anchor="w",
            text=t("warn_incomplete"))
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
        left = ctk.CTkFrame(ar, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")
        self._ghost(left, t("btn_settings"), self.open_settings, width=100).pack(side="left")
        self.open_notion_btn = self._ghost(
            left, t("btn_open_notion"), self.open_notion_db, width=132)
        self.open_notion_btn.pack(side="left", padx=(8, 0))
        self.sync_btn = self._accent(ar, t("btn_sync"), self.sync)
        self.sync_btn.configure(width=168, height=40)
        self.sync_btn.grid(row=0, column=2, sticky="e")
        # Enable "Open in Notion" only once a database id is known; keep it in
        # sync as the id changes (e.g. after the first sync auto-creates a DB).
        self._update_open_notion_state()
        self.dbid.trace_add("write", self._update_open_notion_state)

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
            lc, text="▸ " + t("log_label"), command=self._toggle_log, font=self.f_section,
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
        self.notion_setup.set(t("acct_set") if self.token.get().strip()
                              else t("acct_unset"))
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
            self.cookies_status.set(t("acct_set"))
        else:
            self.cookies_status.set(t("acct_unset"))
            # Invalidate any in-flight probe so its late result can't re-show
            # "接続OK" after the cookies were cleared.
            self._check_epoch += 1
            self._set_validity("", MUTED)  # no cookies → nothing to validate
        win = self._settings_win
        if win is not None and win.winfo_exists():
            win.refresh_cookie_buttons(saved)
        # Kindle sign-in is half of the sync gate — re-evaluate the button/banner.
        self._update_ready_state()

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
                messagebox.showinfo(t("mb_check_title"), t("mb_import_first"))
            return
        self._check_epoch += 1
        epoch = self._check_epoch
        self._set_check_btn_state("disabled")
        self._set_validity(t("checking"), MUTED)
        threading.Thread(target=self._run_check, args=(epoch,), daemon=True).start()

    def _run_check(self, epoch):
        """Worker: probe the saved cookies and update the validity label on the UI thread.

        Results are routed through _apply_check/_finish_check so a probe that
        finishes after the cookies were cleared (or a newer probe started) is
        discarded instead of overwriting the current status.
        """
        try:
            ok = core.check_cookies(str(core.get_cookies_path()), log=lambda *_: None)
            if ok:
                self.root.after(0, self._apply_check, epoch, t("conn_ok"), OK_COLOR)
            else:
                self.root.after(
                    0, self._apply_check, epoch, t("cookies_expired"), BAD_COLOR)
        except Exception:
            self.root.after(
                0, self._apply_check, epoch, t("conn_failed"), MUTED)
        finally:
            self.root.after(0, self._finish_check, epoch)

    def _apply_check(self, epoch, text, color):
        """Apply a probe result only if it's still the current one (UI thread)."""
        if epoch == self._check_epoch:
            self._set_validity(text, color)

    def _finish_check(self, epoch):
        """Re-enable the 接続確認 button after the current probe, if cookies remain."""
        if epoch == self._check_epoch and core.has_saved_cookies():
            self._set_check_btn_state("normal")

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
        self.notion_setup.set(t("acct_set") if token else t("acct_unset"))
        if not token:
            self._set_notion_validity("", MUTED)
            return
        self._set_notion_validity(t("checking"), MUTED)
        threading.Thread(
            target=self._run_notion_check, args=(token,), daemon=True).start()

    def _run_notion_check(self, token):
        """Worker: validate the Notion token and update the Notion status on the UI thread."""
        try:
            ok = core.check_notion(token)
            if ok:
                self.root.after(0, self._set_notion_validity, t("conn_ok"), OK_COLOR)
            else:
                self.root.after(
                    0, self._set_notion_validity,
                    t("token_invalid"), BAD_COLOR)
        except Exception:
            self.root.after(
                0, self._set_notion_validity,
                t("conn_failed"), MUTED)

    def _set_appearance(self, choice):
        self.appearance_mode.set(choice)
        # Live preview only — persisted on save, reverted on cancel. SettingsDialog
        # overrides the title-bar recolor so switching the theme no longer
        # withdraws the open dialog. `choice` is a localized label; map it back.
        ctk.set_appearance_mode(theme_value(choice))

    def _notion_ready(self) -> bool:
        """Notion is set up once the token and parent-page URL are present (DB ID is optional)."""
        return bool(self.token.get().strip()) and bool(self.parent.get().strip())

    def _kindle_ready(self) -> bool:
        """Kindle is set up once a sign-in (cookies) has been saved."""
        return core.has_saved_cookies()

    def _settings_ready(self) -> bool:
        """Sync needs BOTH accounts configured: Notion (token + parent URL) and Kindle (signed in)."""
        return self._notion_ready() and self._kindle_ready()

    def _update_ready_state(self, *_):
        """Enable sync only when both accounts are configured; else show what's missing."""
        notion_ok, kindle_ok = self._notion_ready(), self._kindle_ready()
        if notion_ok and kindle_ok:
            self.warn.grid_remove()
            self.sync_btn.configure(state="normal")
        else:
            if not notion_ok and not kindle_ok:
                key = "warn_need_both"
            elif not kindle_ok:
                key = "warn_need_kindle"
            else:
                key = "warn_incomplete"
            self.warn.configure(text=t(key))
            self.warn.grid()
            self.sync_btn.configure(state="disabled")

    def open_notion_db(self):
        """Open the configured Notion database in the default browser."""
        url = core.database_url(self.dbid.get())
        if url:
            webbrowser.open(url)

    def _update_open_notion_state(self, *_):
        """Enable the 'Open in Notion' button only when a database id is set."""
        state = "normal" if core.database_url(self.dbid.get()) else "disabled"
        try:
            self.open_notion_btn.configure(state=state)
        except Exception:
            pass

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

    def _clear_cookies(self):
        """Delete the app's saved cookies."""
        if not core.has_saved_cookies():
            return
        if not messagebox.askyesno(t("mb_confirm_title"), t("mb_clear_confirm")):
            return
        core.clear_saved_cookies()
        self._refresh_cookie_status()
        self.log(t("log_cookie_cleared"))

    # -- in-app Kindle login (Windows / WebView2) ---------------------------
    def _kindle_login(self):
        """Open an in-app browser to sign in to Amazon and harvest the cookies."""
        self._set_login_running(True)
        threading.Thread(target=self._run_kindle_login, daemon=True).start()

    def _run_kindle_login(self):
        """Worker thread: run the login subprocess (own process = own main thread
        for pywebview) and wait for it, off the Tk event loop."""
        ok = False
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--kindle-login"]
            else:
                cmd = [sys.executable, str(Path(sys.argv[0]).resolve()), "--kindle-login"]
            flags = 0x08000000 if sys.platform.startswith("win") else 0  # CREATE_NO_WINDOW
            ok = subprocess.run(cmd, creationflags=flags).returncode == 0
        except Exception as e:
            self.log(t("log_error").format(e=e))
        self.root.after(0, self._after_kindle_login, ok)

    def _after_kindle_login(self, ok):
        self._set_login_running(False)
        self._refresh_cookie_status()
        if ok:
            self._check_cookies(silent=True)  # validate the freshly saved cookies
        else:
            self._set_validity(t("login_cancelled"), MUTED)

    def _set_login_running(self, on):
        """Disable the login button + show a status while the browser window is open."""
        win = self._settings_win
        if win is not None and win.winfo_exists():
            try:
                win.login_btn.configure(state="disabled" if on else "normal")
            except Exception:
                pass
        if on:
            self.cookies_status.set(t("login_running"))

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
            self.log_toggle.configure(text="▾ " + t("log_label"))
            self.outer.rowconfigure(5, weight=1)  # fill remaining space
            w, _ = self._logical_wh()
            self.root.geometry(f"{w}x{self._expanded_h}")  # restore expanded height
        else:
            self._expanded_h = self._logical_wh()[1]  # remember it for next expand
            self.logbox.grid_remove()
            self.log_toggle.configure(text="▸ " + t("log_label"))
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
        """Snapshot the current settings (plus last_sync) into a config dict for saving."""
        cfg = {
            "notion_token": self.token.get().strip(),
            "notion_parent_page_id": self.parent.get().strip(),
            "notion_database_id": self.dbid.get().strip(),
            "notify_on_complete": bool(self.notify_on_complete.get()),
            "appearance_mode": theme_value(self.appearance_mode.get()),
            "ui_language": langpref_value(self.ui_language.get()),
        }
        if self.last_sync:
            cfg["last_sync"] = self.last_sync
        return cfg

    def save(self):
        core.save_config(self._cfg_from_fields())
        self.log(t("log_config_saved").format(path=core.get_config_path()))

    def _update_last_sync_label(self):
        """Show the header's 'last sync' summary from self.last_sync (or hide it)."""
        ls = self.last_sync
        if not ls:
            self.last_sync_lbl.configure(text="")
            return
        try:
            dt = datetime.fromtimestamp(int(ls.get("at", 0)))
            when = f"{dt.month}/{dt.day} {dt.hour:02d}:{dt.minute:02d}"
        except Exception:
            when = "?"
        summary = t("summary_fmt").format(
            inserted=ls.get("inserted", 0), skipped=ls.get("skipped", 0),
            failed=ls.get("failed", 0))
        self.last_sync_lbl.configure(text=f"{t('last_sync_label')}: {when} · {summary}")

    def _record_last_sync(self):
        """Persist the last-sync record (quietly, no log) and refresh the header."""
        try:
            core.save_config(self._cfg_from_fields())
        except Exception:
            pass
        self._update_last_sync_label()

    def sync(self):
        """Persist settings, then run the sync on a worker thread (needs token + parent URL)."""
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
        """Worker thread: run the end-to-end sync, then report result, progress, and last-sync."""
        try:
            cfg = self._cfg_from_fields()
            if not core.has_saved_cookies():
                raise RuntimeError(t("sync_err_cookies"))
            cookies_file = str(core.get_cookies_path())
            res = core.run_sync(
                cfg, cookies_file, None, log=self.log, progress=self.on_progress
            )
            self.root.after(0, lambda: self.dbid.set(cfg.get("notion_database_id", "")))
            summary = t("summary_fmt").format(
                inserted=res["inserted"], skipped=res["skipped"], failed=res["failed"])
            self.log(t("log_done").format(total=res["total"], summary=summary))
            self.last_sync = {
                "at": int(datetime.now().timestamp()),
                "total": res["total"], "inserted": res["inserted"],
                "skipped": res["skipped"], "failed": res["failed"],
            }
            self.root.after(0, self._record_last_sync)
            self.root.after(0, self._finish_progress, t("prog_done"))
            if self._notify_pref:
                desktop_notify(t("notif_done_title"), summary)
        except Exception as e:
            self.log(t("log_error").format(e=e))
            self.root.after(0, self._finish_progress, t("prog_error"))
            if self._notify_pref:
                desktop_notify(t("notif_err_title"), str(e))
        finally:
            self._syncing = False
            self.root.after(0, self._update_ready_state)

    def _on_close(self):
        """Confirm before quitting mid-sync; a normal close just exits."""
        if self._syncing:
            if not messagebox.askyesno(
                    t("mb_syncing_title"), t("mb_quit_confirm")):
                return
        self.root.destroy()


def main():
    """Application entry point (and the ``--kindle-login`` subprocess dispatcher)."""
    # Subprocess entry: open the in-app Kindle login (WebView2) and exit. This
    # runs in its own process so pywebview can own the main thread (see App._run_
    # kindle_login), leaving the Tk GUI's event loop untouched.
    if "--kindle-login" in sys.argv:
        import kindle_login

        raise SystemExit(kindle_login.run())
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
