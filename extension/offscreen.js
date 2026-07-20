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
    annotations.push({
      id: row.id || null,
      highlight: highlight || null,
      note: noteText || null,
      header: header ? header.textContent.replace(/\s+/g, " ").trim() : null,
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
