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

初回実行すると `~/.kindle-notion/config.json` が作られます。以下を記入：

```json
{
  "notion_token": "ntn_xxx",
  "notion_parent_page_id": "https://www.notion.so/親ページ...",
  "notion_database_id": ""
}
```
`notion_database_id` は空でOK（初回に自動作成して書き戻します）。

### 3. 実行

**Finder で `run.command` をダブルクリック**。初回だけ venv と依存を自動セットアップ→実行します。

- 未署名のためGatekeeperが警告したら、`run.command` を**右クリック→「開く」**（初回のみ）
- 実行権限が要る場合はターミナルで `chmod +x run.command`

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
| 引用文 | title | 2000字超は自動分割 |
| 本のタイトル | rich_text | |
| 本の著者 | rich_text | 先頭「著者:」は除去 |
| ハイライト位置 | number | |
| ハイライト色 | select | 黄色 / 青 / ピンク / オレンジ |
| 実行日 | date | 実行日 |
| 注釈ID | rich_text | 重複判定キー（末尾列） |

- **並び順**: 本のタイトル昇順 → ハイライト位置昇順で挿入
- **重複防止（Notion が真実）**: 各行に注釈IDを保存し、実行時に Notion をクエリして既存分をスキップ。何度実行しても新規だけ追加
- **Cookie/トークンの扱い**: `config.json`（平文・ローカルのみ）と OS の Cookie を使用。外部送信は Amazon と Notion のみ

## うまくいかない時

- **「ログインしていません」** → ブラウザで `read.amazon.co.jp` にログインして再実行、または `-c cookies.txt`
- **Cookie が読めない**（`browser_cookie3` が失敗）→ 「Get cookies.txt LOCALLY」等で `cookies.txt` を書き出し `-c` で指定
- **本が少ない** → ログインが切れている可能性。ログインし直して再実行
- **色が空/ズレ** → `extract_color()` のセレクタ調整が必要。実HTMLを共有してください
