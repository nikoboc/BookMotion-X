#!/usr/bin/env python3
"""Tkinter GUI for the Kindle → Notion app (Level 3 packaged .app entry point).

Enter your Notion token / parent page / cookies right in the window — no file
editing. Values are saved to config.json (Application Support when packaged).
"""
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox, scrolledtext

import kindle_notion as core

BROWSERS = ["chrome", "safari", "edge", "brave", "firefox"]

# --- modern palette ---------------------------------------------------------
BG = "#EEF1F5"        # window background
CARD = "#FFFFFF"      # card surface
TEXT = "#1F2933"      # primary text
MUTED = "#6B7280"     # secondary text
BORDER = "#E2E8F0"    # hairline borders
FIELD = "#F1F5F9"     # input fill
ACCENT = "#4F46E5"    # primary action (indigo)
ACCENT_HOVER = "#4338CA"
ACCENT_ACTIVE = "#3730A3"


def _resolve_fonts(root):
    """Pick UI font families. Windows → Noto Sans JP; macOS → the system font.

    Returns (regular_family, medium_family). medium_family == regular_family
    when no distinct medium-weight face exists (macOS/Linux), in which case the
    caller falls back to a bold weight for emphasis.
    """
    fams = set(tkfont.families(root))
    if sys.platform == "darwin":
        # Match the OS: reuse whatever family Tk's default (system) font resolves to.
        try:
            base = tkfont.nametofont("TkDefaultFont").actual("family")
        except Exception:
            base = "Helvetica Neue"
        return base, base
    if sys.platform.startswith("win"):
        reg = next((f for f in ("Noto Sans JP", "Yu Gothic UI", "Meiryo UI", "Segoe UI")
                    if f in fams), "Segoe UI")
        med = ("Noto Sans JP Medium"
               if reg == "Noto Sans JP" and "Noto Sans JP Medium" in fams else reg)
        return reg, med
    reg = next((f for f in ("Noto Sans CJK JP", "Noto Sans JP", "Noto Sans")
                if f in fams), "TkDefaultFont")
    return reg, reg


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Kindle → Notion")
        root.geometry("680x680")
        root.minsize(600, 560)
        root.configure(bg=BG)
        cfg = core.load_config()
        self._indeterminate = False

        self.token = tk.StringVar(value=cfg.get("notion_token", ""))
        self.parent = tk.StringVar(value=cfg.get("notion_parent_page_id", ""))
        self.dbid = tk.StringVar(value=cfg.get("notion_database_id", ""))
        self.cookie_mode = tk.StringVar(value="file")  # 'file' | 'browser'
        self.cookies_file = tk.StringVar(value="")
        self.browser = tk.StringVar(value="chrome")
        self.test_mode = tk.BooleanVar(value=False)
        self.show_token = tk.BooleanVar(value=False)

        self._setup_style()
        self._build()

    # -- theming --------------------------------------------------------------
    def _setup_style(self):
        reg, med = _resolve_fonts(self.root)
        self.fam = reg
        self.f_base = (reg, 10)
        self.f_small = (reg, 9)
        self.f_sub = (reg, 10)
        self.f_head = (reg, 17, "bold")
        # Prefer a true Medium face for headings/buttons; else fall back to bold.
        self.f_section = (med, 11) if med != reg else (reg, 11, "bold")
        self.f_btn = (med, 10) if med != reg else (reg, 10, "bold")

        st = ttk.Style()
        st.theme_use("clam")

        # labels
        st.configure("Card.TLabel", background=CARD, foreground=TEXT, font=self.f_base)
        st.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=self.f_small)
        st.configure("Section.TLabel", background=CARD, foreground=TEXT, font=self.f_section)

        # entries
        st.configure(
            "Modern.TEntry",
            fieldbackground=FIELD, background=FIELD, foreground=TEXT,
            bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
            insertcolor=TEXT, borderwidth=1, padding=7,
        )
        st.map("Modern.TEntry",
               bordercolor=[("focus", ACCENT)],
               lightcolor=[("focus", ACCENT)],
               darkcolor=[("focus", ACCENT)])

        # combobox
        st.configure(
            "Modern.TCombobox",
            fieldbackground=FIELD, background=FIELD, foreground=TEXT,
            bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
            arrowcolor=MUTED, borderwidth=1, padding=5,
        )
        st.map("Modern.TCombobox",
               fieldbackground=[("readonly", FIELD)],
               bordercolor=[("focus", ACCENT)])

        # radios / checks on cards
        st.configure("Card.TRadiobutton", background=CARD, foreground=TEXT, font=self.f_base)
        st.map("Card.TRadiobutton", background=[("active", CARD)], foreground=[("active", TEXT)])
        st.configure("Card.TCheckbutton", background=CARD, foreground=TEXT, font=self.f_base)
        st.map("Card.TCheckbutton", background=[("active", CARD)], foreground=[("active", TEXT)])

        # primary (accent) button
        st.configure(
            "Accent.TButton",
            background=ACCENT, foreground="#FFFFFF", font=self.f_btn,
            borderwidth=0, focusthickness=0, padding=(18, 9),
        )
        st.map("Accent.TButton",
               background=[("pressed", ACCENT_ACTIVE), ("active", ACCENT_HOVER),
                          ("disabled", "#A5B4FC")],
               foreground=[("disabled", "#EEF2FF")])

        # secondary button
        st.configure(
            "Secondary.TButton",
            background="#FFFFFF", foreground=TEXT, font=self.f_btn,
            bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
            borderwidth=1, focusthickness=0, padding=(14, 8),
        )
        st.map("Secondary.TButton",
               background=[("pressed", "#E2E8F0"), ("active", "#F1F5F9")],
               bordercolor=[("active", "#CBD5E1")])

        # progress bar (thin, accent)
        st.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor=BORDER, background=ACCENT,
            bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT,
            thickness=6, borderwidth=0,
        )

    # -- card helper ----------------------------------------------------------
    def _card(self, parent, title):
        card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                        highlightthickness=1, bd=0)
        card.pack(fill="x", pady=(0, 14))
        ttk.Label(card, text=title, style="Section.TLabel").pack(
            anchor="w", padx=16, pady=(14, 2))
        body = tk.Frame(card, bg=CARD)
        body.pack(fill="both", expand=True, padx=16, pady=(6, 16))
        body.columnconfigure(1, weight=1)
        return body

    def _build(self):
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True, padx=22, pady=20)

        # header
        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x", pady=(0, 16))
        tk.Label(head, text="📚  Kindle → Notion", bg=BG, fg=TEXT,
                 font=self.f_head).pack(anchor="w")
        tk.Label(head, text="Kindle のハイライトを Notion データベースに同期します",
                 bg=BG, fg=MUTED, font=self.f_sub).pack(anchor="w", pady=(2, 0))

        pad = {"padx": 6, "pady": 6}

        # --- card: Notion 接続 ---
        c1 = self._card(outer, "Notion 接続")
        r = 0
        ttk.Label(c1, text="Notion トークン", style="Card.TLabel").grid(
            row=r, column=0, sticky="w", **pad)
        self.token_entry = ttk.Entry(c1, textvariable=self.token, show="•",
                                     style="Modern.TEntry")
        self.token_entry.grid(row=r, column=1, sticky="we", **pad)
        ttk.Checkbutton(c1, text="表示", variable=self.show_token,
                        command=self._toggle_token,
                        style="Card.TCheckbutton").grid(row=r, column=2, **pad)

        r += 1
        ttk.Label(c1, text="親ページ URL", style="Card.TLabel").grid(
            row=r, column=0, sticky="w", **pad)
        ttk.Entry(c1, textvariable=self.parent, style="Modern.TEntry").grid(
            row=r, column=1, columnspan=2, sticky="we", **pad)

        r += 1
        ttk.Label(c1, text="DB ID（任意）", style="Card.TLabel").grid(
            row=r, column=0, sticky="w", **pad)
        ttk.Entry(c1, textvariable=self.dbid, style="Modern.TEntry").grid(
            row=r, column=1, columnspan=2, sticky="we", **pad)

        # --- card: 取得設定 ---
        c2 = self._card(outer, "取得設定")
        r = 0
        ttk.Label(c2, text="Cookie 取得元", style="Card.TLabel").grid(
            row=r, column=0, sticky="w", **pad)
        cf = tk.Frame(c2, bg=CARD)
        cf.grid(row=r, column=1, columnspan=2, sticky="w", **pad)
        ttk.Radiobutton(cf, text="cookies.txt", variable=self.cookie_mode,
                        value="file", style="Card.TRadiobutton").pack(side="left")
        ttk.Radiobutton(cf, text="ブラウザから自動", variable=self.cookie_mode,
                        value="browser", style="Card.TRadiobutton").pack(
            side="left", padx=(14, 0))

        r += 1
        ttk.Label(c2, text="cookies.txt", style="Card.TLabel").grid(
            row=r, column=0, sticky="w", **pad)
        ff = tk.Frame(c2, bg=CARD)
        ff.grid(row=r, column=1, columnspan=2, sticky="we", **pad)
        ttk.Entry(ff, textvariable=self.cookies_file, style="Modern.TEntry").pack(
            side="left", fill="x", expand=True)
        ttk.Button(ff, text="選択…", command=self._pick_cookies,
                   style="Secondary.TButton").pack(side="left", padx=(8, 0))

        r += 1
        ttk.Label(c2, text="ブラウザ", style="Card.TLabel").grid(
            row=r, column=0, sticky="w", **pad)
        ttk.Combobox(c2, textvariable=self.browser, values=BROWSERS,
                     state="readonly", width=14,
                     style="Modern.TCombobox").grid(row=r, column=1, sticky="w", **pad)

        r += 1
        ttk.Checkbutton(c2, text="テスト（先頭 1 冊だけ）", variable=self.test_mode,
                        style="Card.TCheckbutton").grid(
            row=r, column=1, columnspan=2, sticky="w", **pad)

        # --- action row ---
        bf = tk.Frame(outer, bg=BG)
        bf.pack(fill="x", pady=(0, 14))
        bf.columnconfigure(1, weight=1)
        ttk.Button(bf, text="保存", command=self.save,
                   style="Secondary.TButton").grid(row=0, column=0, sticky="w")
        self.sync_btn = ttk.Button(bf, text="Notion へ同期", command=self.sync,
                                   style="Accent.TButton")
        self.sync_btn.grid(row=0, column=2, sticky="e")

        # --- progress ---
        pf = tk.Frame(outer, bg=BG)
        pf.pack(fill="x", pady=(0, 14))
        pf.columnconfigure(0, weight=1)
        self.pbar = ttk.Progressbar(pf, mode="determinate",
                                    style="Accent.Horizontal.TProgressbar")
        self.pbar.grid(row=0, column=0, sticky="we")
        self.status = tk.Label(pf, text="", bg=BG, fg=MUTED, font=self.f_small)
        self.status.grid(row=1, column=0, sticky="w", pady=(4, 0))

        # --- log card ---
        lc = tk.Frame(outer, bg=CARD, highlightbackground=BORDER,
                      highlightthickness=1, bd=0)
        lc.pack(fill="both", expand=True)
        ttk.Label(lc, text="ログ", style="Section.TLabel").pack(
            anchor="w", padx=16, pady=(14, 4))
        self.logbox = scrolledtext.ScrolledText(
            lc, height=10, wrap="word", relief="flat", borderwidth=0,
            bg=CARD, fg=TEXT, insertbackground=TEXT,
            font=(self.fam, 10), padx=6, pady=4,
        )
        self.logbox.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _toggle_token(self):
        self.token_entry.config(show="" if self.show_token.get() else "•")

    def _pick_cookies(self):
        p = filedialog.askopenfilename(
            title="cookies.txt を選択",
            filetypes=[("cookies.txt", "*.txt"), ("すべて", "*.*")],
        )
        if p:
            self.cookies_file.set(p)

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
                self._indeterminate = False
            self.pbar.config(mode="determinate", maximum=total, value=current)
            self.status.config(text=f"{phase} {current}/{total}")
        else:
            if not self._indeterminate:
                self.pbar.config(mode="indeterminate")
                self.pbar.start(12)
                self._indeterminate = True
            self.status.config(text=phase + " …")

    def _reset_progress(self):
        if self._indeterminate:
            self.pbar.stop()
            self._indeterminate = False
        self.pbar.config(mode="determinate", maximum=100, value=0)
        self.status.config(text="")

    def _finish_progress(self, text):
        if self._indeterminate:
            self.pbar.stop()
            self._indeterminate = False
        self.pbar.config(mode="determinate", maximum=100, value=100)
        self.status.config(text=text)

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
        self.sync_btn.config(state="disabled")
        self._reset_progress()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            cfg = self._cfg_from_fields()
            use_file = self.cookie_mode.get() == "file"
            cookies_file = self.cookies_file.get().strip() if use_file else None
            browser = None if use_file else self.browser.get()
            if use_file and not cookies_file:
                raise RuntimeError("cookies.txt を選択してください。")
            limit = 1 if self.test_mode.get() else None
            res = core.run_sync(
                cfg, cookies_file, browser, limit, log=self.log, progress=self.on_progress
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
            self.root.after(0, lambda: self.sync_btn.config(state="normal"))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
