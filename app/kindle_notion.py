#!/usr/bin/env python3
"""Kindle highlights → Notion, as a standalone (Mac click-to-run) app.

Browser-free: it talks to read.amazon.co.jp directly with `requests`, using the
login cookies from an exported cookies.txt.

The library sidebar is paginated server-side via `/notebook?library=list`
(+ a `token`), so we loop that to get every book — no headless browser needed.
Each book's highlights come from `/notebook?asin=...`. Everything is then
pushed into a Notion database.

Being an ordinary process, it is not throttled when you switch to another app.

Config lives in ~/.kindle-notion/config.json.
"""
from __future__ import annotations

import argparse
import json
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

SCRIPT_DIR = Path(__file__).resolve().parent
LOCAL_CONFIG = SCRIPT_DIR / "config.json"
HOME_CONFIG = Path.home() / ".kindle-notion" / "config.json"
_EMPTY = {"notion_token": "", "notion_parent_page_id": "", "notion_database_id": ""}


# ---------------------------------------------------------------- config
def get_config_path() -> Path:
    """Where config.json lives.

    A packaged .app runs read-only from inside the bundle, so store config in
    the user's Application Support instead. In dev, prefer a config.json next to
    the script, then ~/.kindle-notion/config.json.
    """
    if getattr(sys, "frozen", False):  # packaged app
        if sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support" / "KindleNotion"
        else:
            base = Path.home() / ".kindle-notion"
        base.mkdir(parents=True, exist_ok=True)
        return base / "config.json"
    if LOCAL_CONFIG.exists():
        return LOCAL_CONFIG
    if HOME_CONFIG.exists():
        return HOME_CONFIG
    return LOCAL_CONFIG


def load_config() -> dict:
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


def saved_cookies_count() -> int:
    p = get_cookies_path()
    if not p.exists():
        return 0
    try:
        return _count_cookies(p)
    except Exception:
        return 0


def clear_saved_cookies() -> None:
    p = get_cookies_path()
    if p.exists():
        p.unlink()


# ---------------------------------------------------------------- session / cookies
def load_cookies(cookies_file, log=print):
    if not cookies_file:
        raise RuntimeError("cookies.txt が指定されていません。")
    cj = MozillaCookieJar()
    cj.load(cookies_file, ignore_discard=True, ignore_expires=True)
    log(f"cookies.txt から {len(cj)} 件のCookieを読み込みました")
    return cj


def build_session(cookies_file, log=print) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ja,en;q=0.9"})
    for c in load_cookies(cookies_file, log):
        s.cookies.set_cookie(c)
    return s


def check_cookies(cookies_file, log=print) -> bool:
    """Lightweight auth probe: True if the saved cookies still log us in.

    Fetches the notebook page and checks for a sign-in redirect — the same
    signal fetch_all_books uses. Returns False when the cookies have expired or
    been invalidated. Raises on network errors so callers can distinguish
    "expired" (False) from "couldn't reach Amazon" (exception).
    """
    session = build_session(cookies_file, log=log)
    r = session.get(NOTEBOOK, timeout=30)
    return "signin" not in r.url and "/ap/" not in r.url


# ---------------------------------------------------------------- parsing
def parse_books(html: str) -> list:
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
            author = re.sub(r"^著者\s*[:：]\s*", "", author).strip()
        out.append(
            {
                "asin": asin,
                "title": t.get_text(strip=True) if t else None,
                "author": author,
            }
        )
    return out


def extract_color(row, header_text):
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
    nxt = BeautifulSoup(html, "html.parser").select_one(
        ".kp-notebook-library-next-page-start"
    )
    return (nxt.get("value") or "") if nxt else ""


def fetch_all_books(session: requests.Session) -> list:
    """Collect every book.

    The first batch (and the CSRF token) come from the main /notebook page;
    the notebook only serves /notebook?library=list for *subsequent* pages, and
    only with a token (a tokenless call 400s). So we seed from the main page and
    then follow the next-page token.
    """
    r = session.get(NOTEBOOK, timeout=30)
    if "signin" in r.url or "/ap/" in r.url:
        raise RuntimeError(
            "ログインしていません。Cookie の有効期限が切れた可能性があります。"
            "ブラウザで read.amazon.co.jp にログインし直し、新しい cookies.txt を"
            "書き出して「取り込み…」から入れ直してください。"
        )
    soup = BeautifulSoup(r.text, "html.parser")
    csrf_el = soup.select_one("input[name='anti-csrftoken-a2z']")
    csrf = csrf_el.get("value") if csrf_el else None

    books = parse_books(r.text)
    if not books:
        raise RuntimeError("本を取得できませんでした。ログイン状態を確認してください。")
    token = _next_library_token(r.text)

    # Paginated endpoint for the remaining batches. It expects the CSRF token
    # header and a valid page token; the token is appended verbatim so requests
    # doesn't double-encode its existing %-encoding.
    headers = {"X-Requested-With": "XMLHttpRequest", "Referer": NOTEBOOK}
    if csrf:
        headers["anti-csrftoken-a2z"] = csrf
    while token:
        r = session.get(
            NOTEBOOK + "?library=list&token=" + token, headers=headers, timeout=30
        )
        books.extend(parse_books(r.text))
        token = _next_library_token(r.text)
    return books


