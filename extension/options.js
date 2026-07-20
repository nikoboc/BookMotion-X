const tokenEl = document.getElementById("token");
const parentEl = document.getElementById("parent");
const dbidEl = document.getElementById("dbid");
const statusEl = document.getElementById("status");
const saveBtn = document.getElementById("save");
const createBtn = document.getElementById("createDb");

// Load saved config.
chrome.storage.local
  .get(["notionToken", "notionParentPageId", "notionDatabaseId"])
  .then((c) => {
    tokenEl.value = c.notionToken || "";
    parentEl.value = c.notionParentPageId || "";
    dbidEl.value = c.notionDatabaseId || "";
  });

async function save() {
  await chrome.storage.local.set({
    notionToken: tokenEl.value.trim(),
    notionParentPageId: parentEl.value.trim(),
    notionDatabaseId: dbidEl.value.trim(),
  });
  statusEl.textContent = "保存しました。";
}

saveBtn.addEventListener("click", save);

createBtn.addEventListener("click", async () => {
  await save(); // persist token/parent first
  statusEl.textContent = "データベースを作成中…";
  createBtn.disabled = true;
  chrome.runtime.sendMessage({ target: "background", type: "createDb" });
});

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.target !== "ui") return;
  if (msg.type === "db_created") {
    createBtn.disabled = false;
    dbidEl.value = msg.id;
    chrome.storage.local.set({ notionDatabaseId: msg.id });
    statusEl.innerHTML =
      "データベースを作成しました。" +
      (msg.url ? ` <a href="${msg.url}" target="_blank">Notion で開く</a>` : "");
  }
  if (msg.type === "db_error") {
    createBtn.disabled = false;
    statusEl.textContent = "作成エラー: " + msg.error;
  }
});
