#!/usr/bin/env python3
"""Kindle highlights → Notion, as a standalone (Mac click-to-run) app.

Browser-free: it talks to read.amazon.co.jp directly with `requests`, using the
login cookies from an exported cookies.txt.

The library sidebar is paginated server-side via `/notebook?library=list`
(+ a `token`), so we loop that to get every book — no headless browser needed.
Each book's highlights come from `/notebook?asin=...`. Everything is then
pushed into a Notion database.

Being an ordinary process, it is not throttled when you switch to another app.

Config lives in ~/.booklight/config.json (formerly ~/.kindle-notion).
"""
from __future__ import annotations

import argparse
import json
import locale
import os
import re
import shutil
import sys
import time
from datetime import date
from http.cookiejar import MozillaCookieJar
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://read.amazon.co.jp"
NOTEBOOK = f"{BASE}/notebook"
NOTION_VERSION = "2022-06-28"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

COLOR_JA = {"yellow": "黄色", "blue": "青", "pink": "ピンク", "orange": "オレンジ"}


# ---- cooperative cancellation ------------------------------------------------
class SyncCancelled(Exception):
    """Raised from inside a sync when the caller's ``should_cancel()`` turns true.

    The GUI passes ``should_cancel=<threading.Event>.is_set`` and shows a 中断
    (stop) button during the sync; when the user confirms, the event is set and
    the next checkpoint in the fetch / insert loops unwinds the sync by raising
    this. ``inserted`` / ``failed`` carry however many Notion rows were written
    before the stop (both 0 when cancelled during the Kindle fetch, before any
    insert), so the caller can report partial progress. Already-written rows are
    left in place and are skipped by dedup on the next run.
    """

    def __init__(self, inserted: int = 0, failed: int = 0):
        super().__init__("sync cancelled")
        self.inserted = inserted
        self.failed = failed


def _raise_if_cancelled(should_cancel, inserted: int = 0, failed: int = 0) -> None:
    """Checkpoint: raise SyncCancelled if the caller asked to stop. No-op when
    ``should_cancel`` is None (e.g. the CLI, which has no stop button)."""
    if should_cancel and should_cancel():
        raise SyncCancelled(inserted, failed)


# ---- UI language for runtime messages (progress / log / errors) --------------
# NOTE: this covers only user-facing *messages*. The Notion database schema
# (property names like 注釈ID and the マーカー色 option names) is data written
# into the user's database and is intentionally NOT translated — renaming it
# would break dedup/appends against existing databases.
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


LANG = "ja"


def set_language(lang):
    """Set the language for runtime messages. 'ja'/'en' set it directly; anything
    else (e.g. 'auto') auto-detects from the OS. The GUI passes its resolved
    language; the CLI auto-detects (or follows the saved preference)."""
    global LANG
    LANG = lang if lang in ("ja", "en") else _detect_os_lang()
    return LANG


def t(key):
    pair = _TR.get(key)
    return (pair[1] if LANG == "en" else pair[0]) if pair else key


