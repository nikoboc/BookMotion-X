"""Shared test setup.

The core module lives at app/kindle_notion.py and is imported as the top-level
`kindle_notion` (it is not a package), so put app/ on sys.path before importing
it. Doing it here means every test module can just `import kindle_notion`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import kindle_notion as k  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_language():
    """Restore the module-global LANG after tests that call set_language()."""
    saved = k.LANG
    yield
    k.LANG = saved
