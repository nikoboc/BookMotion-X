// Service worker: orchestrates headless fetch of read.amazon.co.jp/notebook.
// It has no DOM, so all HTML parsing is delegated to the offscreen document.

const BASE = "https://read.amazon.co.jp";
const NOTEBOOK = `${BASE}/notebook`;

// ---------- offscreen document (HTML parsing) ----------
async function hasOffscreen() {
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
  });
  return contexts.length > 0;
}

async function ensureOffscreen() {
  if (await hasOffscreen()) return;
  await chrome.offscreen.createDocument({
    url: "offscreen.html",
    reasons: ["DOM_PARSER"],
    justification: "Parse Kindle notebook HTML into structured highlights.",
  });
}

async function parseInOffscreen(kind, html) {
  await ensureOffscreen();
  return await chrome.runtime.sendMessage({ target: "offscreen", kind, html });
}

// ---------- fetching ----------
async function fetchText(url) {
  const res = await fetch(url, {
    credentials: "include",
    headers: { "Accept-Language": "ja,en;q=0.9" },
  });
  const text = await res.text();
  return { text, url: res.url, status: res.status, redirected: res.redirected };
}

function toPopup(payload) {
  chrome.runtime.sendMessage({ target: "popup", ...payload }).catch(() => {});
}

function progress(msg) {
  toPopup({ type: "progress", msg });
}

async function fetchBookAnnotations(asin) {
  let annotations = [];
  let token = "";
  let contentLimitState = "";
  // Hard cap on pages as a runaway guard.
  for (let page = 0; page < 100; page++) {
    const params = new URLSearchParams({ asin, contentLimitState });
    if (token) params.set("token", token);
    const { text } = await fetchText(`${NOTEBOOK}?${params.toString()}`);
    const parsed = await parseInOffscreen("annotations", text);
    if (parsed.error) throw new Error("parse annotations: " + parsed.error);
    annotations = annotations.concat(parsed.annotations);
    contentLimitState = parsed.contentLimitState || "";
    token = parsed.nextToken || "";
    if (!token) break;
    await new Promise((r) => setTimeout(r, 300)); // be polite
  }
  return annotations;
}

async function run() {
  progress("notebook を取得中…");
  const lib = await fetchText(NOTEBOOK);
  if (lib.url.includes("/ap/signin") || /signin|\/ap\//.test(lib.url)) {
    return { error: "not_logged_in" };
  }

  const libParsed = await parseInOffscreen("library", lib.text);
  if (libParsed.error) return { error: "parse library: " + libParsed.error };
  if (libParsed.notLoggedIn) return { error: "not_logged_in" };

  const books = libParsed.books;
  progress(`${books.length} 冊を検出`);

  const out = [];
  for (let i = 0; i < books.length; i++) {
    const b = books[i];
    progress(`(${i + 1}/${books.length}) ${b.title || b.asin}`);
    const annotations = await fetchBookAnnotations(b.asin);
    out.push({ ...b, annotation_count: annotations.length, annotations });
  }

  return {
    source: NOTEBOOK,
    fetched_at: new Date().toISOString(),
    book_count: out.length,
    books: out,
  };
}

// ---------- output ----------
function summarize(data) {
  const highlight_count = data.books.reduce(
    (n, b) => n + b.annotation_count,
    0
  );
  return {
    fetched_at: data.fetched_at,
    book_count: data.book_count,
    highlight_count,
  };
}

async function downloadJson(data) {
  const json = JSON.stringify(data, null, 2);
  const url =
    "data:application/json;charset=utf-8," + encodeURIComponent(json);
  await chrome.downloads.download({
    url,
    filename: "kindle_highlights.json",
    saveAs: false,
  });
}

// ---------- message entrypoint ----------
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.target !== "background") return;
  if (msg.type === "run") {
    sendResponse({ started: true });
    run()
      .then(async (data) => {
        if (!data.error) {
          await chrome.storage.local.set({ lastSummary: summarize(data) });
          await downloadJson(data);
        }
        toPopup({ type: "done", data });
      })
      .catch((err) => {
        toPopup({ type: "done", data: { error: String((err && err.message) || err) } });
      });
  }
});
