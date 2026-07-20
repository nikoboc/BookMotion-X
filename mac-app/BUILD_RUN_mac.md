# macOS ビルド・実行手順

Kindle ハイライト → Notion 同期アプリ（`mac-app/`）を Mac 上でビルドして使う手順。
コマンドはすべて `mac-app/` フォルダの中で実行します。

```bash
cd mac-app
```

---

## 事前準備（1回だけ）

| 必要なもの | 確認・入手 |
|---|---|
| **Python 3** | ビルドに必要。`python3 --version` で確認。無ければ `xcode-select --install`（または `brew install python`） |
| **Tk**（Homebrew の Python のみ） | GUI ビルドに必要なことがある: `brew install python-tk` |
| **Kindle ログイン** | その Mac のブラウザで `read.amazon.co.jp` にログイン済みであること（または `cookies.txt` を用意） |
| **Notion トークン** | [notion.so/my-integrations](https://www.notion.so/my-integrations) で内部インテグレーションを作成 → トークンをコピー |
| **Notion 親ページ** | DB を置く親ページを開き「•••」→「連携」→ 作成したインテグレーションを追加（**忘れると 404**） |

> トークン・親ページ URL は**アプリ画面で入力**します（下記ステップ3）。事前にファイルへ書く必要はありません。

---

## 使い方（ビルド → 起動 → 設定 → 実行）

### 1. ビルド

PyInstaller は**クロスコンパイル不可**なので、必ず **Mac 上で**ビルドします。
Finder で **`build_mac.command` をダブルクリック**（または以下）:

```bash
./build_mac.command
```

- `requirements.txt` + `pyinstaller` を導入し、`gui.py` をバンドル（数分）
- 成功すると **`dist/KindleNotion.app`** が生成される

### 2. 起動

`dist/KindleNotion.app` を **右クリック →「開く」**。

> 未署名のため Gatekeeper が警告します。**初回だけ「右クリック→開く」** で許可すれば、以降は普通にダブルクリックで開けます。

### 3. トークン等を設定

起動したウィンドウに入力します。

1. **Notion トークン**
2. **親ページ URL**
3. **Cookie 取得元** … `cookies.txt`（「選択…」で指定）／ **ブラウザから自動**（ブラウザ名を選択）
4. **「保存」** を押す（`DB ID` は空でOK。初回に自動作成して欄へ書き戻されます）

> 設定は `~/Library/Application Support/KindleNotion/config.json` に自動保存され、次回起動時に復元されます。手でファイルを触る必要はありません。

### 4. 実行

- **「Notion へ同期」** を押す（進捗はウィンドウ下部のログに表示）
- 最初に動作確認したいときは **「テスト（先頭1冊だけ）」** にチェックしてから同期

---

## デバッグ用（コア機能をターミナルで実行）

`.app` を介さず、同期ロジック [kindle_notion.py](kindle_notion.py) を直接動かす方法。引数でテスト・Cookie 元を細かく指定できます。

**初回セットアップ**（仮想環境 + 依存）:

```bash
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
```

**設定** … CLI は画面が無いので `config.json` を読みます（`config.example.json` が見本）:

```json
{
  "notion_token": "ntn_xxx",
  "notion_parent_page_id": "https://www.notion.so/親ページ...",
  "notion_database_id": ""
}
```

探索順は `mac-app/config.json` → 無ければ `~/.kindle-notion/config.json`。`.gitignore` 済み。

**実行**:

```bash
./.venv/bin/python kindle_notion.py -c cookies.txt --limit 1   # 先頭1冊でテスト
./.venv/bin/python kindle_notion.py -b safari                  # Safari の Cookie を使う
./.venv/bin/python kindle_notion.py -c cookies.txt             # 通常実行
```

| 引数 | 意味 |
|---|---|
| `-c, --cookies-file` | エクスポート済み `cookies.txt` を使う |
| `-b, --browser` | Cookie 取得元ブラウザ: `chrome` / `safari` / `edge` / `brave` / `firefox` |
| `--limit N` | 先頭 N 冊だけ処理（テスト用） |

---

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `python3 が見つかりません` | `xcode-select --install` か `brew install python` |
| ビルドで Tk エラー | `brew install python-tk` |
| `.app` が開けない（Gatekeeper） | 右クリック →「開く」（初回のみ） |
| 「ログインしていません」 | ブラウザで `read.amazon.co.jp` に再ログイン、または `cookies.txt` を指定 |
| Cookie が読めない（`browser_cookie3` 失敗） | 「Get cookies.txt LOCALLY」等で `cookies.txt` を書き出して使う |
| 本が少ない | ログインが切れている可能性。ログインし直して再実行 |