_TR = {
    "err_no_cookies": ("cookies.txt が指定されていません。", "No cookies.txt was specified."),
    "log_cookies_loaded": ("cookies.txt から {n} 件のCookieを読み込みました",
                           "Loaded {n} cookies from cookies.txt"),
    "err_not_logged_in": (
        "ログインしていません。Cookie の有効期限が切れた可能性があります。"
        "アプリでは「Kindle にログイン」から再度サインインしてください"
        "（CLI 実行時は read.amazon.co.jp にログインし直し、新しい cookies.txt を"
        "書き出して -c で渡してください）。",
        "Not logged in — your cookies may have expired. In the app, click "
        "“Sign in to Kindle” to sign in again (for the CLI, log back in to "
        "read.amazon.co.jp, export a fresh cookies.txt, and pass it with -c)."),
    "err_fetch_books": ("本を取得できませんでした。ログイン状態を確認してください。",
                        "Couldn't fetch your books. Check that you're logged in."),
    "log_fetch_library": ("本一覧を取得中…", "Fetching your library…"),
    "prog_fetch_library": ("本一覧を取得中", "Fetching library"),
    "log_books_found": ("{n} 冊を検出", "Found {n} books"),
    "log_book_line": ("({i}/{total}) {title} … {n} 件",
                      "({i}/{total}) {title} … {n} highlights"),
    "prog_fetch_highlights": ("ハイライト取得", "Fetching highlights"),
    "err_rate_limit": ("Notion のレート制限で再試行上限に達しました。",
                       "Hit Notion's rate limit — retry limit reached."),
    "err_no_parent": ("親ページID（または既存DB ID）が未設定です。",
                      "No parent page ID (or existing DB ID) is set."),
    "log_creating_db": ("Notion データベースを作成中…", "Creating the Notion database…"),
    "log_created": ("作成: {x}", "Created: {x}"),
    "log_existing": ("既存 {n} 件を確認", "Checked {n} existing entries"),
    "log_to_insert": ("登録対象 {n} 件（重複スキップ {s} 件）",
                      "{n} to insert ({s} duplicates skipped)"),
    "prog_notion_insert": ("Notion 登録", "Inserting into Notion"),
    "log_insert_failed": ("  登録失敗: {e}", "  Insert failed: {e}"),
    "log_insert_progress": ("  Notion 登録 {i}/{total}（成功{ok}/失敗{fail}）",
                            "  Notion insert {i}/{total} (ok {ok} / failed {fail})"),
    "err_no_token": ("Notion トークンが未設定です。", "No Notion token is set."),
    "err_zero_books": ("本が0冊でした。ログイン状態を確認してください。",
                       "Found 0 books. Check that you're logged in."),
    # CLI
    "cli_help_cookies": ("エクスポート済み cookies.txt", "Exported cookies.txt"),
    "cli_help_limit": ("先頭 N 冊だけ（テスト用）", "First N books only (for testing)"),
    "cli_set_token": ("config.json に notion_token を設定してください: {path}",
                      "Set notion_token in config.json: {path}"),
    "cli_error": ("エラー:", "Error:"),
    "cli_summary": ("完了: 対象 {total} / 新規 {inserted} / 重複 {skipped} / 失敗 {failed}",
                    "Done: {total} items / New {inserted} / Dup {skipped} / Failed {failed}"),
}

SCRIPT_DIR = Path(__file__).resolve().parent
LOCAL_CONFIG = SCRIPT_DIR / "config.json"
HOME_CONFIG = Path.home() / ".booklight" / "config.json"
# Pre-rename data dir (the app was "KindleNotion"); still read for one-time
# migration so upgraded installs keep their token and Kindle login.
LEGACY_HOME_CONFIG = Path.home() / ".kindle-notion" / "config.json"
_EMPTY = {"notion_token": "", "notion_parent_page_id": "", "notion_database_id": ""}


# ---------------------------------------------------------------- config
def _migrate_legacy_data(legacy: Path, base: Path) -> None:
    """Copy config.json / cookies.txt from the pre-rename dir into ``base`` once.

    Booklight was formerly "KindleNotion", so existing installs keep their data
    in the old folder. Copy each file only if it isn't already in the new dir, so
    an upgraded user keeps their token and Kindle login without re-entering them.
    Non-destructive: the old folder is left in place as a backup.
    """
    if not legacy.exists() or legacy == base:
        return
    for name in ("config.json", "cookies.txt"):
        src, dst = legacy / name, base / name
        if src.exists() and not dst.exists():
            try:
                shutil.copyfile(src, dst)
            except OSError:
                pass


def _packaged_data_dir() -> Path:
    """Per-user data dir (config.json / cookies.txt) for the packaged app.

    A packaged app runs read-only from inside the bundle, so its data lives here:
    macOS uses Application Support, elsewhere a dotfolder in HOME. Old KindleNotion
    data is migrated in on first run (see _migrate_legacy_data).
    """
    if sys.platform == "darwin":
        support = Path.home() / "Library" / "Application Support"
        base, legacy = support / "Booklight", support / "KindleNotion"
    else:
        base, legacy = Path.home() / ".booklight", Path.home() / ".kindle-notion"
    base.mkdir(parents=True, exist_ok=True)
    # Adopt old KindleNotion data only on a genuine first run — before this app
    # has written its own config.json. This runs on EVERY get_config_path/
    # get_cookies_path call, so migrating unconditionally would re-copy a legacy
    # cookies.txt right back after the user clears the sign-in (has_saved_cookies
    # goes through here), leaving them "signed in" until the legacy file is gone.
    if not (base / "config.json").exists():
        _migrate_legacy_data(legacy, base)
    return base


