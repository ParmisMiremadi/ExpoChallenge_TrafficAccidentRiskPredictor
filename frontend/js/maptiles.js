/* Theme-aware Leaflet basemap tiles. Light mode uses CARTO Positron (clean,
   pale); dark mode uses CARTO Dark Matter so the map blends into dark mode
   instead of glaring white. Shared by the risk map and the routing map. */

const MapTiles = (() => {
  const LIGHT = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
  const DARK = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
  const ATTR = "&copy; OpenStreetMap contributors &copy; CARTO";

  function url() {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    return dark ? DARK : LIGHT;
  }

  function add(map, maxZoom) {
    return L.tileLayer(url(), { maxZoom: maxZoom || 19, attribution: ATTR }).addTo(map);
  }

  // Remove the old tile layer and add one for the current theme; returns it.
  function swap(map, current) {
    const maxZoom = (current && current.options.maxZoom) || 19;
    if (current) map.removeLayer(current);
    return add(map, maxZoom);
  }

  return { add, swap };
})();
