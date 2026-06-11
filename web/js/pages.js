// Footer site pages (about, technology, privacy, terms, glossary) opened as
// in-page modals. The same routes still serve standalone HTML for refresh,
// crawlers and shared links; here we fetch that HTML, lift its <main> content
// into a modal, and drive history so the browser Back button just closes the
// modal instead of reloading the whole app.

const PAGE_PATHS = new Set(["/about", "/technology", "/privacy", "/terms", "/glossary"]);

let modal = null;
let bodyEl = null;
let lastFocus = null;

async function openPage(path) {
  const wasOpen = modal.classList.contains("open");
  try {
    const res = await fetch(path, { headers: { "X-Requested-With": "modal" } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const doc = new DOMParser().parseFromString(await res.text(), "text/html");
    const main = doc.querySelector("main.page") || doc.querySelector("main") || doc.body;
    // The standalone pages lead with a "Back to the map" link; the modal has
    // its own close affordance, so drop it.
    const back = main.querySelector('a[href="/"]');
    if (back && back.closest("p")) back.closest("p").remove();

    bodyEl.innerHTML = main.innerHTML;
    if (!wasOpen) lastFocus = document.activeElement;
    modal.classList.add("open");
    document.body.style.overflow = "hidden";
    bodyEl.scrollTop = 0;
    history[wasOpen ? "replaceState" : "pushState"]({ pageModal: path }, "", path);

    const h1 = bodyEl.querySelector("h1");
    if (h1) { h1.setAttribute("tabindex", "-1"); h1.focus(); }
  } catch (e) {
    // Network or parse failure: fall back to a real navigation.
    window.location.href = path;
  }
}

function closePage(restoreUrl = true) {
  if (!modal.classList.contains("open")) return;
  modal.classList.remove("open");
  document.body.style.overflow = "";
  bodyEl.innerHTML = "";
  if (restoreUrl && history.state && history.state.pageModal) history.back();
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}

export function setupPages() {
  modal = document.getElementById("page-modal");
  bodyEl = document.getElementById("page-modal-body");
  if (!modal || !bodyEl) return;

  // One delegated handler covers the footer links and any cross-links the
  // pages make to each other (about -> technology, etc.).
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (!a) return;
    const href = a.getAttribute("href");
    if (href && PAGE_PATHS.has(href)) {
      e.preventDefault();
      openPage(href);
    } else if (href === "/" && a.closest("#page-modal")) {
      // A "Back to the map" link that slipped through: just close.
      e.preventDefault();
      closePage();
    }
  });

  modal.querySelector(".page-modal-overlay").addEventListener("click", () => closePage());
  document.getElementById("page-modal-close").addEventListener("click", () => closePage());
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal.classList.contains("open")) closePage();
  });
  // Browser Back while a page is open: pop closes the modal, no reload.
  window.addEventListener("popstate", () => {
    if (modal.classList.contains("open")) closePage(false);
  });
}
