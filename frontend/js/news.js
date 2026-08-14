/* Live news ticker: pulls short items from /api/news (NWS weather alerts +
   optional Jina/Gemini traffic news) and scrolls them across the bottom bar.
   The track content is duplicated so the CSS marquee loops seamlessly. Includes
   a hide/unhide toggle (chevron down = hide, chevron up = unhide). */

const NewsTicker = (() => {
  const REFRESH_MS = 5 * 60 * 1000;

  function tagClass(cat) {
    const c = (cat || "").toLowerCase();
    if (["weather", "traffic", "accident", "warning", "news", "info"].includes(c)) return c;
    return "news";
  }

  function itemHtml(it) {
    return `<span class="tk-item"><span class="tk-tag ${tagClass(it.category)}">${it.category}</span>${it.text}</span>`;
  }

  function render(items) {
    const track = document.getElementById("ticker-track");
    if (!items || !items.length) return;
    const html = items.map(itemHtml).join("");
    // Duplicate the sequence so translateX(-50%) wraps without a visible gap.
    track.innerHTML = html + html;
  }

  async function load() {
    try {
      const data = await API.news();
      render(data.items);
    } catch (e) {
      /* leave whatever is showing */
    }
  }

  function wireToggle() {
    const ticker = document.getElementById("ticker");
    const btn = document.getElementById("ticker-toggle");
    const chevron = document.getElementById("ticker-chevron");
    btn.addEventListener("click", () => {
      const hidden = ticker.classList.toggle("hidden");
      // chevron up (m18 15-6-6-6 6) when hidden, down (m6 9 6 6 6-6) when shown
      chevron.innerHTML = hidden ? '<path d="m18 15-6-6-6 6"/>' : '<path d="m6 9 6 6 6-6"/>';
      btn.setAttribute("aria-label", hidden ? "Show news ticker" : "Hide news ticker");
      btn.title = hidden ? "Show" : "Hide";
    });
  }

  function init() {
    wireToggle();
    load();
    setInterval(load, REFRESH_MS);
  }

  return { init };
})();
