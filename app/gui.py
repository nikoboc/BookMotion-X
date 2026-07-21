#!/usr/bin/env python3
"""CustomTkinter GUI for the Kindle → Notion app (Level 3 packaged .app entry point).

Enter your Notion token / parent page / cookies right in the window — no file
editing. Values are saved to config.json (Application Support when packaged).
"""
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


class App:
    def __init__(self, root: ctk.CTk):
        self.root = root
        root.title("Kindle → Notion")
        root.geometry("720x820")
        root.minsize(640, 700)
        cfg = core.load_config()
        self._indeterminate = False

        self.token = tk.StringVar(value=cfg.get("notion_token", ""))
        self.parent = tk.StringVar(value=cfg.get("notion_parent_page_id", ""))
        self.dbid = tk.StringVar(value=cfg.get("notion_database_id", ""))
        self.cookies_status = tk.StringVar(value="")
        self.cookies_valid = tk.StringVar(value="")

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

    # -- fonts ---------------------------------------------------------------
    def _setup_fonts(self):
        reg, med = _resolve_fonts(self.root)
        self.f_title = ctk.CTkFont(family=reg, size=22, weight="bold")
        self.f_sub = ctk.CTkFont(family=reg, size=13)
        self.f_body = ctk.CTkFont(family=reg, size=13)
        self.f_small = ctk.CTkFont(family=reg, size=12)
        self.f_log = ctk.CTkFont(family=reg, size=12)
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
        self.outer.rowconfigure(5, weight=1)

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
        self.appearance = ctk.CTkOptionMenu(
            hdr, values=list(APPEARANCE), width=112, font=self.f_small,
            command=self._set_appearance, fg_color=ACCENT, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER)
        self.appearance.set("システム")
        self.appearance.grid(row=0, column=1, sticky="e")

        # --- card: Notion 接続 ---
        c1 = self._card(1, "Notion 接続")
        self._label(c1, "Notion トークン", 1)
        self.token_entry = ctk.CTkEntry(c1, textvariable=self.token, show="•",
                                        font=self.f_body)
        self.token_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=6)
        ctk.CTkCheckBox(c1, text="表示", variable=self.show_token, width=52,
                        command=self._toggle_token, font=self.f_small).grid(
            row=1, column=2, sticky="w", padx=(0, 16), pady=6)

        self._label(c1, "親ページ URL", 2)
        ctk.CTkEntry(c1, textvariable=self.parent, font=self.f_body).grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=(0, 16), pady=6)

        self._label(c1, "DB ID（任意）", 3)
        ctk.CTkEntry(c1, textvariable=self.dbid, font=self.f_body).grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=(0, 16), pady=(6, 16))

        # --- card: 取得設定 ---
        c2 = self._card(2, "取得設定")
        self._label(c2, "Cookie（cookies.txt）", 1)
        ff = ctk.CTkFrame(c2, fg_color="transparent")
        ff.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 16), pady=(6, 16))
        ff.columnconfigure(0, weight=1)
        self.cookies_status_lbl = ctk.CTkLabel(
            ff, textvariable=self.cookies_status, font=self.f_small,
            text_color=MUTED, anchor="w")
        self.cookies_status_lbl.grid(row=0, column=0, sticky="w")
        self.cookies_check_btn = self._ghost(
            ff, "接続確認", self._check_cookies, width=88)
        self.cookies_check_btn.grid(row=0, column=1, padx=(8, 0))
        self.cookies_btn = self._ghost(ff, "取り込み…", self._import_cookies, width=104)
        self.cookies_btn.grid(row=0, column=2, padx=(8, 0))
        self.cookies_clear_btn = self._ghost(ff, "クリア", self._clear_cookies, width=72)
        self.cookies_clear_btn.grid(row=0, column=3, padx=(8, 0))
        # Second line: cookie validity (colored). Empty until checked.
        self.cookies_valid_lbl = ctk.CTkLabel(
            ff, textvariable=self.cookies_valid, font=self.f_small,
            text_color=MUTED, anchor="w")
        self.cookies_valid_lbl.grid(row=1, column=0, columnspan=4, sticky="w",
                                    pady=(6, 0))

        # --- action row ---
        ar = ctk.CTkFrame(self.outer, fg_color="transparent")
        ar.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        ar.columnconfigure(1, weight=1)
        self._ghost(ar, "保存", self.save, width=104).grid(row=0, column=0, sticky="w")
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

        # --- log card ---
        lc = self._card(5, "ログ", expand=True)
        lc.rowconfigure(1, weight=1)
        self.logbox = ctk.CTkTextbox(lc, font=self.f_log, corner_radius=8, wrap="word")
        self.logbox.grid(row=1, column=0, columnspan=3, sticky="nsew",
                         padx=16, pady=(0, 16))

        # Reflect the saved-cookie status on the Cookie row.
        self._refresh_cookie_status()
        # Notice an expired cookie without waiting for a full sync: probe once at
        # startup (in the background) if we have saved cookies.
        if core.has_saved_cookies():
            self.root.after(400, lambda: self._check_cookies(silent=True))

    # -- appearance ----------------------------------------------------------
    def _refresh_cookie_status(self):
        """Show whether cookies are saved and enable Clear/Check only when they are."""
        saved = core.has_saved_cookies()
        n = core.saved_cookies_count()
        if saved:
            self.cookies_status.set(f"取り込み済み（{n} 件）" if n else "取り込み済み")
        else:
            self.cookies_status.set("未取り込み")
            self._set_validity("", MUTED)  # no cookies → nothing to validate
        self.cookies_clear_btn.configure(state="normal" if saved else "disabled")
        self.cookies_check_btn.configure(state="normal" if saved else "disabled")

    def _set_validity(self, text, color):
        """Update the colored validity line (runs on the UI thread)."""
        self.cookies_valid.set(text)
        self.cookies_valid_lbl.configure(text_color=color)

    def _check_cookies(self, silent=False):
        """Probe Amazon to see whether the saved cookies still log us in.

        silent=True is used for the automatic startup check: it skips the
        "import first" dialog so a fresh install stays quiet.
        """
        if not core.has_saved_cookies():
            if not silent:
                messagebox.showinfo("接続確認", "先に cookies.txt を取り込んでください。")
            return
        self.cookies_check_btn.configure(state="disabled")
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
                    "✕ 期限切れ — 「取り込み…」から新しい cookies.txt を入れ直してください",
                    BAD_COLOR)
        except Exception:
            self.root.after(
                0, self._set_validity,
                "接続を確認できませんでした（ネットワーク未接続など）", MUTED)
        finally:
            self.root.after(
                0, lambda: self.cookies_check_btn.configure(state="normal"))

    def _set_appearance(self, choice):
        ctk.set_appearance_mode(APPEARANCE.get(choice, "system"))

    def _toggle_token(self):
        self.token_entry.configure(show="" if self.show_token.get() else "•")

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

    def log(self, msg):
        self.root.after(0, self._append, str(msg))

    def _append(self, msg):
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
        }

    def save(self):
        core.save_config(self._cfg_from_fields())
        self.log("設定を保存しました: " + str(core.get_config_path()))

    def sync(self):
        if not self.token.get().strip():
            messagebox.showerror("エラー", "Notion トークンを入力してください")
            return
        self.save()
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
            self.log(
                f"完了: 対象 {res['total']} / 新規 {res['inserted']} / "
                f"重複 {res['skipped']} / 失敗 {res['failed']}"
            )
            self.root.after(0, self._finish_progress, "完了")
        except Exception as e:
            self.log("エラー: " + str(e))
            self.root.after(0, self._finish_progress, "エラー")
        finally:
            self.root.after(0, lambda: self.sync_btn.configure(state="normal"))


def main():
    register_bundled_fonts()  # before ctk.CTk() so Tk sees the new families
    ctk.set_default_color_theme("blue")
    ctk.set_appearance_mode("system")
    root = ctk.CTk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
