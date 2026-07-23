"""Fetch-side dedup: paginated Kindle pages can overlap at the boundary (the
next-page-start token re-includes the last item), so fetch_all_books dedups
books by ASIN and fetch_book_annotations dedups annotations by id.
"""
import kindle_notion as k


class _Resp:
    """Minimal stand-in for a requests.Response (only .text / .url are read)."""

    def __init__(self, text, url=k.NOTEBOOK):
        self.text = text
        self.url = url


class _FakeSession:
    """Returns queued responses in order, ignoring the request args."""

    def __init__(self, pages):
        self._pages = list(pages)

    def get(self, *args, **kwargs):
        return self._pages.pop(0)


def _book_div(asin, title):
    return (
        f'<div class="kp-notebook-library-each-book" id="{asin}">'
        f'<h2 class="kp-notebook-searchable">{title}</h2></div>'
    )


def _lib_page(book_divs, next_token=""):
    tok = (
        f'<input class="kp-notebook-library-next-page-start" value="{next_token}"/>'
        if next_token else ""
    )
    return "".join(book_divs) + tok


def _ann_div(ann_id, text, loc):
    return (
        f'<div id="{ann_id}" class="a-row">'
        f'<input id="kp-annotation-location" value="{loc}"/>'
        f'<span id="highlight">{text}</span></div>'
    )


def _ann_page(ann_divs, next_token=""):
    tok = (
        f'<input class="kp-notebook-annotations-next-page-start" value="{next_token}"/>'
        if next_token else ""
    )
    return f'<div id="kp-notebook-annotations">{"".join(ann_divs)}</div>' + tok


# ---- fetch_all_books: dedup books by ASIN -----------------------------------
def test_fetch_all_books_dedups_boundary_book_by_asin():
    # Page 1 -> B1, B2 (+ token). Page 2 re-includes B2 (overlap), then B3.
    page1 = _lib_page([_book_div("B1", "One"), _book_div("B2", "Two")], next_token="T2")
    page2 = _lib_page([_book_div("B2", "Two"), _book_div("B3", "Three")])
    session = _FakeSession([_Resp(page1), _Resp(page2)])

    books = k.fetch_all_books(session)
    assert [b["asin"] for b in books] == ["B1", "B2", "B3"]  # B2 kept once


# ---- fetch_book_annotations: dedup annotations by id ------------------------
def test_fetch_book_annotations_dedups_boundary_highlight_by_id():
    # Page 1 -> A1, A2 (+ token). Page 2 re-includes A2 (overlap), then A3.
    page1 = _ann_page([_ann_div("A1", "h1", 10), _ann_div("A2", "h2", 20)], next_token="N2")
    page2 = _ann_page([_ann_div("A2", "h2", 20), _ann_div("A3", "h3", 30)])
    session = _FakeSession([_Resp(page1), _Resp(page2)])

    anns = k.fetch_book_annotations(session, "B1")
    assert [a["id"] for a in anns] == ["A1", "A2", "A3"]  # A2 kept once


def test_fetch_book_annotations_keeps_distinct_idless_highlights():
    # Two different id-less highlights on one page must NOT be collapsed here
    # (dedup is by id; composite-key dedup happens later in build_rows).
    page = _ann_page([
        '<div class="a-row"><span id="highlight">first</span></div>',
        '<div class="a-row"><span id="highlight">second</span></div>',
    ])
    session = _FakeSession([_Resp(page)])

    anns = k.fetch_book_annotations(session, "B1")
    assert [a["highlight"] for a in anns] == ["first", "second"]
