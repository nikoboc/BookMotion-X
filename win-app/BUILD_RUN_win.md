# Windows ビルド・実行手順

Kindle ハイライト → Notion 同期アプリを Windows 上でビルドして使う手順。
コアは [`../app/`](../app/) にある **Mac 版とまったく同じコード**で、そのまま Windows でも動きます。
このフォルダ（`win-app\`）の `build_win.bat` / `run.bat` はダブルクリックでOK（`..\app` のコアを参照し、venv と `dist\` はここに作られます）。

---

## 事前準備（1回だけ）

| 必要なもの | 確認・入手 |
|---|---|
| **Python 3** | ビルドに必要。`py -3 --version` で確認。無ければ [python.org](https://www.python.org/downloads/windows/) からインストール（インストーラで **「Add python.exe to PATH」と py ランチャにチェック**、Tcl/Tk も既定で同梱）。スクリプトは `py -3`（＝インストール済みで最新の Python 3）を使うので、複数バージョンが入っていても自動で新しい方が選ばれます。**Python 3.10.0 ちょうどは PyInstaller が既知バグ（`dis` の IndexError）で失敗**しますが、3.11 / 3.12 などが入っていれば `py -3` がそちらを使います（このリポジトリは 3.12.10 でビルド確認済み） |
| **Amazon アカウント** | GUI は起動後に「**Kindle にログイン**」ボタンからアプリ内ブラウザ（WebView2）でサインインするだけ。事前の `cookies.txt` は不要（**下記デバッグ用の CLI を使うときだけ** `read.amazon.co.jp` の `cookies.txt` を「Get cookies.txt LOCALLY」等で書き出す） |
| **Notion トークン** | [notion.so/my-integrations](https://www.notion.so/my-integrations) で内部インテグレーションを作成 → トークンをコピー |
| **Notion 親ページ** | DB を置く親ページを開き「•••」→「連携」→ 作成したインテグレーションを追加（**忘れると 404**） |

> トークン・親ページ URL は**アプリ画面で入力**します（下記ステップ3）。事前にファイルへ書く必要はありません。

---

## 使い方（ビルド → 起動 → 設定 → 実行）

### 1. ビルド

PyInstaller は**クロスコンパイル不可**なので、必ず **Windows 上で**ビルドします。
エクスプローラーで `win-app\` の **`build_win.bat` をダブルクリック**（または `win-app\` 内で以下）:

```bat
build_win.bat
```

- `..\app\requirements.txt` + `pyinstaller` を導入し、`..\app\gui.py` を単一 exe にバンドル（数分）
- 成功すると **`win-app\dist\Booklight.exe`** が生成される（`--onefile` なので 1 ファイルで配布可）

### 2. 起動

`win-app\dist\Booklight.exe` を **ダブルクリック**。

> 未署名のため、初回は SmartScreen が警告することがあります。**「詳細情報」→「実行」** で許可すれば、以降は普通に開けます。

### 3. トークン等を設定

起動したウィンドウに入力します。

1. **Notion トークン**
2. **親ページ URL**
3. **Kindle** … 「**Kindle にログイン**」を押すとアプリ内ブラウザ（WebView2）が開くので、いつも通りサインイン（2FA も可）。Cookie は自動保存され、以後は自動更新される
4. **「保存」** を押す（`DB ID` は空でOK。初回に自動作成して欄へ書き戻されます）

> 設定は `%USERPROFILE%\.booklight\config.json` に自動保存され、次回起動時に復元されます。手でファイルを触る必要はありません。（旧バージョンの `.kindle-notion` フォルダにある設定は初回起動時に自動でコピー移行されます）

### 4. 実行

- **「Notion へ同期」** を押す（進捗はウィンドウ下部のログに表示）
- 先頭1冊だけで動作確認したいときは CLI の `--limit 1` を使う（下記「デバッグ用」参照）

---

## ログイン / Cookie について

**GUI はアプリ内ブラウザでログイン**します。ウィンドウの「**Kindle にログイン**」を押すと
WebView2（Windows 10/11 に標準搭載の Edge ランタイム）で `read.amazon.co.jp` のサインイン画面が開くので、
いつも通りログインしてください（2FA・CAPTCHA も本物のブラウザなので通ります）。
取得した Cookie はアプリのデータ（`%USERPROFILE%\.booklight\cookies.txt`）に保存され、
同期のたびに自動更新されるので、**普段は再ログイン不要**です。`cookies.txt` を手で用意する必要はありません。

> **CLI（下記デバッグ用）だけ**は画面が無いため、従来どおり書き出した `cookies.txt` を `-c` で渡します。
> 「**Get cookies.txt LOCALLY**」等の拡張機能で `read.amazon.co.jp` の `cookies.txt` を書き出してください。

---

## デバッグ用（コア機能をターミナルで実行）

exe を介さず、同期ロジック [../app/kindle_notion.py](../app/kindle_notion.py) を直接動かす方法。
GUI を出さず素早く回すには `win-app\` の **`run.bat`** をダブルクリック（初回に venv + 依存を自動セットアップ）。
引数を細かく渡したいときは以下（`win-app\` 内で実行）:

**初回セットアップ**（仮想環境 + 依存。`run.bat` を一度動かせば自動で作られます）:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r ..\app\requirements.txt
```

**設定** … CLI は画面が無いので `config.json` を読みます（`..\app\config.example.json` が見本）。
置き場所は `..\app\config.json`（`.gitignore` 済み）:

```json
{
  "notion_token": "ntn_xxx",
  "notion_parent_page_id": "https://www.notion.so/親ページ...",
  "notion_database_id": ""
}
```

探索順は `app\config.json` → 無ければ `%USERPROFILE%\.booklight\config.json`（旧 `.kindle-notion` も後方互換で読む）。

**実行**:

```powershell
.\.venv\Scripts\python.exe ..\app\kindle_notion.py -c cookies.txt             # 実行（cookies.txt は必須）
.\.venv\Scripts\python.exe ..\app\kindle_notion.py -c cookies.txt --limit 1   # 先頭1冊でテスト
```

| 引数 | 意味 |
|---|---|
| `-c, --cookies-file` | エクスポート済み `cookies.txt`（**必須**） |
| `--limit N` | 先頭 N 冊だけ処理（テスト用） |

---

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `Python 3 が見つかりません` | [python.org](https://www.python.org/downloads/windows/) からインストール（「Add python.exe to PATH」＋ py ランチャにチェック） |
| ビルドが `IndexError: tuple index out of range` で失敗 | Python 3.10.0 の既知バグ。3.11 / 3.12 を入れれば `py -3` が自動でそちらを使う |
| exe が起動しない / すぐ閉じる | まず `run.bat` で CLI 実行してエラー内容を確認（GUI 版はログがウィンドウ内） |
| SmartScreen で開けない | 「詳細情報」→「実行」（初回のみ） |
| 「Kindle にログイン」で画面が出ない | WebView2 ランタイムが必要。Windows 10/11 は標準搭載だが、無い場合は [Microsoft の Evergreen ランタイム](https://developer.microsoft.com/microsoft-edge/webview2/)を入れる |
| 「ログインしていません」 | Cookie が古い可能性。**GUI は「Kindle にログイン」で再サインイン**。**CLI は** `cookies.txt` を書き出し直して `-c` で渡す |
| CLI 用 `cookies.txt` の書き出し方 | 「Get cookies.txt LOCALLY」等の拡張機能で `read.amazon.co.jp` の Cookie を書き出す（GUI では不要） |
| 本が少ない | ログインが切れている可能性。ログインし直して再実行 |