def fetch_book_annotations(session: requests.Session, asin: str) -> list:
    annotations, token, cls = [], "", ""
    for _ in range(100):
        params = {"asin": asin, "contentLimitState": cls}
        if token:
            params["token"] = token
        r = session.get(NOTEBOOK, params=params, timeout=30)
        parsed = parse_annotations(r.text)
        annotations.extend(parsed["annotations"])
        cls = parsed["content_limit_state"] or ""
        token = parsed["next_token"] or ""
        if not token:
            break
    return annotations


def fetch_kindle(session: requests.Session, limit, log=print, progress=None) -> list:
    log("本一覧を取得中…")
    if progress:
        progress("本一覧を取得中", 0, 0)  # count unknown yet → indeterminate
    books = fetch_all_books(session)
    log(f"{len(books)} 冊を検出")
    if limit:
        books = books[:limit]
    for i, b in enumerate(books, 1):
        b["annotations"] = fetch_book_annotations(session, b["asin"])
        log(f"({i}/{len(books)}) {b.get('title') or b['asin']} … {len(b['annotations'])} 件")
        if progress:
            progress("ハイライト取得", i, len(books))
    return books


# ---------------------------------------------------------------- notion
def normalize_id(s: str) -> str:
    if not s:
        return ""
    m = re.search(r"[0-9a-fA-F]{32}", s.replace("-", ""))
    if not m:
        return s.strip()
    h = m.group(0).lower()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def notion_fetch(token: str, path: str, method: str, body=None):
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
    raise RuntimeError("Notion のレート制限で再試行上限に達しました。")


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
    db = notion_fetch(token, "/databases/" + db_id, "GET")
    if db.get("properties", {}).get("注釈ID"):
        return
    notion_fetch(
        token, "/databases/" + db_id, "PATCH", {"properties": {"注釈ID": {"rich_text": {}}}}
    )


def query_existing_keys(token: str, db_id: str) -> set:
    existing, cursor = set(), None
    while True:
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
    s = content or ""
    return [
        {"type": "text", "text": {"content": s[i : i + 2000]}}
        for i in range(0, len(s), 2000)
    ]


def page_properties(r: dict):
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
    rows = []
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
            rows.append(r)
    rows.sort(
        key=lambda r: (r["title"], r["location"] if r["location"] is not None else float("inf"))
    )
    return rows


def notion_sync(token, parent_page_id, database_id, books, today, log=print,
                progress=None, on_database=None) -> dict:
    """Push highlights to Notion. Returns a result dict incl. the database_id
    used/created, so the caller can persist it.

    on_database(db_id) is called as soon as a new database is created — before
    any highlights are inserted — so the caller can persist the id immediately.
    That way an interrupted first sync resumes into the same database instead of
    creating a duplicate on the next run.
    """
    db_id = normalize_id(database_id or "")
    if not db_id:
        parent = normalize_id(parent_page_id or "")
        if not parent:
            raise RuntimeError("親ページID（または既存DB ID）が未設定です。")
        log("Notion データベースを作成中…")
        db = create_database(token, parent)
        db_id = db["id"]
        log("作成: " + (db.get("url") or db_id))
        if on_database:
            on_database(db_id)

    ensure_schema(token, db_id)
    existing = query_existing_keys(token, db_id)
    log(f"既存 {len(existing)} 件を確認")

    rows = build_rows(books, today)
    fresh = [r for r in rows if r["key"] not in existing]
    log(f"登録対象 {len(fresh)} 件（重複スキップ {len(rows) - len(fresh)} 件）")
    if progress:
        progress("Notion 登録", 0, len(fresh))

    ok = fail = 0
    min_interval = 0.34  # ~3 req/s
    for i, r in enumerate(fresh):
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
            log("  登録失敗: " + str(e))
        if progress:
            progress("Notion 登録", i + 1, len(fresh))
        if (i + 1) % 20 == 0 or i == len(fresh) - 1:
            log(f"  Notion 登録 {i + 1}/{len(fresh)}（成功{ok}/失敗{fail}）")
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


def run_sync(cfg: dict, cookies_file=None, limit=None, log=print, progress=None) -> dict:
    """End-to-end sync used by both the CLI and the GUI. Persists a newly
    created database_id back into cfg + config.json."""
    if not cfg.get("notion_token"):
        raise RuntimeError("Notion トークンが未設定です。")
    session = build_session(cookies_file, log)
    books = fetch_kindle(session, limit, log, progress)
    if not books:
        raise RuntimeError("本が0冊でした。ログイン状態を確認してください。")

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
    )
    return res


# ---------------------------------------------------------------- main (CLI)
def main() -> int:
    ap = argparse.ArgumentParser(description="Kindle highlights → Notion (browser-free)")
    ap.add_argument("-c", "--cookies-file", required=True, help="エクスポート済み cookies.txt")
    ap.add_argument("--limit", type=int, help="先頭 N 冊だけ（テスト用）")
    args = ap.parse_args()

    cfg = load_config()
    if not cfg.get("notion_token"):
        print(f"config.json に notion_token を設定してください: {get_config_path()}")
        return 1
    try:
        res = run_sync(cfg, args.cookies_file, args.limit)
    except RuntimeError as e:
        print("エラー:", e)
        return 2
    print(
        f"完了: 対象 {res['total']} / 新規 {res['inserted']} / "
        f"重複 {res['skipped']} / 失敗 {res['failed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
