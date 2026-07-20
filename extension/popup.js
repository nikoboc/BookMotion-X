const syncBtn = document.getElementById("sync");
const syncTestBtn = document.getElementById("syncTest");
const runBtn = document.getElementById("run");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const openOptions = document.getElementById("openOptions");

openOptions.addEventListener("click", () => chrome.runtime.openOptionsPage());

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.target !== "ui") return;
  if (msg.type === "progress") statusEl.textContent = msg.msg;
  if (msg.type === "db_created") statusEl.textContent = "Notion データベースを作成しました。";
  if (msg.type === "done") showDone(msg.data);
});

function busy(on) {
  syncBtn.disabled = on;
  syncTestBtn.disabled = on;
  runBtn.disabled = on;
}

syncBtn.addEventListener("click", () => {
  statusEl.textContent = "同期を開始…";
  summaryEl.textContent = "";
  busy(true);
  chrome.runtime.sendMessage({ target: "background", type: "sync" });
});

syncTestBtn.addEventListener("click", () => {
  statusEl.textContent = "テスト同期を開始（先頭1冊）…";
  summaryEl.textContent = "";
  busy(true);
  chrome.runtime.sendMessage({ target: "background", type: "sync", limit: 1 });
});

runBtn.addEventListener("click", () => {
  statusEl.textContent = "取得を開始…";
  summaryEl.textContent = "";
  busy(true);
  chrome.runtime.sendMessage({ target: "background", type: "run" });
});

function showDone(data) {
  busy(false);
  if (!data) {
    statusEl.textContent = "不明なエラー";
    return;
  }
  if (data.error === "not_logged_in") {
    statusEl.textContent =
      "Amazon にログインしていません。read.amazon.co.jp にログイン後、再実行してください。";
    return;
  }
  if (data.error === "no_books") {
    statusEl.textContent =
      "本が0冊でした。ログイン状態を確認して再実行してください。";
    return;
  }
  if (data.error === "no_token") {
    statusEl.innerHTML =
      "Notion トークンが未設定です。<b>⚙ Notion 設定</b>から設定してください。";
    return;
  }
  if (data.error === "no_db_or_parent") {
    statusEl.innerHTML =
      "Notion のデータベースも親ページも未設定です。<b>⚙ Notion 設定</b>で作成してください。";
    return;
  }
  if (data.error) {
    statusEl.textContent = "エラー: " + data.error;
    return;
  }

  // Notion sync result
  if (data.notion) {
    statusEl.textContent = "Notion 同期が完了しました。";
    summaryEl.textContent = [
      `対象ハイライト: ${data.total} 件`,
      `新規登録: ${data.inserted} 件`,
      `重複スキップ: ${data.skipped} 件`,
      data.failed ? `失敗: ${data.failed} 件（詳細は service worker の Console）` : "",
    ]
      .filter(Boolean)
      .join("\n");
    return;
  }

  // JSON-only result
  const total = data.books.reduce((n, b) => n + b.annotation_count, 0);
  statusEl.textContent = `完了：${data.book_count} 冊 / ハイライト ${total} 件。kindle_highlights.json をダウンロードしました。`;
  const first = data.books.find((b) => b.annotations.length);
  if (first) {
    summaryEl.textContent =
      `例) ${first.title}\n   「${(first.annotations[0].highlight || "").slice(0, 60)}…」`;
  }
}
