#!/bin/bash
# Build KindleNotion.app on macOS. Run this ONCE on a Mac (double-click it).
# PyInstaller cannot cross-compile, so the .app must be built on a Mac.
cd "$(dirname "$0")" || exit 1
APP="../app"   # shared code lives here; venv + dist stay in mac-app/

echo "== ビルド環境を準備 =="
python3 -m venv .buildvenv || { echo "python3 が必要です (xcode-select --install など)"; exit 1; }
./.buildvenv/bin/pip install --quiet --upgrade pip
./.buildvenv/bin/pip install --quiet -r "$APP/requirements.txt" pyinstaller

echo "== .appをビルド中 (数分かかります) =="
./.buildvenv/bin/pyinstaller --noconfirm --windowed --name "KindleNotion" \
  --osx-bundle-identifier "com.local.kindlenotion" \
  --paths "$APP" \
  --add-data "$APP/fonts:fonts" \
  --collect-all certifi \
  --collect-all customtkinter \
  --collect-all darkdetect \
  "$APP/gui.py"

echo ""
if [ -d "dist/KindleNotion.app" ]; then
  echo "完成: $(pwd)/dist/KindleNotion.app"
  echo "初回起動: Finder で右クリック →「開く」(未署名のためGatekeeper対策)"
else
  echo "ビルドに失敗しました。上のログを確認してください。"
fi
echo "このウィンドウは閉じてOKです。"
