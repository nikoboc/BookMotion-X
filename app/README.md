# Booklight（Kindle → Notion・共通コア）

Kindle のハイライト（`read.amazon.co.jp/notebook`）を取得して Notion データベースへ登録する Python アプリ **Booklight** の共通コア。このフォルダ（`app/`）が **Mac / Windows 共通**で、OS 固有のビルド／起動スクリプトは [`../mac-app/`](../mac-app/) と [`../win-app/`](../win-app/) にあります。

- 本一覧は `/notebook?library=list`（+ `token`）を辿って**全冊**取得
- 各本のハイライトは `/notebook?asin=...`
- ログインは、**GUI はアプリ内ブラウザ**（Mac: WKWebView / Win: WebView2、`kindle_login.py`）でサインインして Cookie を自動取得・自動更新。**CLI はエクスポートした `cookies.txt`** を使用
- 同期本体は拡張機能と違い**ただのプロセス**（ブラウザ自動操作なし）なので、別アプリに切り替えても**止まらない**

## フォルダの役割

```
app/        ← このフォルダ。共通コア（Mac/Win 同一コード）
  kindle_notion.py     コア。Kindle 取得＋整形＋Notion 登録（CLI エントリでもある）
  gui.py               Booklight GUI（.app / .exe のエントリポイント）
  kindle_login.py      アプリ内ブラウザで Kindle にログインし Cookie を取得
  requirements.txt     依存（requests / beautifulsoup4 / customtkinter / pywebview）
  config.example.json  設定の見本（実体 config.json は .gitignore 済み）
../mac-app/  Mac 固有: run.command / build_mac.command / BUILD_RUN_mac.md
../win-app/  Win 固有: run.bat / build_win.bat / BUILD_RUN_win.md
```

## 必要なもの

- **Python 3**（Mac: `python3 --version` ／ Windows: `py -3 --version`）
- **Amazon（`read.amazon.co.jp`）のアカウント** … GUI は「Kindle にログイン」ボタンからアプリ内ブラウザでサインインするだけ。**CLI で使う場合のみ**、ログイン済みブラウザから書き出した **`cookies.txt`**（「Get cookies.txt LOCALLY」等の拡張機能）が必要
- Notion のインテグレーショントークンと、DB を置く親ページ

## セットアップ

### 1. Notion 側

