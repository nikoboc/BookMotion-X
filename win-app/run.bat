@echo off
REM Double-click launcher for Windows (CLI). First run sets up a local venv + deps.
REM Shared code lives in ..\app ; the venv is created here in win-app\.
chcp 65001 >nul
cd /d "%~dp0"
set "APP=..\app"

if not exist ".venv" (
  echo 初回セットアップ: 仮想環境と依存関係を準備します...
  REM `py -3` picks the newest installed Python 3 (avoids a stale `python`=3.10 on PATH).
  py -3 -m venv .venv || (echo Python 3 が見つかりません。python.org からインストールし、py ランチャを有効にしてください。& pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r "%APP%\requirements.txt"
)

".venv\Scripts\python.exe" "%APP%\kindle_notion.py" %*
echo.
pause
