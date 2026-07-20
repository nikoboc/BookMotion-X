#!/bin/bash
# Build KindleNotion.app on macOS. Run this ONCE on a Mac (double-click it).
# PyInstaller cannot cross-compile, so the .app must be built on a Mac.
cd "$(dirname "$0")" || exit 1

echo "== ビルド環境を準備 =="
python3 -m venv .buildvenv || { echo "python3 が必要です (xcode-select --install など)"; exit 1; }
./.buildvenv/bin/pip install --quiet --upgrade pip
./.buildvenv/bin/pip install --quiet -r requirements.txt pyinstaller

echo "== .app をビルド中 (数分かかります) =="
./.buildvenv/bin/pyinstaller --noconfirm --windowed --name "KindleNotion" \
  --osx-bundle-identifier "com.local.kindlenotion" \
  --collect-all certifi \
  --collect-all browser_cookie3 \
  gui.py

echo ""
if [ -d "dist/KindleNotion.app" ]; then
  echo "完成: $(pwd)/dist/KindleNotion.app"
  echo "初回起動: Finder で右クリック →「開く」(未署名のためGatekeeper対策)"
else
  echo "ビルドに失敗しました。上のログを確認してください。"
fi
echo "このウィンドウは閉じてOKです。"
