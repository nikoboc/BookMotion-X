"""Pure Notion-side helpers: id normalisation, rich_text chunking, row building."""
import kindle_notion as k


# ---- normalize_id / database_url --------------------------------------------
def test_normalize_id_from_notion_url():
    url = "https://www.notion.so/My-Notes-1234567890abcdef1234567890abcdef?pvs=4"
    assert k.normalize_id(url) == "12345678-90ab-cdef-1234-567890abcdef"


def test_normalize_id_slug_ending_in_hex_letter_does_not_shift_id():
    # regression: "Page" / "Archive" end in a hex letter (e). After dashes are
    # stripped it abuts the id; the right-boundary match must still return the id.
    url = "https://www.notion.so/Reading-Archive-1234567890abcdef1234567890abcdef"
    assert k.normalize_id(url) == "12345678-90ab-cdef-1234-567890abcdef"


def test_normalize_id_ignores_trailing_view_id_in_query():
    # page id in the path, a different 32-hex view id in ?v= — keep the page id
    page = "1234567890abcdef1234567890abcdef"
    view = "fedcba0987654321fedcba0987654321"
    assert k.normalize_id(f"https://www.notion.so/Title-{page}?v={view}") == \
        "12345678-90ab-cdef-1234-567890abcdef"


def test_normalize_id_dashed_uuid_round_trips():
    v = "12345678-90ab-cdef-1234-567890abcdef"
    assert k.normalize_id(v) == v


def test_normalize_id_empty_and_no_hex():
    assert k.normalize_id("") == ""
    assert k.normalize_id("  just text  ") == "just text"


def test_database_url_valid_and_invalid():
    v = "12345678-90ab-cdef-1234-567890abcdef"
    assert k.database_url(v) == "https://www.notion.so/1234567890abcdef1234567890abcdef"
    assert k.database_url("") == ""
    assert k.database_url("too-short") == ""


# ---- rich_text (2000-char chunking) -----------------------------------------
def test_rich_text_short_single_chunk():
    assert k.rich_text("hello") == [{"type": "text", "text": {"content": "hello"}}]


def test_rich_text_splits_on_2000_char_boundary():
    chunks = k.rich_text("a" * 4500)
    assert [len(c["text"]["content"]) for c in chunks] == [2000, 2000, 500]


def test_rich_text_empty_and_none_are_no_chunks():
    assert k.rich_text("") == []
    assert k.rich_text(None) == []


# ---- page_properties --------------------------------------------------------
def _row(**over):
    base = {"quote": "Q", "title": "T", "author": "A", "date": "2026-07-22",
            "key": "KID", "location": 42, "color": "黄色"}
    base.update(over)
    return base


def test_page_properties_full_row():
    props = k.page_properties(_row())
    assert props["ハイライト文"]["title"] == [{"type": "text", "text": {"content": "Q"}}]
    assert props["位置"] == {"number": 42}
    assert props["マーカー色"] == {"select": {"name": "黄色"}}
    assert props["実行日"] == {"date": {"start": "2026-07-22"}}
    assert props["注釈ID"]["rich_text"][0]["text"]["content"] == "KID"


def test_page_properties_omits_absent_location_and_color():
    props = k.page_properties(_row(location=None, color=None))
    assert "位置" not in props
    assert "マーカー色" not in props


def test_page_properties_keeps_location_zero():
    # location 0 is a real value, not "missing" (must survive the None check)
    props = k.page_properties(_row(location=0))
    assert props["位置"] == {"number": 0}


# ---- build_rows -------------------------------------------------------------
def _books():
    return [
        {
            "title": "Zeta", "author": "著者 X",
            "annotations": [
                {"id": "A1", "highlight": "h1", "location": "位置 200", "color": "青"},
                {"id": None, "highlight": "h2", "location": "100"},
                {"id": "A3", "highlight": None, "location": "50"},  # no highlight -> dropped
            ],
        },
        {
            "title": "Alpha", "author": "",
            "annotations": [
                {"id": "B1", "highlight": "hA", "location": None, "color": None},
            ],
        },
    ]


def test_build_rows_drops_highlightless_rows():
    rows = k.build_rows(_books(), "2026-07-22")
    assert len(rows) == 3  # A3 (no highlight) excluded


def test_build_rows_sorts_by_title_then_location():
    rows = k.build_rows(_books(), "2026-07-22")
    assert [r["title"] for r in rows] == ["Alpha", "Zeta", "Zeta"]
    zeta = [r for r in rows if r["title"] == "Zeta"]
    assert [r["location"] for r in zeta] == [100, 200]


def test_build_rows_parses_location_digits_from_noisy_string():
    rows = k.build_rows(_books(), "2026-07-22")
    row200 = next(r for r in rows if r["id"] == "A1")
    assert row200["location"] == 200  # from "位置 200"


def test_build_rows_dedup_key_uses_id_or_composite():
    rows = k.build_rows(_books(), "2026-07-22")
    with_id = next(r for r in rows if r["id"] == "A1")
    assert with_id["key"] == "A1"
    id_less = next(r for r in rows if r["id"] is None)
    assert id_less["key"] == "Zeta|100|h2"  # title|location|quote[:40]


def test_build_rows_stamps_the_run_date():
    rows = k.build_rows(_books(), "2026-07-22")
    assert all(r["date"] == "2026-07-22" for r in rows)


def test_build_rows_dedups_same_annotation_id_within_run():
    # Regression: a paginated fetch can return the same annotation on adjacent
    # pages (boundary overlap). Notion-side dedup only compares against the DB, so
    # build_rows must collapse in-run duplicates or they get inserted twice with
    # an identical 注釈ID.
    books = [{
        "title": "Book A", "author": "A",
        "annotations": [
            {"id": "ANN-1", "highlight": "H1", "location": "100"},
            {"id": "ANN-2", "highlight": "H2", "location": "200"},
            {"id": "ANN-1", "highlight": "H1", "location": "100"},  # duplicate
        ],
    }]
    rows = k.build_rows(books, "2026-07-22")
    assert [r["key"] for r in rows] == ["ANN-1", "ANN-2"]  # ANN-1 kept once


def test_build_rows_dedups_idless_highlights_by_composite_key():
    # Id-less duplicates (no annotation id) collapse on the title|location|quote key.
    books = [{
        "title": "Book A", "author": "A",
        "annotations": [
            {"id": None, "highlight": "same text", "location": "50"},
            {"id": None, "highlight": "same text", "location": "50"},  # duplicate
        ],
    }]
    rows = k.build_rows(books, "2026-07-22")
    assert len(rows) == 1
    assert rows[0]["key"] == "Book A|50|same text"
