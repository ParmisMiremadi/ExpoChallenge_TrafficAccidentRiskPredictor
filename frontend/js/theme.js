/* Dark-mode toggle. The initial theme is applied pre-paint by an inline script
   in <head>; this wires the toggle button and persists the choice. Other
   modules can listen for the `themechange` event to re-render (e.g. Plotly). */

const Theme = (() => {
  const KEY = "safevector-theme";

  function current() {
    return document.documentElement.getAttribute("data-theme") || "light";
  }

  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem(KEY, theme); } catch (e) {}
    document.dispatchEvent(new CustomEvent("themechange", { detail: { theme } }));
  }

  function toggle() {
    apply(current() === "dark" ? "light" : "dark");
  }

  function wire() {
    const btn = document.getElementById("theme-toggle");
    if (btn) btn.addEventListener("click", toggle);
  }

  return { current, apply, toggle, wire };
})();
