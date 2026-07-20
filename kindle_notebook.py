#!/usr/bin/env python3
"""Fetch Kindle highlights & notes from read.amazon.co.jp/notebook.

Uses the login cookies of a browser you're already signed in with
(via browser_cookie3), so no password handling / 2FA automation is needed.

Usage:
    python kindle_notebook.py                 # auto-detect browser, print JSON
    python kindle_notebook.py -b firefox      # force a specific browser
    python kindle_notebook.py -o out.json     # write to a file
    python kindle_notebook.py --debug-html     # dump raw HTML for inspection
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.cookiejar import MozillaCookieJar
from typing import Optional

import browser_cookie3
import requests
from bs4 import BeautifulSoup

BASE = "https://read.amazon.co.jp"
NOTEBOOK_URL = f"{BASE}/notebook"
DOMAIN = "amazon.co.jp"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
# Browsers to try, in order, when none is specified.
BROWSER_ORDER = ["chrome", "edge", "firefox", "brave", "chromium", "opera"]


def load_cookies(browser: Optional[str]):
    """Return a cookiejar of amazon.co.jp cookies from the given browser.

    If browser is None, try a list of common browsers and use the first
    that yields any amazon.co.jp cookies.
    """
    candidates = [browser] if browser else BROWSER_ORDER
    last_err = None
    for name in candidates:
        fn = getattr(browser_cookie3, name, None)
        if fn is None:
            continue
        try:
            cj = fn(domain_name=DOMAIN)
            if len(cj) > 0:
                print(f"[info] loaded {len(cj)} cookies from {name}", file=sys.stderr)
                return cj
            print(f"[info] {name}: no {DOMAIN} cookies", file=sys.stderr)
        except Exception as e:  # locked DB, decryption failure, not installed...
            last_err = e
            print(f"[info] {name}: {e}", file=sys.stderr)
    if last_err and browser:
        raise last_err
    raise RuntimeError(
        f"No {DOMAIN} cookies found in any browser. "
        f"Log in at {BASE} in your browser first, then retry (or pass -b)."
    )


def load_cookies_file(path: str):
    """Load cookies from a manually exported file.

    Supports Netscape/Mozilla cookies.txt (from the "Get cookies.txt LOCALLY"
    extension) or a JSON array export (from "Cookie-Editor" / "EditThisCookie").
    This path needs no admin rights and works regardless of Chrome's
    app-bound encryption.
    """
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        jar = requests.cookies.RequestsCookieJar()
        for c in data:
            jar.set(
                c["name"],
                c["value"],
                domain=c.get("domain", "").lstrip("."),
                path=c.get("path", "/"),
            )
        print(f"[info] loaded {len(jar)} cookies from {path}", file=sys.stderr)
        return jar
    cj = MozillaCookieJar()
    cj.load(path, ignore_discard=True, ignore_expires=True)
    print(f"[info] loaded {len(cj)} cookies from {path}", file=sys.stderr)
    return cj


def make_session(browser: Optional[str], cookies_file: Optional[str]) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ja,en;q=0.9"})
    jar = load_cookies_file(cookies_file) if cookies_file else load_cookies(browser)
    for c in jar:
        s.cookies.set_cookie(c)
    return s


def looks_logged_out(resp: requests.Response, soup: BeautifulSoup) -> bool:
    if "/ap/signin" in resp.url or "signin" in resp.url:
        return True
    # The library container is only present when authenticated.
    if soup.select_one("#library") or soup.select_one(".kp-notebook-library-each-book"):
        return False
    # Sign-in form present?
    if soup.select_one("form[name='signIn']") or soup.select_one("#ap_email"):
        return True
    return False


def parse_library(soup: BeautifulSoup) -> list[dict]:
    books = []
    for div in soup.select(".kp-notebook-library-each-book"):
        asin = div.get("id")
        title_el = div.select_one("h2.kp-notebook-searchable")
        author_el = div.select_one("p.kp-notebook-searchable")
        if not asin:
            continue
        books.append(
            {
                "asin": asin,
                "title": title_el.get_text(strip=True) if title_el else None,
                "author": author_el.get_text(strip=True) if author_el else None,
            }
        )
    return books


def parse_annotations(soup: BeautifulSoup) -> list[dict]:
    """Parse highlight/note annotations from a book's notebook page."""
    out = []
    # Each annotation is an element carrying its own id (the annotation id);
    # highlight text/note/location live inside as spans with fixed ids.
    for row in soup.select("#kp-notebook-annotations > div, .kp-notebook-row-separator"):
        hl = row.select_one("#highlight")
        note = row.select_one("#note")
        header = row.select_one("#annotationHighlightHeader") or row.select_one(
            "#annotationNoteHeader"
        )
        loc = row.select_one("#kp-annotation-location")
        highlight_text = hl.get_text(strip=True) if hl else None
        note_text = note.get_text(strip=True) if note else None
        if not highlight_text and not note_text:
            continue
        out.append(
            {
                "highlight": highlight_text,
                "note": note_text or None,
                "header": header.get_text(strip=True) if header else None,
                "location": loc.get("value") if loc else None,
            }
        )
    return out


def fetch_book(session: requests.Session, asin: str, debug=False) -> list[dict]:
    annotations = []
    token = None
    content_limit_state = ""
    page = 0
    while True:
        params = {"asin": asin, "contentLimitState": content_limit_state}
        if token:
            params["token"] = token
        r = session.get(NOTEBOOK_URL, params=params, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        if debug and page == 0:
            with open(f"debug_{asin}.html", "w", encoding="utf-8") as f:
                f.write(r.text)
        annotations.extend(parse_annotations(soup))

        nxt = soup.select_one(".kp-notebook-annotations-next-page-start")
        cls = soup.select_one(".kp-notebook-content-limit-state")
        content_limit_state = cls.get("value", "") if cls else ""
        token = nxt.get("value") if nxt and nxt.get("value") else None
        page += 1
        if not token:
            break
        time.sleep(0.3)  # be polite
    return annotations


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape Kindle highlights to JSON.")
    ap.add_argument("-b", "--browser", help="chrome|edge|firefox|brave|chromium|opera")
    ap.add_argument(
        "-c",
        "--cookies-file",
        help="Path to exported cookies (.txt Netscape or .json). "
        "Bypasses browser auto-detection and Chrome app-bound encryption.",
    )
    ap.add_argument("-o", "--output", help="Write JSON here (default: stdout)")
    ap.add_argument("--debug-html", action="store_true", help="Dump raw HTML per book")
    ap.add_argument("--limit", type=int, help="Only fetch the first N books")
    args = ap.parse_args()

    session = make_session(args.browser, args.cookies_file)

    r = session.get(NOTEBOOK_URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    if args.debug_html:
        with open("debug_library.html", "w", encoding="utf-8") as f:
            f.write(r.text)

    if looks_logged_out(r, soup):
        print(
            "[error] Not logged in. Open https://read.amazon.co.jp/notebook in your "
            "browser, sign in, then rerun.",
            file=sys.stderr,
        )
        return 2

    books = parse_library(soup)
    print(f"[info] found {len(books)} books", file=sys.stderr)
    if args.limit:
        books = books[: args.limit]

    for i, book in enumerate(books, 1):
        print(f"[info] ({i}/{len(books)}) {book.get('title')}", file=sys.stderr)
        book["annotations"] = fetch_book(session, book["asin"], debug=args.debug_html)
        book["annotation_count"] = len(book["annotations"])

    result = {"source": NOTEBOOK_URL, "book_count": len(books), "books": books}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[info] wrote {args.output}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
