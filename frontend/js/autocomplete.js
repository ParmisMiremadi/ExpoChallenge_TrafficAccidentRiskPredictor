/* Reusable location autocomplete. Attach it to any text input; it queries
   /api/suggest as the user types and shows a ranked dropdown of states,
   counties, and cities. On pick it fills the input and calls onSelect(item).

   The dropdown is a fixed-position element on <body>, positioned under the
   input, so it never gets clipped by overflow:hidden containers. */

const Autocomplete = (() => {
  const TYPE_LABEL = { state: "State", county: "County", city: "City" };

  function attach(input, { onSelect, minChars = 2 } = {}) {
    if (!input) return;

    const list = document.createElement("div");
    list.className = "ac-list";
    list.style.display = "none";
    document.body.appendChild(list);

    let items = [];
    let active = -1;
    let debounce;
    let seq = 0;

    function place() {
      const r = input.getBoundingClientRect();
      list.style.left = `${r.left}px`;
      list.style.top = `${r.bottom + 4}px`;
      list.style.width = `${r.width}px`;
    }

    function close() {
      list.style.display = "none";
      active = -1;
    }

    function render() {
      if (!items.length) { close(); return; }
      list.innerHTML = items.map((it, i) => `
        <div class="ac-item ${i === active ? "active" : ""}" data-i="${i}">
          <span class="ac-type ac-type-${it.type}">${TYPE_LABEL[it.type] || it.type}</span>
          <span class="ac-label">${it.label}</span>
        </div>`).join("");
      place();
      list.style.display = "block";
    }

    async function query() {
      const q = input.value.trim();
      if (q.length < minChars) { close(); return; }
      const my = ++seq;
      try {
        const res = await API.suggest(q, 8);
        if (my !== seq) return;          // a newer keystroke superseded this
        items = res || [];
        active = -1;
        render();
      } catch (e) { close(); }
    }

    function choose(i) {
      const it = items[i];
      if (!it) return;
      input.value = it.label;
      close();
      if (onSelect) onSelect(it);
    }

    input.setAttribute("autocomplete", "off");

    input.addEventListener("input", () => {
      clearTimeout(debounce);
      debounce = setTimeout(query, 180);
    });

    input.addEventListener("keydown", (e) => {
      if (list.style.display === "none") return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        active = Math.min(active + 1, items.length - 1);
        render();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        active = Math.max(active - 1, 0);
        render();
      } else if (e.key === "Enter") {
        if (active >= 0) { e.preventDefault(); choose(active); }
      } else if (e.key === "Escape") {
        close();
      }
    });

    // Use mousedown so the pick registers before the input's blur closes the list.
    list.addEventListener("mousedown", (e) => {
      const row = e.target.closest(".ac-item");
      if (row) { e.preventDefault(); choose(parseInt(row.dataset.i, 10)); }
    });

    input.addEventListener("blur", () => setTimeout(close, 120));
    window.addEventListener("scroll", () => {
      if (list.style.display !== "none") place();
    }, true);
    window.addEventListener("resize", () => {
      if (list.style.display !== "none") place();
    });
  }

  return { attach };
})();
