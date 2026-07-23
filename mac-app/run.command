#!/bin/bash
# Double-click launcher for macOS: runs the Booklight GUI from source (no build).
# First run sets up a local venv + deps. For the command-line sync tool instead,
# see the "デバッグ用" section of BUILD_RUN_mac.md (kindle_notion.py -c cookies.txt).
cd "$(dirname "$0")" || exit 1
APP="../app"   # shared code lives here; the venv stays in mac-app/

# The GUI is Tkinter/CustomTkinter, so it needs a python3 with Tk >= 8.6 — see
# _pick_python.sh. Apple's built-in python3 (Tk 8.5.9) crashes the GUI on launch.
source "./_pick_python.sh"

# (Re)create the venv if it's missing OR its Python's Tk is too old — e.g. a
# venv made by an earlier version of this script with Apple's python3, whose
# system Tk 8.5.9 would crash the GUI. tk_ok reads the version without starting
# Tk, so it's safe to run against that interpreter.
if [ ! -x ".venv/bin/python" ]; then
  NEED_VENV=1
elif ! tk_ok "./.venv/bin/python"; then
  echo "既存の .venv の Tk が古い (8.5) ため作り直します…"
  rm -rf .venv
  NEED_VENV=1
else
  NEED_VENV=0
fi

if [ "$NEED_VENV" = 1 ]; then
  PYBIN="$(pick_python)" || exit 1
  echo "初回セットアップ: 仮想環境と依存関係を準備します ($PYBIN, Tk $("$PYBIN" -c 'import tkinter; print(tkinter.TkVersion)'))…"
  "$PYBIN" -m venv .venv || { echo "venv の作成に失敗しました"; exit 1; }
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r "$APP/requirements.txt"
fi

# Launch the GUI. Kindle sign-in happens in-app (WKWebView); no cookies.txt.
./.venv/bin/python "$APP/gui.py" "$@"
STATUS=$?

echo ""
if [ $STATUS -ne 0 ]; then
  echo "エラーで終了しました (code $STATUS)。上のメッセージを確認してください。"
fi
echo "このウィンドウは閉じてOKです。"
