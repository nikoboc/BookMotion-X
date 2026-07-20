# Kindle → Notion

Kindle のハイライト（`read.amazon.co.jp/notebook`）を取得し、**Notion データベースへ登録**するツール群。
ログイン済みのセッション（ブラウザの Cookie）を流用するので、Cookie の抜き取りや管理者権限は不要です。

同じ目的に対して、**使い方の異なる 2 つの実装**を用意しています。用途に合う方を選んでください。

| 実装 | 動作環境 | 使い方 | 特徴 |
|---|---|---|---|
| [`extension/`](extension/) | Chrome / Edge の拡張機能（MV3） | ブラウザのポップアップから操作 | ログイン中のブラウザセッションをそのまま利用。導入が手軽 |
| [`app/`](app/) ＋ [`mac-app/`](mac-app/)・[`win-app/`](win-app/) | macOS / Windows の Python アプリ | クリック実行（GUI）または CLI | ブラウザ自動操作なしの単なるプロセス。別アプリに切り替えても止まらない。`.app` / `.exe` 化も可能 |

どちらも登録先の Notion DB スキーマ（列構成・重複防止ロジック）は共通です。

## フォルダ構成

```
04_Kindle/
├── README.md              ← このファイル
├── .gitignore             トークン・Cookie・ビルド成果物を除外
├── .gitattributes         改行コード固定（.command=LF / .bat=CRLF）
│
├── extension/             【実装A】Chrome/Edge 拡張機能（Manifest V3）
│   ├── README.md          拡張の詳しい導入・仕組み・トラブルシュート
│   ├── manifest.json      権限・エントリ定義（offscreen/downloads/storage/scripting/tabs）
│   ├── background.js      service worker。本一覧の収集とハイライト取得の司令塔
│   ├── offscreen.js       DOMParser で HTML を構造化（SW に DOMParser が無いため委譲）
│   ├── offscreen.html      └ offscreen document のホスト
│   ├── popup.js           ポップアップの操作・進捗表示（同期 / JSON 出力）
│   ├── popup.html          └ ポップアップ UI
│   ├── options.js         Notion トークン・親ページ設定、DB 作成処理
│   └── options.html        └ 設定画面 UI
│
├── app/                   【実装B・共通コア】Mac/Win 同一の Python コード
│   ├── README.md          セットアップと実行方法（GUI / CLI）
│   ├── kindle_notion.py   コア。Kindle 取得＋整形＋Notion 登録（CLI エントリでもある）
│   ├── gui.py             Tkinter GUI（.app / .exe のエントリポイント）
│   ├── requirements.txt   依存（requests / beautifulsoup4 / browser_cookie3）
│   └── config.example.json 設定ファイルの見本（実体 config.json は .gitignore 済み）
│
├── mac-app/               【実装B・Mac 固有】起動とパッケージング（../app を参照）
│   ├── BUILD_RUN_mac.md   macOS でのビルド→起動→設定→実行の詳細手順
│   ├── run.command        ダブルクリック起動（初回に venv+依存を自動構築）
│   └── build_mac.command  PyInstaller で KindleNotion.app をビルド（要 Mac）
│
└── win-app/               【実装B・Windows 固有】起動とパッケージング（..\app を参照）
    ├── BUILD_RUN_win.md   Windows でのビルド→起動→設定→実行の詳細手順
    ├── run.bat            ダブルクリック起動（初回に venv+依存を自動構築）
    └── build_win.bat      PyInstaller で KindleNotion.exe をビルド（要 Windows）
```

## 仕組み（共通の流れ）

1. **本一覧の取得** — notebook の左サイドバーは全冊が一度に載っていない。
   - `extension/`: バックグラウンドタブで notebook を開き、injected content script でサイドバーを自動スクロールして全冊をロードしてから回収。
   - `app/`（Python アプリ）: `/notebook?library=list`（+ `token`）をサーバー側ページネーションで辿って全冊取得（ブラウザ不要）。
2. **各書籍のハイライト取得** — `/notebook?asin=...` が返すサーバー描画 HTML を取得・パース（色・位置も抽出）。
3. **Notion へ登録** — 下記スキーマの DB に、注釈 ID で重複を避けながら追加。

### Notion データベースの列（左→右）

| 列 | Notion 型 | 備考 |
|---|---|---|
| ハイライト文 | title | ハイライト本文。2000 字超は自動分割 |
| 書籍名 | rich_text | |
| 著者名 | rich_text | 先頭の「著者:」は除去 |
| 位置 | number | |
| マーカー色 | select | 黄色 / 青 / ピンク / オレンジ |
| 実行日 | date | 同期実行日 |
| 注釈ID | rich_text | 重複判定用のキー（末尾列） |

- **列の並び順**: 上表が設計上の順。ただし Notion API は DB 作成時に列順を指定できないため、**新規作成後に一度だけ Notion 上で手動整列**が必要（DB は使い回すので初回だけ）。
- **重複防止（Notion が真実）**: 各行に注釈 ID を保存。同期開始時に Notion をクエリして既存 ID を取得し、無いものだけ登録。別 PC・手動削除・再インストールにも強い。

## クイックスタート

### 実装A：拡張機能（Chrome / Edge）
1. `read.amazon.co.jp` にログインしておく。
2. `chrome://extensions`（Edge は `edge://extensions`）→ デベロッパーモード ON →「パッケージ化されていない拡張機能を読み込む」で `extension/` を選択。
3. ポップアップから「⚙ Notion 設定」でトークン・親ページを設定 → DB 作成 → 「Kindle → Notion 同期」。

詳細は [extension/README.md](extension/README.md)。

### 実装B：Python アプリ（Mac / Windows）
1. `read.amazon.co.jp` にログインしておく。
2. `mac-app/run.command`（Mac）/ `win-app/run.bat`（Windows）をダブルクリック、または `app/gui.py` を起動。
3. トークン・親ページを入力 → 「Notion へ同期」。

詳細は [app/README.md](app/README.md)、ビルド手順は [mac-app/BUILD_RUN_mac.md](mac-app/BUILD_RUN_mac.md) / [win-app/BUILD_RUN_win.md](win-app/BUILD_RUN_win.md)。

## 必要なもの（共通）

- 対象ブラウザで **`read.amazon.co.jp` にログイン済み**であること。
- **Notion のインテグレーショントークン**（[notion.so/my-integrations](https://www.notion.so/my-integrations) で作成）。
- DB を置く **親ページ**に、そのインテグレーションを「連携」から追加しておくこと（忘れると 404）。

## 秘密情報の扱い

- トークンや Cookie は**ローカルのみ**に保存され、外部送信は Amazon と Notion に限られます。
- `config.json` / `cookies.txt` / `.env` / ビルド成果物（`dist/`・`build/`）は `.gitignore` 済みでコミットされません。設定の見本は [app/config.example.json](app/config.example.json) を参照。