1. [notion.so/my-integrations](https://www.notion.so/my-integrations) で内部インテグレーションを作成 → **トークン**をコピー
2. DB を置きたい**親ページ**を開き、右上「•••」→「連携」→ そのインテグレーションを追加（忘れると 404）

### 2. 設定ファイル（GUI を使うなら不要）

GUI（`.app` / `.exe` / `gui.py`）は画面でトークン等を入力するため、手でファイルを触る必要はありません。
CLI で使う場合のみ `config.json` を用意します。**置き場所は `app/config.json`（`kindle_notion.py` の隣）**。無ければ初回に自動生成されます。

```json
{
  "notion_token": "ntn_xxx",
  "notion_parent_page_id": "https://www.notion.so/親ページ...",
  "notion_database_id": ""
}
```
- `notion_database_id` は空でOK（初回に自動作成して書き戻します）
- 探索順は **`app/config.json` → 無ければ `~/.booklight/config.json`**（旧 `~/.kindle-notion` も後方互換で読む）
- `config.json` は `.gitignore` 済み（トークンはコミットされません。`config.example.json` は見本）

## 実行（3つの方法）

**方法1: GUIアプリ（おすすめ）**
- ビルド済みの **`Booklight.app`（Mac）/ `Booklight.exe`（Win）** を起動、または `app/` で `python3 gui.py` / `py -3 gui.py`
- 窓に **トークン / 親ページURL** を入力し、**「Kindle にログイン」**でアプリ内ブラウザからサインイン → 「保存」→「Notion へ同期」。ログも窓に表示（Cookie は以後自動更新）

**方法2: ダブルクリック CLI**
- Mac: [`../mac-app/run.command`](../mac-app/run.command) ／ Windows: [`../win-app/run.bat`](../win-app/run.bat) をダブルクリック
- 初回だけ venv と依存を自動セットアップ→実行（venv は各 OS フォルダ内に作られます）。設定は `app/config.json`

**方法3: ターミナル**
- 初回のみ venv と依存をセットアップ（`app/` 内で）:
  ```bash
  # macOS
  python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
  ./.venv/bin/python kindle_notion.py -c cookies.txt      # --limit 1 でテスト
  ```
  ```powershell
  # Windows
  py -3 -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt
  .\.venv\Scripts\python.exe kindle_notion.py -c cookies.txt   # --limit 1 でテスト
  ```

## 単体アプリにする（Python不要のスタンドアロン）

PyInstaller は**クロスコンパイル不可**なので、必ず**そのOS上で**ビルドします。

- **Mac**: [`../mac-app/build_mac.command`](../mac-app/build_mac.command) をダブルクリック → `mac-app/dist/Booklight.app`
- **Windows**: [`../win-app/build_win.bat`](../win-app/build_win.bat) をダブルクリック → `win-app/dist/Booklight.exe`

詳しい手順は [BUILD_RUN_mac.md](../mac-app/BUILD_RUN_mac.md) / [BUILD_RUN_win.md](../win-app/BUILD_RUN_win.md)。

> パッケージ版の設定は Mac: `~/Library/Application Support/Booklight/config.json`、Windows: `%USERPROFILE%\.booklight\config.json` に保存されます（バンドル内は書込不可のため）。旧バージョン（`KindleNotion` / `.kindle-notion`）の設定は初回起動時に自動でコピー移行されます。GUIの入力欄から設定すればこのファイルは意識不要です。

## コマンド（ターミナルから使う場合）

```bash
python kindle_notion.py -c cookies.txt            # 実行（cookies.txt は必須）
python kindle_notion.py -c cookies.txt --limit 1  # 先頭1冊だけ（テスト）
```

## テスト

`tests/` に `pytest` のユニットテストがあります（ネットワーク不要のコア関数のみ対象：
パーサ・i18n・設定パス/移行・Notion 整形）。`app/` 内で実行:

```bash
python -m venv .venv
./.venv/bin/pip install -r requirements-dev.txt     # Win: .\.venv\Scripts\pip install ...
./.venv/bin/pytest                                  # Win: .\.venv\Scripts\pytest
```

## データベースの列（左→右）

| 列 | 型 | 備考 |
|---|---|---|
| ハイライト文 | title | 2000字超は自動分割 |
| 書籍名 | rich_text | |
| 著者名 | rich_text | 先頭「著者:」は除去 |
| 位置 | number | |
| マーカー色 | select | 黄色 / 青 / ピンク / オレンジ |
| 実行日 | date | 実行日 |
| 注釈ID | rich_text | 重複判定キー（末尾列） |

- **列の並び順**: 上表が設計上の左→右の順。ただし **Notion API はデータベース作成時に列順を無視する**（作成順でも1列ずつ追加しても、UI 上の列順は Notion 内部の順で決まる／API に列順を指定する手段が無い）ため、**新規作成後に一度だけ Notion 上で手動整列**が必要。DB は一度作れば使い回すので、これは初回だけの作業
- **行の並び順**: 書籍名昇順 → 位置昇順で挿入
- **重複防止（Notion が真実）**: 各行に注釈IDを保存し、実行時に Notion をクエリして既存分をスキップ。何度実行しても新規だけ追加
- **Cookie/トークンの扱い**: `config.json`（平文・ローカルのみ）と Cookie を使用。GUI は「Kindle にログイン」で取得した Cookie を、CLI は取り込んだ `cookies.txt` を、いずれもアプリのデータフォルダ内に保存。外部送信は Amazon と Notion のみ

## うまくいかない時

- **「ログインしていません」** → Cookie が古い可能性。**GUI は「Kindle にログイン」で再サインイン**。**CLI は** `read.amazon.co.jp` にログインし直して `cookies.txt` を取り直し `-c` で渡す
- **CLI 用 `cookies.txt` の書き出し方** → 「Get cookies.txt LOCALLY」等の拡張機能で `read.amazon.co.jp` の Cookie を書き出す（GUI では不要）
- **本が少ない** → ログインが切れている可能性。ログインし直して再実行
- **色が空/ズレ** → `extract_color()` のセレクタ調整が必要。実HTMLを共有してください
