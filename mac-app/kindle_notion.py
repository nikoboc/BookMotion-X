#!/usr/bin/env python3
"""Kindle highlights → Notion, as a standalone (Mac click-to-run) app.

Browser-free: it talks to read.amazon.co.jp directly with `requests`, using the
login cookies from your browser (browser_cookie3) or an exported cookies.txt.

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
import re
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
DOMAIN = "amazon.co.jp"
# Browser cookie sources to try, in order (Mac-friendly first).
BROWSER_ORDER = ["chrome", "safari", "edge", "brave", "firefox", "chromium"]

COLOR_JA = {"yellow": "黄色", "blue": "青", "pink": "ピンク", "orange": "オレンジ"}

# config.json is looked for next to this script first (mac-app/config.json),
# then ~/.kindle-notion/config.json. New files are created next to the script.
SCRIPT_DIR = Path(__file__).resolve().parent
LOCAL_CONFIG = SCRIPT_DIR / "config.json"
HOME_CONFIG = Path.home() / ".kindle-notion" / "config.json"
_config_path: Path | None = None


# ---------------------------------------------------------------- config
def _resolve_config_path() -> Path:
    if LOCAL_CONFIG.exists():
        return LOCAL_CONFIG
    if HOME_CONFIG.exists():
        return HOME_CONFIG
    return LOCAL_CONFIG


def load_config() -> dict:
    global _config_path
    _config_path = _resolve_config_path()
    if not _config_path.exists():
        _config_path.parent.mkdir(parents=True, exist_ok=True)
        _config_path.write_text(
            json.dumps(
                {"notion_token": "", "notion_parent_page_id": "", "notion_database_id": ""},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"設定ファイルを作成しました: {_config_path}")
        print("notion_token と notion_parent_page_id を記入して、もう一度実行してください。")
        sys.exit(1)
    return json.loads(_config_path.read_text(encoding="utf-8"))


def save_config(cfg: dict) -> None:
    _config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- session / cookies
def load_cookies(cookies_file: str | None, browser: str | None):
    if cookies_file:
        cj = MozillaCookieJar()
        cj.load(cookies_file, ignore_discard=True, ignore_expires=True)
        print(f"cookies.txt から {len(cj)} 件のCookieを読み込みました")
        return cj
    import browser_cookie3

    for name in [browser] if browser else BROWSER_ORDER:
        fn = getattr(browser_cookie3, name, None)
        if fn is None:
            continue
        try:
            cj = fn(domain_name=DOMAIN)
            if len(cj) > 0:
                print(f"{name} から {len(cj)} 件のCookieを読み込みました")
                return cj
        except Exception as e:
            print(f"[info] {name}: {e}")
    raise SystemExit(
        f"{DOMAIN} のCookieが見つかりませんでした。ブラウザで {BASE} にログインするか、"
        "--cookies-file でエクスポート済みCookieを指定してください。"
    )


def build_session(cookies_file: str | None, browser: str | None) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ja,en;q=0.9"})
    for c in load_cookies(cookies_file, browser):
        s.cookies.set_cookie(c)
    return s


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
def fetch_all_books(session: requests.Session) -> list:
    """Paginate /notebook?library=list to collect every book."""
    books, token, first = [], "", True
    while True:
        # Token comes URL-encoded already; append verbatim so requests doesn't
        # double-encode it (requests preserves existing %-encoding).
        url = NOTEBOOK + "?library=list" + (f"&token={token}" if token else "")
        r = session.get(url, timeout=30)
        if first and ("signin" in r.url or "/ap/" in r.url):
            raise SystemExit(
                "ログインしていません。ブラウザで read.amazon.co.jp にログインして再実行"
                "（または --cookies-file を指定）してください。"
            )
        page_books = parse_books(r.text)
        if first and not page_books:
            raise SystemExit("本を取得できませんでした。ログイン状態を確認してください。")
        books.extend(page_books)
        soup = BeautifulSoup(r.text, "html.parser")
        nxt = soup.select_one(".kp-notebook-library-next-page-start")
        token = (nxt.get("value") or "") if nxt else ""
        first = False
        if not token:
            break
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


def fetch_kindle(session: requests.Session, limit: int | None) -> list:
    print("本一覧を取得中…")
    books = fetch_all_books(session)
    print(f"{len(books)} 冊を検出")
    if limit:
        books = books[:limit]
    for i, b in enumerate(books, 1):
        b["annotations"] = fetch_book_annotations(session, b["asin"])
        print(f"({i}/{len(books)}) {b.get('title') or b['asin']} … {len(b['annotations'])} 件")
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


def create_database(token: str, parent_page_id: str):
    body = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": "Kindle Highlights"}}],
        "properties": {
            "引用文": {"title": {}},
            "本のタイトル": {"rich_text": {}},
            "本の著者": {"rich_text": {}},
            "ハイライト位置": {"number": {}},
            "ハイライト色": {
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
        "引用文": {"title": rich_text(r["quote"])},
        "本のタイトル": {"rich_text": rich_text(r["title"])},
        "本の著者": {"rich_text": rich_text(r["author"])},
        "実行日": {"date": {"start": r["date"]}},
        "注釈ID": {"rich_text": rich_text(r["key"])},
    }
    if r.get("location") is not None:
        props["ハイライト位置"] = {"number": r["location"]}
    if r.get("color"):
        props["ハイライト色"] = {"select": {"name": r["color"]}}
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


def notion_sync(cfg: dict, books: list, today: str) -> dict:
    token = cfg["notion_token"]
    db_id = normalize_id(cfg.get("notion_database_id") or "")
    if not db_id:
        parent = normalize_id(cfg.get("notion_parent_page_id") or "")
        if not parent:
            raise RuntimeError("notion_parent_page_id が未設定です。")
        print("Notion データベースを作成中…")
        db = create_database(token, parent)
        db_id = db["id"]
        cfg["notion_database_id"] = db_id
        save_config(cfg)
        print("作成:", db.get("url"))

    ensure_schema(token, db_id)
    existing = query_existing_keys(token, db_id)
    print(f"既存 {len(existing)} 件を確認")

    rows = build_rows(books, today)
    fresh = [r for r in rows if r["key"] not in existing]
    print(f"登録対象 {len(fresh)} 件（重複スキップ {len(rows) - len(fresh)} 件）")

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
            print("  登録失敗:", e)
        if (i + 1) % 20 == 0 or i == len(fresh) - 1:
            print(f"  Notion 登録 {i + 1}/{len(fresh)}（成功{ok}/失敗{fail}）")
        dt = time.time() - t0
        if i < len(fresh) - 1 and dt < min_interval:
            time.sleep(min_interval - dt)

    return {"total": len(rows), "inserted": ok, "failed": fail, "skipped": len(rows) - len(fresh)}


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Kindle highlights → Notion (browser-free)")
    ap.add_argument("-c", "--cookies-file", help="エクスポート済み cookies.txt")
    ap.add_argument("-b", "--browser", help="chrome|safari|edge|brave|firefox")
    ap.add_argument("--limit", type=int, help="先頭 N 冊だけ（テスト用）")
    args = ap.parse_args()

    cfg = load_config()
    if not cfg.get("notion_token"):
        print(f"config.json に notion_token を設定してください: {_config_path}")
        return 1

    session = build_session(args.cookies_file, args.browser)
    books = fetch_kindle(session, args.limit)
    if not books:
        print("本が0冊でした。ログイン状態を確認してください。")
        return 2

    res = notion_sync(cfg, books, date.today().isoformat())
    print(
        f"完了: 対象 {res['total']} / 新規 {res['inserted']} / "
        f"重複 {res['skipped']} / 失敗 {res['failed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
