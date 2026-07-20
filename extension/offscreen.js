// Runs in an offscreen document (has DOM). Parses Kindle notebook HTML
// strings sent by the service worker and returns structured data.

function toDoc(html) {
  return new DOMParser().parseFromString(html, "text/html");
}

function parseLibrary(html) {
  const d = toDoc(html);
  // Signed-out pages show the Amazon login form instead of the library.
  if (d.querySelector("#ap_email") || d.querySelector("form[name='signIn']")) {
    return { notLoggedIn: true, books: [] };
  }
  const books = [];
  d.querySelectorAll(".kp-notebook-library-each-book").forEach((div) => {
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
  return { notLoggedIn: false, books };
}

// Kindle encodes highlight color as a `kp-notebook-highlight-<color>` class,
// and the header text also names it in Japanese. Try the class first, then
// fall back to the header text.
function extractColor(row, headerText) {
  const colored = row.querySelector('[class*="kp-notebook-highlight-"]');
  if (colored) {
    const m = colored.className.match(
      /kp-notebook-highlight-(yellow|blue|pink|orange)/
    );
    if (m) {
      return { yellow: "黄色", blue: "青", pink: "ピンク", orange: "オレンジ" }[
        m[1]
      ];
    }
  }
  const h = headerText || "";
  if (h.includes("黄")) return "黄色";
  if (h.includes("青")) return "青";
  if (h.includes("ピンク")) return "ピンク";
  if (h.includes("オレンジ")) return "オレンジ";
  return null;
}

function parseAnnotations(html) {
  const d = toDoc(html);

  // Each annotation is a direct child <div> of #kp-notebook-annotations.
  let rows = [...d.querySelectorAll("#kp-notebook-annotations > div")].filter(
    (r) => r.querySelector("#highlight") || r.querySelector("#note")
  );

  // Fallback if the container id/structure differs: group by each highlight/note.
  if (rows.length === 0) {
    const set = new Set();
    d.querySelectorAll('[id="highlight"],[id="note"]').forEach((el) => {
      const wrap = el.closest("div.a-row.a-spacing-base") || el.parentElement;
      if (wrap) set.add(wrap);
    });
    rows = [...set];
  }

  const annotations = [];
  rows.forEach((row) => {
    const hl = row.querySelector("#highlight");
    const note = row.querySelector("#note");
    const header =
      row.querySelector("#annotationHighlightHeader") ||
      row.querySelector("#annotationNoteHeader");
    const loc = row.querySelector("#kp-annotation-location");
    const highlight = hl ? hl.textContent.trim() : null;
    const noteText = note ? note.textContent.trim() : null;
    if (!highlight && !noteText) return;
    const headerText = header
      ? header.textContent.replace(/\s+/g, " ").trim()
      : null;
    annotations.push({
      id: row.id || null,
      highlight: highlight || null,
      note: noteText || null,
      header: headerText,
      color: extractColor(row, headerText),
      location: loc ? loc.value : null,
    });
  });

  const next = d.querySelector(".kp-notebook-annotations-next-page-start");
  const cls = d.querySelector(".kp-notebook-content-limit-state");
  return {
    annotations,
    nextToken: next ? next.value || "" : "",
    contentLimitState: cls ? cls.value || "" : "",
  };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.target !== "offscreen") return;
  try {
    if (msg.kind === "library") sendResponse(parseLibrary(msg.html));
    else if (msg.kind === "annotations") sendResponse(parseAnnotations(msg.html));
    else sendResponse({ error: "unknown kind: " + msg.kind });
  } catch (e) {
    sendResponse({ error: String((e && e.message) || e) });
  }
  // Response is sent synchronously above.
});
