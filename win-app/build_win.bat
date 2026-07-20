@echo off
REM Build KindleNotion.exe on Windows. Double-click this file.
REM PyInstaller cannot cross-compile, so the .exe must be built on Windows.
REM Shared code lives in ..\app ; venv + dist are created here in win-app\.
chcp 65001 >nul
cd /d "%~dp0"
set "APP=..\app"

REM `py -3` picks the newest installed Python 3 (avoids a stale `python`=3.10 on PATH).
echo == ビルド環境を準備 ==
py -3 -m venv .buildvenv || (echo Python 3 が見つかりません。python.org からインストールし、py ランチャを有効にしてください。& pause & exit /b 1)
".buildvenv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".buildvenv\Scripts\python.exe" -m pip install --quiet -r "%APP%\requirements.txt" pyinstaller

echo == exe をビルド中 (数分かかります) ==
".buildvenv\Scripts\pyinstaller.exe" --noconfirm --windowed --onefile --name "KindleNotion" ^
  --paths "%APP%" ^
  --add-data "%APP%\fonts;fonts" ^
  --collect-all certifi ^
  --collect-all customtkinter ^
  --collect-all darkdetect ^
  "%APP%\gui.py"

echo.
if exist "dist\KindleNotion.exe" (
  echo 完成: %cd%\dist\KindleNotion.exe
  echo ダブルクリックで起動できます（初回は SmartScreen の警告が出たら「詳細情報」→「実行」）。
) else (
  echo ビルドに失敗しました。上のログを確認してください。
)
echo このウィンドウは閉じてOKです。
pause
