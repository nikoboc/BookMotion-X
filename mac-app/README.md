# Kindle → Notion（Mac クリック実行・ブラウザ不要）

Kindle のハイライト（`read.amazon.co.jp/notebook`）を取得して Notion データベースへ登録する、**ブラウザ自動操作なし**の Python アプリ。

- 本一覧は `/notebook?library=list`（+ `token`）を辿って**全冊**取得
- 各本のハイライトは `/notebook?asin=...`
- ログインは**ブラウザの Cookie を流用**（`browser_cookie3`）、または手動 `cookies.txt`
- 拡張機能と違い**ただのプロセス**なので、別アプリに切り替えても**止まらない**

## 必要なもの

- macOS に **Python 3**（`python3 --version`。無ければ `xcode-select --install` か Homebrew）
- その Mac のブラウザで **`read.amazon.co.jp` にログイン済み**であること
- Notion のインテグレーショントークンと、DB を置く親ページ

## セットアップ

### 1. Notion 側

1. [notion.so/my-integrations](https://www.notion.so/my-integrations) で内部インテグレーションを作成 → **トークン**をコピー
2. DB を置きたい**親ページ**を開き、右上「•••」→「連携」→ そのインテグレーションを追加（忘れると 404）

### 2. 設定ファイル

`config.json` に記入します。**置き場所は `mac-app/config.json`（このスクリプトの隣）**。
初回実行時に無ければ自動生成されます。

```json
{
  "notion_token": "ntn_xxx",
  "notion_parent_page_id": "https://www.notion.so/親ページ...",
  "notion_database_id": ""
}
```
- `notion_database_id` は空でOK（初回に自動作成して書き戻します）
- 探索順は **`mac-app/config.json` → 無ければ `~/.kindle-notion/config.json`**
- `config.json` は `.gitignore` 済み（トークンはコミットされません。`config.example.json` は見本）

### 3. 実行（3つの方法）

**方法1: GUIアプリ（おすすめ）**
- `python3 gui.py`（またはビルドした `KindleNotion.app`）を起動
- 窓に **トークン / 親ページURL / cookies.txt** を入力 → 「保存」→「Notion へ同期」
- ファイル編集不要。ログも窓に表示

**方法2: `run.command`（CLI・ダブルクリック）**
- Finder で `run.command` をダブルクリック。初回だけ venv と依存を自動セットアップ→実行
- 設定は `config.json` を編集（下記）

**方法3: ターミナル**
- 初回のみ venv と依存をセットアップ:
  ```bash
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip
  ./.venv/bin/pip install -r requirements.txt
  ```
- 実行: `./.venv/bin/python kindle_notion.py -c cookies.txt`（`--limit 1` でテスト）

- 未署名のためGatekeeperが警告したら、**右クリック→「開く」**（初回のみ）
- 実行権限が要る場合は `chmod +x run.command`

### 単体 .app にする（Python不要のスタンドアロン）

Mac 上で **`build_mac.command` をダブルクリック**（PyInstaller はクロスコンパイル不可なので必ずMacで）。
`dist/KindleNotion.app` が生成されます。初回起動は右クリック→「開く」。

> パッケージ版（.app）の設定は `~/Library/Application Support/KindleNotion/config.json` に保存されます（バンドル内は書込不可のため）。GUIの入力欄から設定すればこのファイルは意識不要です。
>
> Homebrew の Python を使う場合、GUI に必要な Tk が別途要ることがあります: `brew install python-tk`

## コマンド（ターミナルから使う場合）

```bash
./.venv/bin/python kindle_notion.py            # 通常実行
./.venv/bin/python kindle_notion.py --limit 1  # 先頭1冊だけ（テスト）
./.venv/bin/python kindle_notion.py -b safari  # Cookie取得元ブラウザを指定
./.venv/bin/python kindle_notion.py -c cookies.txt  # 手動エクスポートCookieを使う
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
- **Cookie/トークンの扱い**: `config.json`（平文・ローカルのみ）と OS の Cookie を使用。外部送信は Amazon と Notion のみ

## うまくいかない時

- **「ログインしていません」** → ブラウザで `read.amazon.co.jp` にログインして再実行、または `-c cookies.txt`
- **Cookie が読めない**（`browser_cookie3` が失敗）→ 「Get cookies.txt LOCALLY」等で `cookies.txt` を書き出し `-c` で指定
- **本が少ない** → ログインが切れている可能性。ログインし直して再実行
- **色が空/ズレ** → `extract_color()` のセレクタ調整が必要。実HTMLを共有してください
