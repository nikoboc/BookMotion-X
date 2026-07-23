#!/bin/bash
# Build Booklight.app on macOS. Run this ONCE on a Mac (double-click it).
# PyInstaller cannot cross-compile, so the .app must be built on a Mac.
cd "$(dirname "$0")" || exit 1
APP="../app"   # shared code lives here; venv + dist stay in mac-app/

# Pick a python3 whose tkinter has Tk >= 8.6 (Apple's built-in python3 links the
# deprecated system Tk 8.5.9, which crashes the bundled app on launch). See
# _pick_python.sh for the full explanation.
source "./_pick_python.sh"

echo "== ビルド環境を準備 =="
PYBIN="$(pick_python)" || exit 1
echo "使用する Python: $PYBIN (Tk $("$PYBIN" -c 'import tkinter; print(tkinter.TkVersion)'))"

"$PYBIN" -m venv .buildvenv || { echo "venv の作成に失敗しました"; exit 1; }
./.buildvenv/bin/pip install --quiet --upgrade pip
./.buildvenv/bin/pip install --quiet -r "$APP/requirements.txt" pyinstaller

echo "== .appをビルド中 (数分かかります) =="
# --clean wipes PyInstaller's cache first, so a dependency added to
# requirements.txt (e.g. pillow) is always picked up on a rebuild.
./.buildvenv/bin/pyinstaller --clean --noconfirm --windowed --name "Booklight" \
  --osx-bundle-identifier "com.local.booklight" \
  --icon "$APP/icons/appicon.icns" \
  --paths "$APP" \
  --add-data "$APP/fonts:fonts" \
  --add-data "$APP/icons:icons" \
  --collect-all certifi \
  --collect-all customtkinter \
  --collect-all darkdetect \
  --collect-all webview \
  --hidden-import kindle_login \
  "$APP/gui.py"

echo ""
if [ -d "dist/Booklight.app" ]; then
  echo "完成: $(pwd)/dist/Booklight.app"
  echo "初回起動: Finder で右クリック →「開く」(未署名のためGatekeeper対策)"
else
  echo "ビルドに失敗しました。上のログを確認してください。"
fi
echo "このウィンドウは閉じてOKです。"
