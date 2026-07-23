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


def test_parse_books_strips_english_by_prefix():
    html = """
    <div class="kp-notebook-library-each-book" id="B003EN">
      <h2 class="kp-notebook-searchable">Book Three</h2>
      <p class="kp-notebook-searchable">By: John Smith</p>
    </div>
    """
    books = k.parse_books(html)
    # The English "By:" prefix is stripped like the Japanese "著者:" form
    assert books[0]["author"] == "John Smith"


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


# ---- pagination fragments (no #kp-notebook-annotations wrapper) --------------
# The first ?asin= page is a full document WITH the #kp-notebook-annotations
# wrapper; every subsequent (paginated) page is a bare fragment WITHOUT it — just
# the annotation divs. The location input and header live in a sibling of the
# highlight span, so grouping must reach the whole annotation div, not the narrow
# highlight cell, or location + colour are lost (the real-world bug).
def _annotation_div(annid, loc, color_cls, text, note_text=None):
    if note_text is not None:
        note = (f'<div id="note-{annid}" class="a-row a-spacing-top-base kp-notebook-note">'
                f'<span id="note-label">メモ</span><span id="note">{note_text}</span></div>')
    else:
        note = ('<div id="note-" class="a-row a-spacing-top-base kp-notebook-note aok-hidden">'
                '<span id="note-label">メモ</span><span id="note"></span></div>')
    return (
        f'<div id="{annid}" class="a-row a-spacing-base">'
        f'<div class="a-column a-span10 kp-notebook-row-separator">'
        f'<div class="a-row"><input type="hidden" value="{loc}" id="kp-annotation-location"/>'
        f'<div class="a-column a-span8">'
        f'<span id="annotationHighlightHeader">色のハイライト | 位置: {loc}</span>'
        f'<span id="annotationNoteHeader" class="aok-hidden">メモ | 位置: {loc}</span>'
        f'</div></div>'
        f'<div class="a-row a-spacing-top-medium"><div class="a-column a-span10">'
        f'<div id="highlight-{annid}" class="a-row kp-notebook-highlight kp-notebook-highlight-{color_cls}">'
        f'<span id="highlight">{text}</span><div></div></div>'
        f'{note}'
        f'</div></div></div></div>'
    )


# Mirrors highlightapiresponse2.html: leading token inputs, two annotation divs
# (the first with a child note), then the empty-annotations-pane placeholder — all
# top-level, no #kp-notebook-annotations wrapper.
_FRAGMENT = (
    '<input type="hidden" name="" value="CLS1" class="kp-notebook-content-limit-state"/>'
    '<input type="hidden" name="" class="kp-notebook-annotations-next-page-start"/>'
    + _annotation_div("ANN1", "3213", "yellow", "first highlight", note_text="my note")
    + _annotation_div("ANN2", "3549", "pink", "second highlight")
    + '<div id="empty-annotations-pane" class="a-row aok-hidden"><span>make a note?</span></div>'
)


def test_parse_annotations_wrapperless_fragment_keeps_location_and_color():
    res = k.parse_annotations(_FRAGMENT)
    anns = res["annotations"]
    assert len(anns) == 2  # the empty-annotations-pane is not an annotation
    assert anns[0]["location"] == "3213" and anns[0]["color"] == "黄色"
    assert anns[0]["note"] == "my note"        # child note stays attached, not split
    assert anns[1]["location"] == "3549" and anns[1]["color"] == "ピンク"
    assert res["content_limit_state"] == "CLS1"
    assert res["next_token"] == ""             # empty next-page input -> last page


def test_parse_annotations_with_wrapper_still_works():
    html = ('<div id="kp-notebook-annotations">'
            + _annotation_div("ANN1", "12", "yellow", "hl")
            + "</div>")
    anns = k.parse_annotations(html)["annotations"]
    assert len(anns) == 1
    assert anns[0]["location"] == "12" and anns[0]["color"] == "黄色"


def test_parse_annotations_uses_header_location_when_input_missing():
    # No #kp-annotation-location input -> recover the number from the header text.
    html = ('<div id="ANN" class="a-row a-spacing-base">'
            '<span id="annotationHighlightHeader">黄色のハイライト | 位置: 999</span>'
            '<div id="highlight-ANN" class="a-row kp-notebook-highlight kp-notebook-highlight-yellow">'
            '<span id="highlight">text</span></div></div>')
    anns = k.parse_annotations(html)["annotations"]
    assert anns[0]["location"] == "999" and anns[0]["color"] == "黄色"


def test_extract_color_reads_class_on_the_row_element_itself():
    # In the deep fallback the row *is* the highlight div, so the colour class sits
    # on the row, not a descendant.
    inner = _row('<div class="a-row kp-notebook-highlight kp-notebook-highlight-orange">'
                 '<span id="highlight">x</span></div>').select_one("div")
    assert k.extract_color(inner, None) == "オレンジ"


def test_location_from_header_recovers_number_when_input_missing():
    assert k._location_from_header("黄色のハイライト | 位置: 3,213") == "3213"
    assert k._location_from_header("メモ | ページ: 12") == "12"
    assert k._location_from_header("Yellow highlight | Location: 4567") == "4567"
    assert k._location_from_header("no number here") is None
    assert k._location_from_header(None) is None
