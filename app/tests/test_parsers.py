"""HTML parsers for the Kindle notebook pages."""
from bs4 import BeautifulSoup

import kindle_notion as k


BOOKS_HTML = """
<div class="kp-notebook-library-each-book" id="B001ABC">
  <h2 class="kp-notebook-searchable">Book One</h2>
  <p class="kp-notebook-searchable">著者: Jane Doe</p>
</div>
<div class="kp-notebook-library-each-book" id="B002XYZ">
  <h2 class="kp-notebook-searchable">Book Two</h2>
  <p class="kp-notebook-searchable">著者：山田太郎</p>
</div>
<div class="kp-notebook-library-each-book">
  <h2 class="kp-notebook-searchable">Has no id, must be skipped</h2>
</div>
"""


def test_parse_books_reads_asin_title_author():
    books = k.parse_books(BOOKS_HTML)
    assert len(books) == 2  # the id-less book is skipped
    assert books[0] == {"asin": "B001ABC", "title": "Book One", "author": "Jane Doe"}


def test_parse_books_strips_author_prefix_both_colon_forms():
    books = k.parse_books(BOOKS_HTML)
    # "著者:" (ASCII colon) and "著者：" (full-width colon) both stripped
    assert books[0]["author"] == "Jane Doe"
    assert books[1]["author"] == "山田太郎"


def test_parse_books_empty_html():
    assert k.parse_books("<html></html>") == []


def _row(html):
    return BeautifulSoup(html, "html.parser")


def test_extract_color_from_highlight_class():
    row = _row('<div><span class="kp-notebook-highlight-pink">x</span></div>')
    assert k.extract_color(row, None) == "ピンク"


def test_extract_color_falls_back_to_header_text():
    row = _row("<div><span>x</span></div>")
    assert k.extract_color(row, "青のハイライト | 位置: 5") == "青"


def test_extract_color_returns_none_when_unknown():
    row = _row("<div><span>x</span></div>")
    assert k.extract_color(row, "no colour named here") is None


ANNOTATIONS_HTML = """
<div id="kp-notebook-annotations">
  <div id="QW1abc" class="a-row">
    <span id="annotationHighlightHeader">黄色 のハイライト | 位置: 123</span>
    <input id="kp-annotation-location" value="123"/>
    <span id="highlight" class="kp-notebook-highlight-yellow">This is a highlight.</span>
  </div>
  <div id="QW2def" class="a-row">
    <span id="note">My note text</span>
  </div>
  <div id="emptyRow" class="a-row"><span>nothing useful</span></div>
</div>
<input class="kp-notebook-annotations-next-page-start" value="NEXTTOK"/>
<input class="kp-notebook-content-limit-state" value="CLS1"/>
"""


def test_parse_annotations_rows_tokens_and_state():
    res = k.parse_annotations(ANNOTATIONS_HTML)
    assert res["next_token"] == "NEXTTOK"
    assert res["content_limit_state"] == "CLS1"

    anns = res["annotations"]
    assert len(anns) == 2  # the empty row (no #highlight / #note) is dropped

    a0 = anns[0]
    assert a0["id"] == "QW1abc"
    assert a0["highlight"] == "This is a highlight."
    assert a0["color"] == "黄色"
    assert a0["location"] == "123"

    a1 = anns[1]
    assert a1["id"] == "QW2def"
    assert a1["note"] == "My note text"
    assert a1["highlight"] is None


def test_parse_annotations_missing_pagination_yields_empty_tokens():
    html = (
        '<div id="kp-notebook-annotations">'
        '<div id="R1"><span id="highlight">h</span></div>'
        "</div>"
    )
    res = k.parse_annotations(html)
    assert res["next_token"] == ""
    assert res["content_limit_state"] == ""
    assert len(res["annotations"]) == 1


def test_next_library_token_present_and_absent():
    html = '<input class="kp-notebook-library-next-page-start" value="TOK123"/>'
    assert k._next_library_token(html) == "TOK123"
    assert k._next_library_token("<div>nothing</div>") == ""
