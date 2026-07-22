"""Config/cookie locations: legacy-data migration and path resolution."""
from http.cookiejar import MozillaCookieJar

import kindle_notion as k


# ---- _migrate_legacy_data ---------------------------------------------------
def test_migrate_copies_both_files_non_destructively(tmp_path):
    legacy, base = tmp_path / "old", tmp_path / "new"
    legacy.mkdir()
    base.mkdir()
    (legacy / "config.json").write_text('{"notion_token":"x"}', encoding="utf-8")
    (legacy / "cookies.txt").write_text("cookie-data", encoding="utf-8")

    k._migrate_legacy_data(legacy, base)

    assert (base / "config.json").read_text(encoding="utf-8") == '{"notion_token":"x"}'
    assert (base / "cookies.txt").read_text(encoding="utf-8") == "cookie-data"
    # source is left in place as a backup
    assert (legacy / "config.json").exists()
    assert (legacy / "cookies.txt").exists()


def test_migrate_never_overwrites_existing_new_data(tmp_path):
    legacy, base = tmp_path / "old", tmp_path / "new"
    legacy.mkdir()
    base.mkdir()
    (legacy / "config.json").write_text("OLD", encoding="utf-8")
    (base / "config.json").write_text("KEEP", encoding="utf-8")

    k._migrate_legacy_data(legacy, base)

    assert (base / "config.json").read_text(encoding="utf-8") == "KEEP"


def test_migrate_with_missing_legacy_is_a_noop(tmp_path):
    base = tmp_path / "new"
    base.mkdir()
    k._migrate_legacy_data(tmp_path / "does-not-exist", base)
    assert not (base / "config.json").exists()


def test_migrate_same_dir_is_a_noop(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "config.json").write_text("x", encoding="utf-8")
    k._migrate_legacy_data(d, d)  # must not copy a file onto itself / raise
    assert (d / "config.json").read_text(encoding="utf-8") == "x"


# ---- get_config_path (dev / non-frozen) -------------------------------------
def _force_dev_mode(monkeypatch):
    monkeypatch.setattr(k.sys, "frozen", False, raising=False)


def test_config_path_prefers_local_next_to_script(monkeypatch, tmp_path):
    _force_dev_mode(monkeypatch)
    local = tmp_path / "config.json"
    local.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(k, "LOCAL_CONFIG", local)
    assert k.get_config_path() == local


def test_config_path_falls_back_to_booklight_home(monkeypatch, tmp_path):
    _force_dev_mode(monkeypatch)
    home = tmp_path / ".booklight" / "config.json"
    home.parent.mkdir(parents=True)
    home.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(k, "LOCAL_CONFIG", tmp_path / "absent.json")
    monkeypatch.setattr(k, "HOME_CONFIG", home)
    monkeypatch.setattr(k, "LEGACY_HOME_CONFIG", tmp_path / ".kindle-notion" / "config.json")
    assert k.get_config_path() == home


def test_config_path_falls_back_to_legacy_home_when_only_that_exists(monkeypatch, tmp_path):
    _force_dev_mode(monkeypatch)
    legacy = tmp_path / ".kindle-notion" / "config.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(k, "LOCAL_CONFIG", tmp_path / "absent.json")
    monkeypatch.setattr(k, "HOME_CONFIG", tmp_path / ".booklight" / "config.json")
    monkeypatch.setattr(k, "LEGACY_HOME_CONFIG", legacy)
    assert k.get_config_path() == legacy


def test_config_path_defaults_to_local_when_nothing_exists(monkeypatch, tmp_path):
    _force_dev_mode(monkeypatch)
    local = tmp_path / "config.json"  # not created
    monkeypatch.setattr(k, "LOCAL_CONFIG", local)
    monkeypatch.setattr(k, "HOME_CONFIG", tmp_path / ".booklight" / "config.json")
    monkeypatch.setattr(k, "LEGACY_HOME_CONFIG", tmp_path / ".kindle-notion" / "config.json")
    assert k.get_config_path() == local


# ---- _packaged_data_dir (frozen) --------------------------------------------
def test_packaged_data_dir_windows_migrates_legacy(monkeypatch, tmp_path):
    monkeypatch.setattr(k.sys, "platform", "win32")
    monkeypatch.setattr(k.Path, "home", staticmethod(lambda: tmp_path))
    legacy = tmp_path / ".kindle-notion"
    legacy.mkdir()
    (legacy / "config.json").write_text("CFG", encoding="utf-8")

    base = k._packaged_data_dir()

    assert base == tmp_path / ".booklight"
    assert base.is_dir()
    assert (base / "config.json").read_text(encoding="utf-8") == "CFG"


def test_packaged_data_dir_macos_location(monkeypatch, tmp_path):
    monkeypatch.setattr(k.sys, "platform", "darwin")
    monkeypatch.setattr(k.Path, "home", staticmethod(lambda: tmp_path))

    base = k._packaged_data_dir()

    assert base == tmp_path / "Library" / "Application Support" / "Booklight"
    assert base.is_dir()


# ---- save_cookies -----------------------------------------------------------
def test_save_cookies_keeps_only_amazon_and_tolerates_bad_expiry(monkeypatch, tmp_path):
    dst = tmp_path / "cookies.txt"
    monkeypatch.setattr(k, "get_cookies_path", lambda: dst)
    cookies = [
        {"name": "at-main", "value": "v1", "domain": ".amazon.co.jp",
         "path": "/", "expires": 9999999999, "secure": True},
        {"name": "sess", "value": "v2", "domain": "read.amazon.co.jp",
         "expires": "not-a-number"},                       # bad expiry -> kept, no expiry
        {"name": "tracker", "value": "v3", "domain": ".doubleclick.net"},  # non-amazon -> dropped
        {"name": "", "value": "v4", "domain": ".amazon.com"},              # no name -> dropped
    ]

    n = k.save_cookies(cookies)

    assert n == 2
    jar = MozillaCookieJar(str(dst))
    jar.load(ignore_discard=True, ignore_expires=True)
    assert {c.name for c in jar} == {"at-main", "sess"}
