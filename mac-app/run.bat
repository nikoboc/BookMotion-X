@echo off
REM Double-click launcher for Windows. First run sets up a local venv + deps.
cd /d "%~dp0"

if not exist ".venv" (
  echo 初回セットアップ: 仮想環境と依存関係を準備します...
  python -m venv .venv || (echo python が見つかりません。python.org からインストールしてください。& pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
)

".venv\Scripts\python.exe" kindle_notion.py %*
echo.
pause
