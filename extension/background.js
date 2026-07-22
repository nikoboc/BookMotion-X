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
    const authorText = author
      ? author.textContent.trim().replace(/^(?:著者|by)\s*[:：]\s*/i, "").trim()
      : null;
    books.push({
      asin,
      title: title ? title.textContent.trim() : null,
      author: authorText,
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
    await sleep(150);
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

  // Fetch each book's highlights with bounded concurrency (much faster than
  // one-at-a-time). Results are kept index-aligned with `books`.
  const CONCURRENCY = 6;
  const out = new Array(books.length);
  let next = 0;
  let done = 0;
  async function worker() {
    while (next < books.length) {
      const i = next++;
      const b = books[i];
      try {
        const annotations = await fetchBookAnnotations(b.asin);
        out[i] = { ...b, annotation_count: annotations.length, annotations };
      } catch (e) {
        out[i] = {
          ...b,
          annotation_count: 0,
          annotations: [],
          error: String((e && e.message) || e),
        };
      }
      done++;
      if (done % 5 === 0 || done === books.length) {
        progress(`ハイライト取得 ${done}/${books.length} 冊`);
      }
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(CONCURRENCY, books.length) }, worker)
  );

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
    // NOTE: Notion's API ignores property order on database creation — the UI
    // shows columns in an internal (arbitrary) order regardless of the order
    // here or of adding them one-by-one. The public API has no way to set
    // column order, so arrange the columns once by hand after first creation
    // (the DB is created once and reused, so this is a one-time step).
    properties: {
      ハイライト文: { title: {} },
      書籍名: { rich_text: {} },
      著者名: { rich_text: {} },
      位置: { number: {} },
      マーカー色: {
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
      // Dedup key (Amazon annotation id, or a composite fallback). Kept last.
      注釈ID: { rich_text: {} },
    },
  };
  return await notionFetch(token, "/databases", "POST", body);
}

// Make sure an existing database has the 注釈ID column (older DBs won't).
async function ensureNotionSchema(token, dbId) {
  const db = await notionFetch(token, "/databases/" + dbId, "GET");
  if (db.properties && db.properties["注釈ID"]) return;
  await notionFetch(token, "/databases/" + dbId, "PATCH", {
    properties: { 注釈ID: { rich_text: {} } },
  });
}

// Notion is the source of truth for dedup: read every existing 注釈ID value.
async function queryExistingKeys(token, dbId) {
  const existing = new Set();
  let cursor;
  do {
    const body = { page_size: 100 };
    if (cursor) body.start_cursor = cursor;
    const res = await notionFetch(
      token,
      "/databases/" + dbId + "/query",
      "POST",
      body
    );
    for (const page of res.results || []) {
      const prop = page.properties && page.properties["注釈ID"];
      const txt =
        prop && prop.rich_text
          ? prop.rich_text.map((t) => t.plain_text).join("")
          : "";
      if (txt) existing.add(txt);
    }
    cursor = res.has_more ? res.next_cursor : undefined;
    if (cursor) await sleep(200);
  } while (cursor);
  return existing;
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
    ハイライト文: { title: richText(r.quote) },
    書籍名: { rich_text: richText(r.title) },
    著者名: { rich_text: richText(r.author) },
    実行日: { date: { start: r.date } },
    注釈ID: { rich_text: richText(r.key) },
  };
  if (r.location != null && !Number.isNaN(r.location)) {
    props["位置"] = { number: r.location };
  }
  if (r.color) props["マーカー色"] = { select: { name: r.color } };
  return props;
}

// Rows for a single book, location-ascending. Each row carries its dedup key.
function bookRows(book, annotations, today) {
  const rows = [];
  for (const a of annotations || []) {
    if (!a.highlight) continue; // schema has no note column; skip note-only
    const digits =
      a.location != null && a.location !== ""
        ? Number(String(a.location).replace(/[^0-9]/g, ""))
        : null;
    const location = digits != null && !Number.isNaN(digits) ? digits : null;
    const r = {
      id: a.id,
      quote: a.highlight,
      title: book.title || "",
      author: book.author || "",
      location,
      color: a.color || null,
      date: today,
    };
    r.key = r.id || `${r.title}|${r.location}|${(r.quote || "").slice(0, 40)}`;
    rows.push(r);
  }
  rows.sort((x, y) => {
    const lx = x.location == null ? Infinity : x.location;
    const ly = y.location == null ? Infinity : y.location;
    return lx - ly;
  });
  return rows;
}

