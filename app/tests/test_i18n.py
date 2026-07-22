"""Runtime-message i18n: set_language / t / _detect_os_lang."""
import kindle_notion as k


def test_japanese_lookup_is_default_pair():
    k.set_language("ja")
    assert k.t("cli_error") == "エラー:"


def test_english_lookup():
    k.set_language("en")
    assert k.t("cli_error") == "Error:"


def test_unknown_key_falls_back_to_the_key_itself():
    k.set_language("en")
    assert k.t("no_such_key_xyz") == "no_such_key_xyz"


def test_placeholder_formatting():
    k.set_language("en")
    assert k.t("log_books_found").format(n=3) == "Found 3 books"


def test_set_language_direct_values():
    assert k.set_language("ja") == "ja"
    assert k.set_language("en") == "en"


def test_set_language_auto_delegates_to_detection(monkeypatch):
    monkeypatch.setattr(k, "_detect_os_lang", lambda: "en")
    assert k.set_language("auto") == "en"
    assert k.LANG == "en"


def test_set_language_unknown_delegates_to_detection(monkeypatch):
    monkeypatch.setattr(k, "_detect_os_lang", lambda: "ja")
    assert k.set_language("klingon") == "ja"


def test_detect_os_lang_returns_a_supported_code():
    assert k._detect_os_lang() in ("ja", "en")


def test_detect_os_lang_locale_japanese(monkeypatch):
    monkeypatch.setattr(k.sys, "platform", "linux")
    monkeypatch.setattr(k.locale, "getlocale", lambda *a: ("ja_JP", "UTF-8"))
    assert k._detect_os_lang() == "ja"


def test_detect_os_lang_locale_english(monkeypatch):
    monkeypatch.setattr(k.sys, "platform", "linux")
    monkeypatch.setattr(k.locale, "getlocale", lambda *a: ("en_US", "UTF-8"))
    assert k._detect_os_lang() == "en"
