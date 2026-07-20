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

function toUI(payload) {
  chrome.runtime.sendMessage({ target: "ui", ...payload }).catch(() => {});
}

function progress(msg) {
  toUI({ type: "progress", msg });
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

// Fetch every book + its highlights. Shared by "run" (JSON) and "sync" (Notion).
// limit: optional cap on the number of books (for a small test run).
async function fetchAll(limit) {
  progress("notebook をタブで開いて全書籍を読み込み中…");
  const lib = await discoverBooks();
  if (lib.notLoggedIn) return { error: "not_logged_in" };

  let books = lib.books || [];
  progress(`${books.length} 冊を検出（スクロール読み込み完了）`);
  if (books.length === 0) return { error: "no_books" };
  if (limit) books = books.slice(0, limit);

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

async function run(limit) {
  return await fetchAll(limit);
}

// ---------- Notion ----------
const NOTION_VERSION = "2022-06-28";

function localDate() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// Accept a raw id (with/without dashes) or a full Notion URL.
function normalizeId(input) {
  if (!input) return "";
  const m = String(input).replace(/-/g, "").match(/[0-9a-fA-F]{32}/);
  if (!m) return String(input).trim();
  const h = m[0].toLowerCase();
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(
    16,
    20
  )}-${h.slice(20)}`;
}

async function getConfig() {
  return await chrome.storage.local.get([
    "notionToken",
    "notionParentPageId",
    "notionDatabaseId",
  ]);
}

async function notionFetch(token, path, method, body) {
  for (let attempt = 0; attempt < 5; attempt++) {
    const res = await fetch("https://api.notion.com/v1" + path, {
      method,
      headers: {
        Authorization: "Bearer " + token,
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (res.status === 429) {
      const retry = Number(res.headers.get("Retry-After") || "1");
      await sleep(retry * 1000);
      continue;
    }
    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(`Notion ${res.status}: ${json.message || res.statusText}`);
    }
    return json;
  }
  throw new Error("Notion のレート制限で再試行上限に達しました");
}

async function createNotionDatabase(token, parentPageId) {
  const body = {
    parent: { type: "page_id", page_id: parentPageId },
    title: [{ type: "text", text: { content: "Kindle Highlights" } }],
    // Property insertion order = column order (title is always first).
    properties: {
      引用文: { title: {} },
      本のタイトル: { rich_text: {} },
      本の著者: { rich_text: {} },
      ハイライト位置: { number: {} },
      ハイライト色: {
        select: {
          options: [
            { name: "黄色", color: "yellow" },
            { name: "青", color: "blue" },
            { name: "ピンク", color: "pink" },
            { name: "オレンジ", color: "orange" },
          ],
        },
      },
      実行日: { date: {} },
    },
  };
  return await notionFetch(token, "/databases", "POST", body);
}

// Notion caps a single rich-text object at 2000 chars; split long highlights.
function richText(content) {
  const s = content || "";
  if (!s) return [];
  const out = [];
  for (let i = 0; i < s.length; i += 2000) {
    out.push({ type: "text", text: { content: s.slice(i, i + 2000) } });
  }
  return out;
}

function pageProperties(r) {
  const props = {
    引用文: { title: richText(r.quote) },
    本のタイトル: { rich_text: richText(r.title) },
    本の著者: { rich_text: richText(r.author) },
    実行日: { date: { start: r.date } },
  };
  if (r.location != null && !Number.isNaN(r.location)) {
    props["ハイライト位置"] = { number: r.location };
  }
  if (r.color) props["ハイライト色"] = { select: { name: r.color } };
  return props;
}

function buildRows(data, today) {
  const rows = [];
  for (const b of data.books) {
    for (const a of b.annotations) {
      if (!a.highlight) continue; // schema has no note column; skip note-only
      const digits =
        a.location != null && a.location !== ""
          ? Number(String(a.location).replace(/[^0-9]/g, ""))
          : null;
      rows.push({
        id: a.id,
        quote: a.highlight,
        title: b.title || "",
        author: b.author || "",
        location: digits != null && !Number.isNaN(digits) ? digits : null,
        color: a.color || null,
        date: today,
      });
    }
  }
  // 本のタイトル昇順 → ハイライト位置昇順（挿入順＝表示順）
  rows.sort((x, y) => {
    const t = (x.title || "").localeCompare(y.title || "", "ja");
    if (t) return t;
    const lx = x.location == null ? Infinity : x.location;
    const ly = y.location == null ? Infinity : y.location;
    return lx - ly;
  });
  return rows;
}

async function sync(limit) {
  const cfg = await getConfig();
  if (!cfg.notionToken) return { error: "no_token" };

  let dbId = cfg.notionDatabaseId ? normalizeId(cfg.notionDatabaseId) : "";
  if (!dbId) {
    const parent = normalizeId(cfg.notionParentPageId);
    if (!parent) return { error: "no_db_or_parent" };
    progress("Notion データベースを作成中…");
    const db = await createNotionDatabase(cfg.notionToken, parent);
    dbId = db.id;
    await chrome.storage.local.set({ notionDatabaseId: dbId });
    toUI({ type: "db_created", id: dbId, url: db.url });
  }

  const data = await fetchAll(limit);
  if (data.error) return data;

  const rows = buildRows(data, localDate());

  // Dedup against previously inserted annotations for this database.
  const insertedKey = "inserted_" + dbId;
  const store = await chrome.storage.local.get(insertedKey);
  const inserted = new Set(store[insertedKey] || []);
  const keyOf = (r) =>
    r.id || `${r.title}|${r.location}|${(r.quote || "").slice(0, 40)}`;
  const fresh = rows.filter((r) => !inserted.has(keyOf(r)));

  progress(
    `登録対象 ${fresh.length} 件（重複スキップ ${rows.length - fresh.length} 件）`
  );

  let ok = 0;
  let fail = 0;
  for (let i = 0; i < fresh.length; i++) {
    const r = fresh[i];
    try {
      await notionFetch(cfg.notionToken, "/pages", "POST", {
        parent: { database_id: dbId },
        properties: pageProperties(r),
      });
      ok++;
      inserted.add(keyOf(r));
    } catch (e) {
      fail++;
      console.error("Notion insert failed:", e);
    }
    if ((i + 1) % 10 === 0 || i === fresh.length - 1) {
      progress(`Notion 登録中… ${i + 1}/${fresh.length}（成功${ok}/失敗${fail}）`);
      await chrome.storage.local.set({ [insertedKey]: [...inserted] });
    }
    await sleep(334); // ~3 req/s (Notion's average rate limit)
  }
  await chrome.storage.local.set({ [insertedKey]: [...inserted] });

  return {
    notion: true,
    dbId,
    total: rows.length,
    inserted: ok,
    failed: fail,
    skipped: rows.length - fresh.length,
  };
}

async function createDbOnly() {
  const cfg = await getConfig();
  if (!cfg.notionToken) throw new Error("Notion トークンが未設定です");
  const parent = normalizeId(cfg.notionParentPageId);
  if (!parent) throw new Error("親ページ ID が未設定です");
  const db = await createNotionDatabase(cfg.notionToken, parent);
  await chrome.storage.local.set({ notionDatabaseId: db.id });
  return db;
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
    run(msg.limit)
      .then(async (data) => {
        if (!data.error) {
          await chrome.storage.local.set({ lastSummary: summarize(data) });
          await downloadJson(data);
        }
        toUI({ type: "done", data });
      })
      .catch((err) =>
        toUI({ type: "done", data: { error: String((err && err.message) || err) } })
      );
    return;
  }

  if (msg.type === "sync") {
    sendResponse({ started: true });
    sync(msg.limit)
      .then((data) => toUI({ type: "done", data }))
      .catch((err) =>
        toUI({ type: "done", data: { error: String((err && err.message) || err) } })
      );
    return;
  }

  if (msg.type === "createDb") {
    sendResponse({ started: true });
    createDbOnly()
      .then((db) => toUI({ type: "db_created", id: db.id, url: db.url }))
      .catch((err) =>
        toUI({ type: "db_error", error: String((err && err.message) || err) })
      );
    return;
  }
});