def get_config_path() -> Path:
    """Where config.json lives.

    Packaged: the per-user data dir (see _packaged_data_dir). In dev: prefer a
    config.json next to the script, then ~/.booklight/config.json, falling back
    to the legacy ~/.kindle-notion/config.json if only that exists.
    """
    if getattr(sys, "frozen", False):  # packaged app
        return _packaged_data_dir() / "config.json"
    if LOCAL_CONFIG.exists():
        return LOCAL_CONFIG
    if HOME_CONFIG.exists():
        return HOME_CONFIG
    if LEGACY_HOME_CONFIG.exists():
        return LEGACY_HOME_CONFIG
    return LOCAL_CONFIG


def load_config() -> dict:
    """Load config.json, creating it with empty defaults on first run."""
    p = get_config_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_EMPTY, ensure_ascii=False, indent=2), encoding="utf-8")
        return dict(_EMPTY)
    return json.loads(p.read_text(encoding="utf-8"))


def save_config(cfg: dict) -> None:
    """Write config.json atomically: a crash never leaves a half-written file.

    Write to a temp file in the same directory, then os.replace() it over the
    target — the rename is atomic, so config.json is always either the old
    complete file or the new complete file, never truncated JSON.
    """
    p = get_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


# ---------------------------------------------------------------- saved cookies
def get_cookies_path() -> Path:
    """The app-managed copy of cookies.txt, kept next to config.json.

    Importing a cookies.txt copies it here, so the original file is no longer
    needed at run time — the cookie data lives in the app's own data dir.
    """
    return get_config_path().parent / "cookies.txt"


def _count_cookies(path) -> int:
    cj = MozillaCookieJar()
    cj.load(str(path), ignore_discard=True, ignore_expires=True)
    return len(cj)


def import_cookies_file(src) -> int:
    """Validate a cookies.txt and copy it into the app data dir. Returns count.

    Raises if `src` is not a readable Netscape/Mozilla cookies.txt.
    """
    n = _count_cookies(src)  # parse first; a bad file raises before we overwrite
    dst = get_cookies_path()
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return n


def has_saved_cookies() -> bool:
    return get_cookies_path().exists()


def clear_saved_cookies() -> None:
    p = get_cookies_path()
    if p.exists():
        p.unlink()


def save_cookies(cookies) -> int:
    """Write harvested cookies to the app's store (Netscape cookies.txt format).

    `cookies` is a list of dicts with at least name/value/domain and optional
    path, expires (epoch seconds), secure. This is the in-app-login equivalent of
    import_cookies_file: it lands cookies in the same place build_session reads,
    so the rest of the pipeline is unchanged. Returns the number written. Only
    read.amazon / .amazon cookies are kept (the auth session lives there).
    """
    from http.cookiejar import Cookie

    dst = get_cookies_path()
    dst.parent.mkdir(parents=True, exist_ok=True)
    jar = MozillaCookieJar(str(dst))
    n = 0
    for c in cookies:
        name = (c.get("name") or "").strip()
        domain = (c.get("domain") or "").strip()
        if not name or "amazon" not in domain:
            continue
        try:
            expires = int(c["expires"]) if c.get("expires") else None
        except (TypeError, ValueError):
            expires = None
        jar.set_cookie(Cookie(
            version=0, name=name, value=c.get("value", ""),
            port=None, port_specified=False,
            domain=domain, domain_specified=True,
            domain_initial_dot=domain.startswith("."),
            path=c.get("path") or "/", path_specified=True,
            secure=bool(c.get("secure")), expires=expires,
            discard=False, comment=None, comment_url=None, rest={},
        ))
        n += 1
    jar.save(ignore_discard=True, ignore_expires=True)
    return n


# ---------------------------------------------------------------- session / cookies
def load_cookies(cookies_file, log=print):
    """Load a cookies.txt (Netscape/Mozilla jar); raise if no file is given."""
    if not cookies_file:
        raise RuntimeError(t("err_no_cookies"))
    cj = MozillaCookieJar()
    cj.load(cookies_file, ignore_discard=True, ignore_expires=True)
    log(t("log_cookies_loaded").format(n=len(cj)))
    return cj


