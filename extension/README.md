# Kindle → Notion 拡張機能（自作）

Kindle のハイライト（`read.amazon.co.jp/notebook`）を、ブラウザ拡張が**自分でアクセス**して取得する自作ツール。

- ログイン済みセッションを使うので、Cookie 抜き取りも管理者権限も不要
- **本一覧の取得**: notebook の左サイドバーはスクロールで遅延ロードされる（素の fetch だと最初の ~14 冊しか取れない）。そこで拡張が **notebook をバックグラウンドタブで開き、injected content script でサイドバーを自動スクロール**して全冊をロード → 書籍リストを回収 → タブを閉じる
- **各書籍のハイライト取得**: `?asin=` エンドポイントはサーバー描画 HTML を返すため、こちらは **ヘッドレス fetch** で取得
- MV3 の service worker には DOMParser が無いため、ハイライト HTML のパースは offscreen document に委譲

## フェーズ

- **フェーズ1（今ここ）**: 取得 → 整形 → `kindle_highlights.json` を自動ダウンロード
- **フェーズ2（予定）**: 取得したデータを Notion API で DB に直接登録

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
| `offscreen.js` / `offscreen.html` | HTML を DOMParser でパース |
| `popup.html` / `popup.js` | ボタン UI・進捗表示 |
