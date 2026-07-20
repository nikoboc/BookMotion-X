#!/usr/bin/env python3
"""Tkinter GUI for the Kindle → Notion app (Level 3 packaged .app entry point).

Enter your Notion token / parent page / cookies right in the window — no file
editing. Values are saved to config.json (Application Support when packaged).
"""
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import kindle_notion as core

BROWSERS = ["chrome", "safari", "edge", "brave", "firefox"]


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Kindle → Notion")
        root.geometry("660x580")
        cfg = core.load_config()

        self.token = tk.StringVar(value=cfg.get("notion_token", ""))
        self.parent = tk.StringVar(value=cfg.get("notion_parent_page_id", ""))
        self.dbid = tk.StringVar(value=cfg.get("notion_database_id", ""))
        self.cookie_mode = tk.StringVar(value="file")  # 'file' | 'browser'
        self.cookies_file = tk.StringVar(value="")
        self.browser = tk.StringVar(value="chrome")
        self.test_mode = tk.BooleanVar(value=False)
        self.show_token = tk.BooleanVar(value=False)
        self._build()

    def _build(self):
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        r = 0
        ttk.Label(frm, text="Notion トークン").grid(row=r, column=0, sticky="w", **pad)
        self.token_entry = ttk.Entry(frm, textvariable=self.token, show="•")
        self.token_entry.grid(row=r, column=1, sticky="we", **pad)
        ttk.Checkbutton(frm, text="表示", variable=self.show_token,
                        command=self._toggle_token).grid(row=r, column=2, **pad)

        r += 1
        ttk.Label(frm, text="親ページ URL").grid(row=r, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.parent).grid(row=r, column=1, columnspan=2, sticky="we", **pad)

        r += 1
        ttk.Label(frm, text="DB ID（任意）").grid(row=r, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.dbid).grid(row=r, column=1, columnspan=2, sticky="we", **pad)

        r += 1
        ttk.Separator(frm, orient="horizontal").grid(row=r, column=0, columnspan=3, sticky="we", pady=8)

        r += 1
        ttk.Label(frm, text="Cookie 取得元").grid(row=r, column=0, sticky="w", **pad)
        cf = ttk.Frame(frm)
        cf.grid(row=r, column=1, columnspan=2, sticky="w", **pad)
        ttk.Radiobutton(cf, text="cookies.txt", variable=self.cookie_mode, value="file").pack(side="left")
        ttk.Radiobutton(cf, text="ブラウザから自動", variable=self.cookie_mode, value="browser").pack(side="left", padx=(10, 0))

        r += 1
        ttk.Label(frm, text="cookies.txt").grid(row=r, column=0, sticky="w", **pad)
        ff = ttk.Frame(frm)
        ff.grid(row=r, column=1, columnspan=2, sticky="we", **pad)
        ttk.Entry(ff, textvariable=self.cookies_file).pack(side="left", fill="x", expand=True)
        ttk.Button(ff, text="選択…", command=self._pick_cookies).pack(side="left", padx=(6, 0))

        r += 1
        ttk.Label(frm, text="ブラウザ").grid(row=r, column=0, sticky="w", **pad)
        ttk.Combobox(frm, textvariable=self.browser, values=BROWSERS, state="readonly",
                     width=12).grid(row=r, column=1, sticky="w", **pad)

        r += 1
        ttk.Checkbutton(frm, text="テスト（先頭1冊だけ）", variable=self.test_mode).grid(
            row=r, column=1, sticky="w", **pad)

        r += 1
        bf = ttk.Frame(frm)
        bf.grid(row=r, column=0, columnspan=3, sticky="w", pady=(8, 4), padx=8)
        ttk.Button(bf, text="保存", command=self.save).pack(side="left")
        self.sync_btn = ttk.Button(bf, text="Notion へ同期", command=self.sync)
        self.sync_btn.pack(side="left", padx=(8, 0))

        r += 1
        self.logbox = scrolledtext.ScrolledText(frm, height=14, wrap="word")
        self.logbox.grid(row=r, column=0, columnspan=3, sticky="nsew", **pad)
        frm.rowconfigure(r, weight=1)

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
            res = core.run_sync(cfg, cookies_file, browser, limit, log=self.log)
            self.root.after(0, lambda: self.dbid.set(cfg.get("notion_database_id", "")))
            self.log(
                f"完了: 対象 {res['total']} / 新規 {res['inserted']} / "
                f"重複 {res['skipped']} / 失敗 {res['failed']}"
            )
        except Exception as e:
            self.log("エラー: " + str(e))
        finally:
            self.root.after(0, lambda: self.sync_btn.config(state="normal"))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
