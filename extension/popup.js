const runBtn = document.getElementById("run");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.target !== "popup") return;
  if (msg.type === "progress") statusEl.textContent = msg.msg;
  if (msg.type === "done") showDone(msg.data);
});

runBtn.addEventListener("click", () => {
  statusEl.textContent = "開始…";
  summaryEl.textContent = "";
  runBtn.disabled = true;
  chrome.runtime.sendMessage({ target: "background", type: "run" });
});

function showDone(data) {
  runBtn.disabled = false;
  if (!data) {
    statusEl.textContent = "不明なエラー";
    return;
  }
  if (data.error === "not_logged_in") {
    statusEl.textContent =
      "Amazon にログインしていません。ブラウザで read.amazon.co.jp を開いてログイン後、再実行してください。";
    return;
  }
  if (data.error === "no_books") {
    statusEl.textContent =
      "本が0冊でした。ログイン状態を確認して再実行してください（改善しない場合はタブを前面で開く方式に切り替えます）。";
    return;
  }
  if (data.error) {
    statusEl.textContent = "エラー: " + data.error;
    return;
  }
  const total = data.books.reduce((n, b) => n + b.annotation_count, 0);
  statusEl.textContent = `完了：${data.book_count} 冊 / ハイライト ${total} 件。kindle_highlights.json をダウンロードしました。`;

  const lines = data.books
    .slice(0, 5)
    .map((b) => `• ${b.title || b.asin} … ${b.annotation_count} 件`);
  const first = data.books.find((b) => b.annotations.length);
  if (first) {
    lines.push("");
    lines.push(`例) ${first.title}`);
    lines.push(`   「${(first.annotations[0].highlight || "").slice(0, 60)}…」`);
  }
  summaryEl.textContent = lines.join("\n");
}

// Show last run's summary on open.
chrome.storage.local.get("lastSummary").then(({ lastSummary }) => {
  if (lastSummary && !summaryEl.textContent) {
    summaryEl.textContent = `前回: ${lastSummary.book_count} 冊 / ${lastSummary.highlight_count} 件 (${lastSummary.fetched_at})`;
  }
});
