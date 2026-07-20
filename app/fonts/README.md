# Bundled fonts — Noto Sans JP

These font files are bundled so the app renders with the **same typeface on
Windows and macOS**, without requiring a system-wide font install. They are
registered into the running process at startup by `register_bundled_fonts()` in
[`../gui.py`](../gui.py) and picked up by `_resolve_fonts()`.

| File | Family (as seen by Tk) | Used for |
|---|---|---|
| `NotoSansJP-Regular.otf` | `Noto Sans JP` | body / labels / logs |
| `NotoSansJP-Medium.otf` | `Noto Sans JP Medium` | headings / buttons |

## Source

Static Japanese-subset OTFs from the Noto CJK project:
<https://github.com/notofonts/noto-cjk> (`Sans/SubsetOTF/JP/`).

## License

SIL Open Font License, Version 1.1 — see [`OFL.txt`](OFL.txt). The OFL permits
bundling and redistribution with the application.

## Packaging

The build scripts ship this folder into the app bundle:

- Windows — `--add-data "%APP%\fonts;fonts"` (see `win-app/build_win.bat`)
- macOS — `--add-data "$APP/fonts:fonts"` (see `mac-app/build_mac.command`)

If these files are absent, the app still runs and falls back to the best
per-OS system font.
