#!/bin/bash
# Shared helper for build_mac.command / run.command.
#
# Booklight's UI is Tkinter/CustomTkinter. Apple's built-in python3 (Command
# Line Tools) links the DEPRECATED system Tcl/Tk 8.5.9, which aborts on modern
# macOS (Tcl_Panic in TkpInit → SIGABRT) the moment a window is created. So the
# GUI must be built/run with a python3 whose tkinter has Tk >= 8.6 (python.org
# and Homebrew builds ship it). `brew install python-tk` does NOT fix Apple's
# python3 — it uses its own system Tk regardless.

# Succeeds only if $1's tkinter has Tk >= 8.6. Reads the compiled Tk version
# (no Tk root is created), so the broken 8.5 build reports 8.5 instead of
# crashing this check.
tk_ok() {
  "$1" -c 'import sys, tkinter; sys.exit(0 if float(tkinter.TkVersion) >= 8.6 else 1)' \
    >/dev/null 2>&1
}

# Prints a suitable interpreter path to stdout and returns 0; on failure prints
# guidance to stderr and returns 1. Candidates, best first: python.org framework
# builds, Homebrew (arm/intel), then whatever python3 is on PATH (often Apple's).
pick_python() {
  local c v cands=()
  for v in 3.13 3.12 3.11 3.10; do
    cands+=("/Library/Frameworks/Python.framework/Versions/$v/bin/python3")
  done
  cands+=("/opt/homebrew/bin/python3" "/usr/local/bin/python3" "$(command -v python3)")
  for c in "${cands[@]}"; do
    [ -n "$c" ] && [ -x "$c" ] || continue
    if tk_ok "$c"; then printf '%s\n' "$c"; return 0; fi
  done
  {
    echo "エラー: Tk 8.6 以上を持つ python3 が見つかりませんでした。"
    echo "Apple 標準の python3 は廃止済みの Tk 8.5.9 を使うため、GUI は起動時に"
    echo "クラッシュします (Tcl_Panic in TkpInit)。次のいずれかを入れてください:"
    echo "  1) python.org 版 Python (Tk 8.6 同梱・推奨): https://www.python.org/downloads/macos/"
    echo "  2) Homebrew: brew install python python-tk"
  } >&2
  return 1
}