// Bounded-concurrency gate so we can prefetch a few books ahead while the
// (rate-limited) Notion inserts drain, without launching all fetches at once.
class Semaphore {
  constructor(max) {
    this.max = max;
    this.cur = 0;
    this.q = [];
  }
  run(fn) {
    return new Promise((resolve, reject) => {
      const task = () => {
        this.cur++;
        Promise.resolve()
          .then(fn)
          .then(
            (v) => {
              this.cur--;
              this._next();
              resolve(v);
            },
            (e) => {
              this.cur--;
              this._next();
              reject(e);
            }
          );
      };
      if (this.cur < this.max) task();
      else this.q.push(task);
    });
  }
  _next() {
    if (this.q.length && this.cur < this.max) this.q.shift()();
  }
}

async function sync(limit) {
  const cfg = await getConfig();
  if (!cfg.notionToken) return { error: "no_token" };
  const token = cfg.notionToken;

  let dbId = cfg.notionDatabaseId ? normalizeId(cfg.notionDatabaseId) : "";
  if (!dbId) {
    const parent = normalizeId(cfg.notionParentPageId);
    if (!parent) return { error: "no_db_or_parent" };
    progress("Notion データベースを作成中…");
    const db = await createNotionDatabase(token, parent);
    dbId = db.id;
    await chrome.storage.local.set({ notionDatabaseId: dbId });
    toUI({ type: "db_created", id: dbId, url: db.url });
  }

  // Notion is the source of truth for dedup.
  progress("Notion のスキーマと既存データを確認中…");
  await ensureNotionSchema(token, dbId);
  const existing = await queryExistingKeys(token, dbId);
  progress(`既存 ${existing.size} 件を確認`);

  // Discover the full library (tab + auto-scroll), then process books in
  // 書籍名昇順 so creation order == 書籍名昇順→位置昇順.
  progress("notebook をタブで開いて全書籍を読み込み中…");
  const lib = await discoverBooks();
  if (lib.notLoggedIn) return { error: "not_logged_in" };
  let books = lib.books || [];
  if (books.length === 0) return { error: "no_books" };
  if (limit) books = books.slice(0, limit);
  books.sort((a, b) => (a.title || "").localeCompare(b.title || "", "ja"));
  progress(`${books.length} 冊。取得と登録を並行実行します…`);

  const today = localDate();

  // Pipeline (B): prefetch up to 6 books ahead while inserts drain. Each
  // book's highlights are consumed strictly in title order.
  const sem = new Semaphore(6);
  const fetches = books.map((b) =>
    sem
      .run(() => fetchBookAnnotations(b.asin))
      .then((annotations) => ({ annotations }))
      .catch((e) => ({ annotations: [], error: String((e && e.message) || e) }))
  );

  let ok = 0;
  let fail = 0;
  let total = 0;
  let skipped = 0;
  const MIN_INTERVAL = 340; // ms; Notion's average limit is ~3 req/s

  for (let i = 0; i < books.length; i++) {
    const b = books[i];
    const res = await fetches[i]; // ready by now (fetch outran the inserts)
    const rows = bookRows(b, res.annotations, today);
    total += rows.length;
    const fresh = rows.filter((r) => !existing.has(r.key));
    skipped += rows.length - fresh.length;

    for (const r of fresh) {
      const started = Date.now();
      try {
        await notionFetch(token, "/pages", "POST", {
          parent: { database_id: dbId },
          properties: pageProperties(r),
        });
        ok++;
        existing.add(r.key);
      } catch (e) {
        fail++;
        console.error("Notion insert failed:", e);
      }
      await sleep(Math.max(0, MIN_INTERVAL - (Date.now() - started)));
    }

    progress(
      `(${i + 1}/${books.length}) ${b.title || b.asin} ｜ 登録${ok} 重複${skipped} 失敗${fail}`
    );
  }

  return { notion: true, dbId, total, inserted: ok, failed: fail, skipped };
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
