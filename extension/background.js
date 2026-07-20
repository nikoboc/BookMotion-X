// Service worker: orchestrates the scrape of read.amazon.co.jp/notebook.
//
// The library sidebar is lazy-loaded on scroll, so a plain fetch only sees the
// first ~14 books. To get ALL books we briefly open the notebook in a
// background tab and auto-scroll it (via an injected content script) until the
// whole library is in the DOM, then collect the book list and close the tab.
// Each book's highlights are then fetched headlessly (that endpoint returns
// server-rendered HTML), parsed in an offscreen document (SW has no DOMParser).

const BASE = "https://read.amazon.co.jp";
const NOTEBOOK = `${BASE}/notebook`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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

// ---------- library discovery (tab + auto-scroll) ----------

// Injected into the notebook tab. Must be fully self-contained.
async function scrollAndCollectBooks() {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  if (
    document.querySelector("#ap_email") ||
    document.querySelector("form[name='signIn']")
  ) {
    return { notLoggedIn: true, books: [] };
  }

  const SEL = ".kp-notebook-library-each-book";
  const count = () => document.querySelectorAll(SEL).length;

  // Scroll the library to the bottom repeatedly until the count stops growing.
  let last = count();
  let stable = 0;
  for (let i = 0; i < 300 && stable < 5; i++) {
    const books = document.querySelectorAll(SEL);
    if (books.length) books[books.length - 1].scrollIntoView({ block: "end" });
    const container =
      document.querySelector("#kp-notebook-library") ||
      document.scrollingElement ||
      document.body;
    if (container) {
      container.scrollTop = container.scrollHeight;
      container.dispatchEvent(new Event("scroll"));
    }
    window.scrollTo(0, document.body.scrollHeight);
    await sleep(500);
    const c = count();
    if (c === last) stable++;
    else {
      stable = 0;
      last = c;
    }
  }

  const books = [];
  document.querySelectorAll(SEL).forEach((div) => {
    const asin = div.id;
    if (!asin) return;
    const title = div.querySelector("h2.kp-notebook-searchable");
    const author = div.querySelector("p.kp-notebook-searchable");
    books.push({
      asin,
      title: title ? title.textContent.trim() : null,
      author: author ? author.textContent.trim() : null,
    });
  });
  return { notLoggedIn: false, books, domCount: count() };
}

function waitForTabComplete(tabId, timeoutMs = 20000) {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    };
    function listener(id, info) {
      if (id === tabId && info.status === "complete") finish();
    }
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(finish, timeoutMs);
  });
}

async function discoverBooks() {
  const tab = await chrome.tabs.create({ url: NOTEBOOK, active: false });
  try {
    await waitForTabComplete(tab.id);
    await sleep(1000); // let the initial list render
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: scrollAndCollectBooks,
    });
    return (results && results[0] && results[0].result) || { books: [] };
  } finally {
    try {
      await chrome.tabs.remove(tab.id);
    } catch (e) {
      /* tab already gone */
    }
  }
}

// ---------- fetching highlights (headless) ----------
async function fetchText(url) {
  const res = await fetch(url, {
    credentials: "include",
    headers: { "Accept-Language": "ja,en;q=0.9" },
  });
  return { text: await res.text(), url: res.url };
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
    await sleep(300);
  }
  return annotations;
}

async function run() {
  progress("notebook をタブで開いて全書籍を読み込み中…");
  const lib = await discoverBooks();
  if (lib.notLoggedIn) return { error: "not_logged_in" };

  const books = lib.books || [];
  progress(`${books.length} 冊を検出（スクロール読み込み完了）`);
  if (books.length === 0) return { error: "no_books" };

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
  const highlight_count = data.books.reduce((n, b) => n + b.annotation_count, 0);
  return {
    fetched_at: data.fetched_at,
    book_count: data.book_count,
    highlight_count,
  };
}

async function downloadJson(data) {
  const json = JSON.stringify(data, null, 2);
  const url = "data:application/json;charset=utf-8," + encodeURIComponent(json);
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
        toPopup({
          type: "done",
          data: { error: String((err && err.message) || err) },
        });
      });
  }
});