def build_session(cookies_file, log=print) -> requests.Session:
    """A requests session preloaded with the saved cookies and the desktop UA."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ja,en;q=0.9"})
    for c in load_cookies(cookies_file, log):
        s.cookies.set_cookie(c)
    return s


def _renew_saved_cookies(session) -> None:
    """Write the session's (possibly Amazon-refreshed) cookies back to the store.

    Each request can rotate Amazon's tokens via Set-Cookie, and requests updates
    them in `session.cookies` in place. Persisting that set after a *successful*
    call lets the login self-renew like a browser, so it stays valid far longer.
    Best-effort: a save failure must never break the sync/check that just worked.

    Renew only *refreshes* an existing store — it must never re-create one that
    was deleted while the (30 s) probe was in flight. Without this guard, clearing
    the sign-in during a background check would resurrect cookies.txt, leaving the
    app "signed in" again until restart.
    """
    try:
        dst = get_cookies_path()
        if not dst.exists():
            return  # cleared mid-probe — don't resurrect the deleted store
        jar = MozillaCookieJar(str(dst))
        for c in session.cookies:  # requests' jar yields http.cookiejar.Cookie
            if "amazon" in (c.domain or ""):
                jar.set_cookie(c)
        if len(jar):
            dst.parent.mkdir(parents=True, exist_ok=True)
            jar.save(ignore_discard=True, ignore_expires=True)
    except Exception:
        pass


def check_cookies(cookies_file, log=print) -> bool:
    """Lightweight auth probe: True if the saved cookies still log us in.

    Fetches the notebook page and checks for a sign-in redirect — the same
    signal fetch_all_books uses. Returns False when the cookies have expired or
    been invalidated. Raises on network errors so callers can distinguish
    "expired" (False) from "couldn't reach Amazon" (exception). On success it
    also renews the stored cookies (see _renew_saved_cookies).
    """
    session = build_session(cookies_file, log=log)
    r = session.get(NOTEBOOK, timeout=30)
    ok = "signin" not in r.url and "/ap/" not in r.url
    if ok:
        _renew_saved_cookies(session)
    return ok


# ---------------------------------------------------------------- parsing
def parse_books(html: str) -> list:
    """Parse the notebook library sidebar into ``[{asin, title, author}, ...]``.

    Each book is a ``.kp-notebook-library-each-book`` div keyed by its ASIN (the
    div id); the "著者:" / "著者：" (JP) and "By:" (EN) prefix is stripped from
    the author.
    """
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for div in soup.select(".kp-notebook-library-each-book"):
        asin = div.get("id")
        if not asin:
            continue
        t = div.select_one("h2.kp-notebook-searchable")
        a = div.select_one("p.kp-notebook-searchable")
        author = a.get_text(strip=True) if a else None
        if author:
            author = re.sub(r"^(?:著者|by)\s*[:：]\s*", "", author, flags=re.IGNORECASE).strip()
        out.append(
            {
                "asin": asin,
                "title": t.get_text(strip=True) if t else None,
                "author": author,
            }
        )
    return out


def extract_color(row, header_text):
    """The marker colour as a Japanese label (黄色/青/ピンク/オレンジ), or None.

    Prefers the ``kp-notebook-highlight-<color>`` class; falls back to the colour
    named in the header text when the class is missing.
    """
    colored = row.select_one('[class*="kp-notebook-highlight-"]')
    if colored:
        classes = " ".join(colored.get("class", []))
        m = re.search(r"kp-notebook-highlight-(yellow|blue|pink|orange)", classes)
        if m:
            return COLOR_JA[m.group(1)]
    h = header_text or ""
    if "黄" in h:
        return "黄色"
    if "青" in h:
        return "青"
    if "ピンク" in h:
        return "ピンク"
    if "オレンジ" in h:
        return "オレンジ"
    return None


def parse_annotations(html: str) -> dict:
    """Parse one annotations page into ``{annotations, next_token, content_limit_state}``.

    Each annotation carries id/highlight/note/header/color/location. ``next_token``
    drives the server-side pagination and ``content_limit_state`` is echoed back on
    the next request. A fallback selector handles pages whose container id differs.
    """
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#kp-notebook-annotations")
    rows = []
    if container:
        rows = [
            d
            for d in container.find_all("div", recursive=False)
            if d.select_one("#highlight") or d.select_one("#note")
        ]
    if not rows:
        seen = []
        for el in soup.select('[id="highlight"], [id="note"]'):
            wrap = el.find_parent("div", class_="a-row") or el.parent
            if wrap is not None and wrap not in seen:
                seen.append(wrap)
        rows = seen

    annotations = []
    for row in rows:
        hl = row.select_one("#highlight")
        note = row.select_one("#note")
        header = row.select_one("#annotationHighlightHeader") or row.select_one(
            "#annotationNoteHeader"
        )
        loc = row.select_one("#kp-annotation-location")
        highlight = hl.get_text(strip=True) if hl else None
        note_text = note.get_text(strip=True) if note else None
        if not highlight and not note_text:
            continue
        header_text = re.sub(r"\s+", " ", header.get_text()).strip() if header else None
        annotations.append(
            {
                "id": row.get("id") or None,
                "highlight": highlight or None,
                "note": note_text or None,
                "header": header_text,
                "color": extract_color(row, header_text),
                "location": loc.get("value") if loc else None,
            }
        )

    next_el = soup.select_one(".kp-notebook-annotations-next-page-start")
    cls_el = soup.select_one(".kp-notebook-content-limit-state")
    return {
        "annotations": annotations,
        "next_token": (next_el.get("value") or "") if next_el else "",
        "content_limit_state": (cls_el.get("value") or "") if cls_el else "",
    }


# ---------------------------------------------------------------- kindle fetch
def _next_library_token(html: str) -> str:
    """The pagination token for the next library page (empty when it's the last)."""
    nxt = BeautifulSoup(html, "html.parser").select_one(
        ".kp-notebook-library-next-page-start"
    )
    return (nxt.get("value") or "") if nxt else ""


def fetch_all_books(session: requests.Session, should_cancel=None) -> list:
    """Collect every book.

    The first batch (and the CSRF token) come from the main /notebook page;
    the notebook only serves /notebook?library=list for *subsequent* pages, and
    only with a token (a tokenless call 400s). So we seed from the main page and
    then follow the next-page token.
    """
    r = session.get(NOTEBOOK, timeout=30)
    if "signin" in r.url or "/ap/" in r.url:
        raise RuntimeError(t("err_not_logged_in"))
    soup = BeautifulSoup(r.text, "html.parser")
    csrf_el = soup.select_one("input[name='anti-csrftoken-a2z']")
    csrf = csrf_el.get("value") if csrf_el else None

    # Collect books, skipping any ASIN already seen: the next-page-start token can
    # overlap the boundary book, so the same book (and all its highlights) would
    # otherwise be fetched twice. First occurrence wins.
    books, seen = [], set()

    def _add(new_books):
        for bk in new_books:
            asin = bk.get("asin")
            if asin and asin not in seen:
                seen.add(asin)
                books.append(bk)

    _add(parse_books(r.text))
    if not books:
        raise RuntimeError(t("err_fetch_books"))
    token = _next_library_token(r.text)

    # Paginated endpoint for the remaining batches. It expects the CSRF token
    # header and a valid page token; the token is appended verbatim so requests
    # doesn't double-encode its existing %-encoding.
    headers = {"X-Requested-With": "XMLHttpRequest", "Referer": NOTEBOOK}
    if csrf:
        headers["anti-csrftoken-a2z"] = csrf
    while token:
        _raise_if_cancelled(should_cancel)
        r = session.get(
            NOTEBOOK + "?library=list&token=" + token, headers=headers, timeout=30
        )
        _add(parse_books(r.text))
        token = _next_library_token(r.text)
    return books


def fetch_book_annotations(session: requests.Session, asin: str) -> list:
    """All annotations for one book, following Amazon's server-side pagination.

    Loops ``/notebook?asin=...`` with the returned next_token / content-limit
    state until there is no next page (capped at 100 pages as a safety bound).

    Annotations carrying an id are deduped by it: the next-page-start token can
    overlap the boundary highlight, returning it on two adjacent pages. Id-less
    annotations are kept as-is (build_rows still dedups them by composite key).
    """
    annotations, token, cls = [], "", ""
    seen = set()
    for _ in range(100):
        params = {"asin": asin, "contentLimitState": cls}
        if token:
            params["token"] = token
        r = session.get(NOTEBOOK, params=params, timeout=30)
        parsed = parse_annotations(r.text)
        for ann in parsed["annotations"]:
            aid = ann.get("id")
            if aid is not None:
                if aid in seen:
                    continue
                seen.add(aid)
            annotations.append(ann)
        cls = parsed["content_limit_state"] or ""
        token = parsed["next_token"] or ""
        if not token:
            break
    return annotations


def fetch_kindle(session: requests.Session, limit, log=print, progress=None,
                 should_cancel=None) -> list:
    """Fetch the whole library and each book's annotations.

    Returns the books, each with an ``annotations`` list attached. ``limit`` (if
    set) caps how many books are fetched — used by the test-sync. Reports work via
    the optional ``log`` / ``progress`` callbacks. ``should_cancel`` (if given) is
    polled between books so a user-requested stop unwinds promptly.
    """
    log(t("log_fetch_library"))
    if progress:
        progress(t("prog_fetch_library"), 0, 0)  # count unknown yet → indeterminate
    books = fetch_all_books(session, should_cancel)
    log(t("log_books_found").format(n=len(books)))
    if limit:
        books = books[:limit]
    for i, b in enumerate(books, 1):
        _raise_if_cancelled(should_cancel)
        b["annotations"] = fetch_book_annotations(session, b["asin"])
        log(t("log_book_line").format(
            i=i, total=len(books), title=b.get("title") or b["asin"],
            n=len(b["annotations"])))
        if progress:
            progress(t("prog_fetch_highlights"), i, len(books))
    return books


# ---------------------------------------------------------------- notion
def normalize_id(s: str) -> str:
    """Normalise a Notion id or URL to a dashed 32-hex UUID (best-effort).

    Extracts the 32-hex id (ignoring dashes) and re-inserts the 8-4-4-4-12
    dashes; returns the input stripped if no id is found. The run must end at a
    non-hex boundary (``(?![0-9a-fA-F])``) so a page slug that ends in hex
    letters — e.g. ``.../Reading-Archive-<id>`` (“Archive” ends in ‘e’) — can't
    merge into the id and shift the captured 32 chars rightward.
    """
    if not s:
        return ""
    m = re.search(r"[0-9a-fA-F]{32}(?![0-9a-fA-F])", s.replace("-", ""))
    if not m:
        return s.strip()
    h = m.group(0).lower()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def database_url(db_id: str) -> str:
    """Browser URL that opens (redirects to) a Notion database by its id."""
    h = normalize_id(db_id or "").replace("-", "")
    return ("https://www.notion.so/" + h) if len(h) == 32 else ""


def notion_fetch(token: str, path: str, method: str, body=None):
    """Call the Notion API, retrying on 429 (rate limit) up to 5 times.

    Honours the ``Retry-After`` header on 429 and raises RuntimeError with the
    status + message on any other non-2xx. Returns the decoded JSON body.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    for _ in range(5):
        r = requests.request(
            method, "https://api.notion.com/v1" + path, headers=headers, json=body
        )
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", "1")))
            continue
        data = r.json() if r.content else {}
        if not r.ok:
            raise RuntimeError(f"Notion {r.status_code}: {data.get('message', r.reason)}")
        return data
    raise RuntimeError(t("err_rate_limit"))


def check_notion(token: str) -> bool:
    """Lightweight auth probe: True if the Notion token is valid.

    Calls GET /users/me, which any valid integration token can reach and an
    invalid/empty one rejects with 401/403. Mirrors check_cookies: returns
    False for a bad token, but re-raises other errors (network, 5xx) so callers
    can tell "invalid token" apart from "couldn't reach Notion".
    """
    if not (token or "").strip():
        return False
    try:
        notion_fetch(token.strip(), "/users/me", "GET")
        return True
    except RuntimeError as e:
        m = str(e)
        if "Notion 401" in m or "Notion 403" in m:
            return False
        raise


def create_database(token: str, parent_page_id: str):
    """Create the "Kindle Highlights" database under the given parent page.

    Defines the fixed schema (highlight / title / author / location / colour /
    date / annotation-id).
    """
    # NOTE: Notion's API ignores property order on database creation — the UI
    # shows columns in an internal (arbitrary) order regardless of the order
    # below or of adding them one-by-one via PATCH. The public API has no way to
    # set column order, so arrange the columns once by hand after first creation
    # (the DB is created once and reused, so this is a one-time step).
    body = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": "Kindle Highlights"}}],
        "properties": {
            "ハイライト文": {"title": {}},
            "書籍名": {"rich_text": {}},
            "著者名": {"rich_text": {}},
            "位置": {"number": {}},
            "マーカー色": {
                "select": {
                    "options": [
                        {"name": "黄色", "color": "yellow"},
                        {"name": "青", "color": "blue"},
                        {"name": "ピンク", "color": "pink"},
                        {"name": "オレンジ", "color": "orange"},
                    ]
                }
            },
            "実行日": {"date": {}},
            "注釈ID": {"rich_text": {}},
        },
    }
    return notion_fetch(token, "/databases", "POST", body)


def ensure_schema(token: str, db_id: str) -> None:
    """Make sure the dedup-key column (注釈ID) exists on an existing database.

    Lets the app append to a user-supplied database that predates this column.
    """
    db = notion_fetch(token, "/databases/" + db_id, "GET")
    if db.get("properties", {}).get("注釈ID"):
        return
    notion_fetch(
        token, "/databases/" + db_id, "PATCH", {"properties": {"注釈ID": {"rich_text": {}}}}
    )


def query_existing_keys(token: str, db_id: str, should_cancel=None) -> set:
    """All 注釈ID values already in the database (paged), for dedup on insert."""
    existing, cursor = set(), None
    while True:
        _raise_if_cancelled(should_cancel)
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        res = notion_fetch(token, f"/databases/{db_id}/query", "POST", body)
        for pg in res.get("results", []):
            prop = pg.get("properties", {}).get("注釈ID", {})
            txt = "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))
            if txt:
                existing.add(txt)
        if res.get("has_more"):
            cursor = res.get("next_cursor")
            time.sleep(0.2)
        else:
            break
    return existing


def rich_text(content: str):
    # Notion caps one rich_text object at 2000 chars, so split long text into chunks.
    s = content or ""
    return [
        {"type": "text", "text": {"content": s[i : i + 2000]}}
        for i in range(0, len(s), 2000)
    ]


def page_properties(r: dict):
    """Notion page properties for one highlight row.

    The (Japanese) property names are the database schema — see the note in
    create_database — and must match what query_existing_keys reads back.
    """
    props = {
        "ハイライト文": {"title": rich_text(r["quote"])},
        "書籍名": {"rich_text": rich_text(r["title"])},
        "著者名": {"rich_text": rich_text(r["author"])},
        "実行日": {"date": {"start": r["date"]}},
        "注釈ID": {"rich_text": rich_text(r["key"])},
    }
    if r.get("location") is not None:
        props["位置"] = {"number": r["location"]}
    if r.get("color"):
        props["マーカー色"] = {"select": {"name": r["color"]}}
    return props


def build_rows(books: list, today: str) -> list:
    """Flatten books → one row per highlight, each with a stable dedup ``key``.

    The key is the annotation id when present, else a
    ``title|location|quote-prefix`` composite so id-less highlights still dedup.
    Rows are sorted by title then location.

    Rows are also deduped by ``key`` *within this run*: the paginated Kindle fetch
    can return the same annotation on adjacent pages (next-page-start overlaps the
    boundary item), and Notion-side dedup only compares against rows already in the
    database — so without this, an annotation fetched twice in one run would be
    inserted twice, producing identical-注釈ID duplicates. First occurrence wins.
    """
    rows = []
    seen = set()
    for b in books:
        for a in b.get("annotations", []):
            if not a.get("highlight"):
                continue
            loc = None
            if a.get("location"):
                digits = re.sub(r"[^0-9]", "", str(a["location"]))
                loc = int(digits) if digits else None
            r = {
                "id": a.get("id"),
                "quote": a["highlight"],
                "title": b.get("title") or "",
                "author": b.get("author") or "",
                "location": loc,
                "color": a.get("color"),
                "date": today,
            }
            r["key"] = r["id"] or f'{r["title"]}|{r["location"]}|{(r["quote"] or "")[:40]}'
            if r["key"] in seen:
                continue
            seen.add(r["key"])
            rows.append(r)
    rows.sort(
        key=lambda r: (r["title"], r["location"] if r["location"] is not None else float("inf"))
    )
    return rows


def notion_sync(token, parent_page_id, database_id, books, today, log=print,
                progress=None, on_database=None, should_cancel=None) -> dict:
    """Push highlights to Notion. Returns a result dict incl. the database_id
    used/created, so the caller can persist it.

    on_database(db_id) is called as soon as a new database is created — before
    any highlights are inserted — so the caller can persist the id immediately.
    That way an interrupted first sync resumes into the same database instead of
    creating a duplicate on the next run.

    ``should_cancel`` (if given) is polled before each insert; a stop leaves the
    rows written so far in place (dedup skips them next run) and raises
    SyncCancelled carrying the partial insert/fail counts.
    """
    db_id = normalize_id(database_id or "")
    if not db_id:
        parent = normalize_id(parent_page_id or "")
        if not parent:
            raise RuntimeError(t("err_no_parent"))
        log(t("log_creating_db"))
        db = create_database(token, parent)
        db_id = db["id"]
        log(t("log_created").format(x=db.get("url") or db_id))
        if on_database:
            on_database(db_id)

    ensure_schema(token, db_id)
    existing = query_existing_keys(token, db_id, should_cancel)
    log(t("log_existing").format(n=len(existing)))

    rows = build_rows(books, today)
    fresh = [r for r in rows if r["key"] not in existing]
    log(t("log_to_insert").format(n=len(fresh), s=len(rows) - len(fresh)))
    if progress:
        progress(t("prog_notion_insert"), 0, len(fresh))

    ok = fail = 0
    min_interval = 0.34  # ~3 req/s
    for i, r in enumerate(fresh):
        _raise_if_cancelled(should_cancel, inserted=ok, failed=fail)
        t0 = time.time()
        try:
            notion_fetch(
                token,
                "/pages",
                "POST",
                {"parent": {"database_id": db_id}, "properties": page_properties(r)},
            )
            ok += 1
        except Exception as e:
            fail += 1
            log(t("log_insert_failed").format(e=e))
        if progress:
            progress(t("prog_notion_insert"), i + 1, len(fresh))
        if (i + 1) % 20 == 0 or i == len(fresh) - 1:
            log(t("log_insert_progress").format(
                i=i + 1, total=len(fresh), ok=ok, fail=fail))
        dt = time.time() - t0
        if i < len(fresh) - 1 and dt < min_interval:
            time.sleep(min_interval - dt)

    return {
        "database_id": db_id,
        "total": len(rows),
        "inserted": ok,
        "failed": fail,
        "skipped": len(rows) - len(fresh),
    }


def run_sync(cfg: dict, cookies_file=None, limit=None, log=print, progress=None,
             should_cancel=None) -> dict:
    """End-to-end sync used by both the CLI and the GUI. Persists a newly
    created database_id back into cfg + config.json.

    ``should_cancel`` is an optional zero-arg predicate polled at loop
    boundaries; when it returns true the sync unwinds with SyncCancelled. The GUI
    passes its stop-button event; the CLI leaves it None (no cancellation)."""
    if not cfg.get("notion_token"):
        raise RuntimeError(t("err_no_token"))
    session = build_session(cookies_file, log)
    books = fetch_kindle(session, limit, log, progress, should_cancel)
    if not books:
        raise RuntimeError(t("err_zero_books"))
    _renew_saved_cookies(session)  # keep the stored login fresh for next time

    had_db = bool((cfg.get("notion_database_id") or "").strip())

    def _persist_new_db(db_id):
        # Persist a freshly created database id right away (before inserts) so an
        # interrupted first sync resumes into it rather than making a duplicate.
        if not had_db:
            cfg["notion_database_id"] = db_id
            save_config(cfg)

    res = notion_sync(
        cfg["notion_token"],
        cfg.get("notion_parent_page_id"),
        cfg.get("notion_database_id"),
        books,
        date.today().isoformat(),
        log,
        progress,
        on_database=_persist_new_db,
        should_cancel=should_cancel,
    )
    return res


# ---------------------------------------------------------------- main (CLI)
def main() -> int:
    """CLI entry point: sync using -c cookies.txt and the config.json token."""
    cfg = load_config()
    set_language(cfg.get("ui_language", "auto"))  # follow the saved pref, else OS
    ap = argparse.ArgumentParser(description="Kindle highlights → Notion (browser-free)")
    ap.add_argument("-c", "--cookies-file", required=True, help=t("cli_help_cookies"))
    ap.add_argument("--limit", type=int, help=t("cli_help_limit"))
    args = ap.parse_args()

    if not cfg.get("notion_token"):
        print(t("cli_set_token").format(path=get_config_path()))
        return 1
    try:
        res = run_sync(cfg, args.cookies_file, args.limit)
    except RuntimeError as e:
        print(t("cli_error"), e)
        return 2
    print(t("cli_summary").format(
        total=res["total"], inserted=res["inserted"],
        skipped=res["skipped"], failed=res["failed"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
