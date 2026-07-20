#!/bin/bash
# Double-click launcher for macOS. First run sets up a local venv + deps.
cd "$(dirname "$0")" || exit 1

if [ ! -d ".venv" ]; then
  echo "初回セットアップ: 仮想環境と依存関係を準備します…"
  python3 -m venv .venv || { echo "python3 が見つかりません。Xcodeコマンドラインツール(xcode-select --install)かHomebrewでPython3を入れてください。"; exit 1; }
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt
fi

./.venv/bin/python kindle_notion.py "$@"
STATUS=$?

echo ""
if [ $STATUS -ne 0 ]; then
  echo "エラーで終了しました (code $STATUS)。上のメッセージを確認してください。"
fi
echo "このウィンドウは閉じてOKです。"
