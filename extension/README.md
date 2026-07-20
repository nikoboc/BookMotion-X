# Kindle → Notion 拡張機能（自作）

Kindle のハイライト（`read.amazon.co.jp/notebook`）を、ブラウザ拡張が**自分でアクセス**して取得する自作ツール。

- ログイン済みセッションを使うので、Cookie 抜き取りも管理者権限も不要
- **本一覧の取得**: notebook の左サイドバーはスクロールで遅延ロードされる（素の fetch だと最初の ~14 冊しか取れない）。そこで拡張が **notebook をバックグラウンドタブで開き、injected content script でサイドバーを自動スクロール**して全冊をロード → 書籍リストを回収 → タブを閉じる
- **各書籍のハイライト取得**: `?asin=` エンドポイントはサーバー描画 HTML を返すため、こちらは **ヘッドレス fetch** で取得
- MV3 の service worker には DOMParser が無いため、ハイライト HTML のパースは offscreen document に委譲

## フェーズ

- **フェーズ1**: 取得 → 整形 → `kindle_highlights.json` を自動ダウンロード
- **フェーズ2（実装済み）**: 取得したデータを Notion API で DB に直接登録

## Notion 連携（フェーズ2）

### 準備（初回のみ）

1. [notion.so/my-integrations](https://www.notion.so/my-integrations) で内部インテグレーションを作成し、**Internal Integration Token** をコピー
2. DB を置きたい**親ページ**を Notion で開き、右上「•••」→「連携」から作成したインテグレーションを追加（← これを忘れると 404）
3. 拡張のポップアップ →「⚙ Notion 設定」を開き、**トークン**と**親ページ ID（URL 可）**を入力して保存
4. 「Notion データベースを作成」をクリック → 指定の 6 列で DB が作られ、DB ID が保存される

### 同期

ポップアップの **「Kindle → Notion 同期」** をクリック。全書籍を取得 → 整形 → Notion に登録します。

### データベースの列（左→右）

| 列 | Notion 型 | 備考 |
|---|---|---|
| ハイライト文 | title | ハイライト本文。2000 字超は自動分割 |
| 書籍名 | rich_text | |
| 著者名 | rich_text | 先頭の「著者:」は除去 |
| 位置 | number | |
| マーカー色 | select | 黄色 / 青 / ピンク / オレンジ |
| 実行日 | date | 同期実行日 |
| 注釈ID | rich_text | 重複判定用のキー（末尾列） |

- **列の並び順**: 上表が設計上の左→右の順。ただし **Notion API はデータベース作成時に列順を無視する**（作成順でも1列ずつ追加しても、UI 上の列順は Notion 内部の順で決まる／API に列順を指定する手段が無い）ため、**新規作成後に一度だけ Notion 上で手動整列**が必要。DB は一度作れば使い回すので、これは初回だけの作業
- **行の並び順**: 書籍名昇順 → 位置昇順で挿入（Notion 側ビューにも同じソートを付けると確実）
- **重複防止（Notion が真実）**: 各行に注釈 ID（Amazon の注釈 id、無ければ `書籍名|位置|ハイライト先頭40字` の合成キー）を保存。同期開始時に **Notion をクエリして既存の注釈 ID を取得**し、無いものだけ登録する。別 PC・手動削除・拡張再インストールにも強い
- **パイプライン実行**: 書籍名順に「取得 → 即登録」を流し、次の本を先読み取得（6 冊先まで）しながら登録するので、取得時間が登録の裏に隠れる
- **メモのみの注釈**（ハイライト無し）はスキップ（このスキーマにハイライト文列しか無いため）
- **レート**: Notion の平均 3 req/s に合わせて登録。件数が多いと数分かかることあり

> ⚠️ この更新より前に作った DB / 登録済み行には `注釈ID` が入っていません。拡張が列は自動追加しますが、**旧行は ID 空欄なので次回同期で重複登録**され得ます。最初のフル同期前に、テストで入れた行（または DB）を一度クリアするのが安全です。

## 読み込み方法（Chrome / Edge 共通）

1. `read.amazon.co.jp` にブラウザでログインしておく（1回でOK）
2. `chrome://extensions`（Edge は `edge://extensions`）を開く
3. 右上の **「デベロッパーモード」** を ON
4. **「パッケージ化されていない拡張機能を読み込む」** → この `extension/` フォルダを選択
5. ツールバーの拡張アイコン → ポップアップの **「notebook から取得」** をクリック
6. 完了すると `kindle_highlights.json` がダウンロードされる

コードを直したら、拡張一覧の **「更新（↻）」** で再読み込み。

## 出力 JSON の形

```json
{
  "source": "https://read.amazon.co.jp/notebook",
  "fetched_at": "2026-07-20T...Z",
  "book_count": 12,
  "books": [
    {
      "asin": "B0XXXXXXX",
      "title": "本のタイトル",
      "author": "著者",
      "annotation_count": 34,
      "annotations": [
        {
          "id": "注釈ID（重複防止に使える）",
          "highlight": "ハイライト本文",
          "note": "自分のメモ or null",
          "header": "黄色のハイライト | 位置: 1,234",
          "location": "1234"
        }
      ]
    }
  ]
}
```

## うまくいかない時

- **「Amazon にログインしていません」** → `read.amazon.co.jp` でログインし直して再実行
- **book が 0 件 / highlight が 0 件** → ページ構造が想定と違う可能性。`chrome://extensions` の拡張の **「service worker」** と **offscreen** の DevTools でエラーを確認。セレクタ（`offscreen.js` / `background.js` の `scrollAndCollectBooks`）を実データに合わせて調整する
- **本の数が少ない（例: 14 冊だけ）** → バックグラウンドタブでの自動スクロールが遅延ロードを発火できていない可能性。`background.js` の `discoverBooks` で `active: false` を `active: true` にすると、タブを前面表示してより確実にロードできる（一瞬タブが開く）

## ファイル構成

| ファイル | 役割 |
|---|---|
| `manifest.json` | 権限・エントリ定義（MV3。`scripting`/`tabs` 権限を使用） |
| `background.js` | service worker。タブでの本一覧収集＋ヘッドレス fetch の司令塔 |
| `offscreen.js` / `offscreen.html` | HTML を DOMParser でパース（色・位置も抽出） |
| `popup.html` / `popup.js` | ボタン UI・進捗表示（同期 / JSON） |
| `options.html` / `options.js` | Notion トークン・親ページ設定、DB 作成 |
