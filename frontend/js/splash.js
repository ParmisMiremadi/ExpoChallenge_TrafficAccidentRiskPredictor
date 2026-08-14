/* Welcome screen. Purely a friendly intro overlay -- no auth, nothing gated
   behind it. The real app underneath is already booting (main.js's
   DOMContentLoaded handler runs regardless), so by the time someone dismisses
   this it's usually already populated.

   Dismiss on any key press or click: the screen "flies through" the logo
   (the logo bursts outward while the overlay's visible region collapses to a
   circle centered on the logo) revealing the app underneath. */

const Splash = (() => {
  let left = false;
  let cycleTimer = null;
  let keyHandler = null;
  let clickHandler = null;

  function cycleFeatures() {
    const pills = [...document.querySelectorAll("#splash-features .sf-pill")];
    if (!pills.length) return;
    let i = 0;
    pills[0].classList.add("is-active");
    cycleTimer = setInterval(() => {
      pills[i].classList.remove("is-active");
      i = (i + 1) % pills.length;
      pills[i].classList.add("is-active");
    }, 1900);
  }

  function exit() {
    if (left) return;
    left = true;
    clearInterval(cycleTimer);
    if (keyHandler) window.removeEventListener("keydown", keyHandler);

    const splash = document.getElementById("splash");
    if (!splash) return;
    if (clickHandler) splash.removeEventListener("click", clickHandler);

    const logo = document.getElementById("splash-logo");
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (reduce || !logo) {
      splash.classList.add("splash--fade");
      setTimeout(() => splash.remove(), 320);
      return;
    }

    // Center the collapsing circle exactly on the logo, wherever it sits.
    const r = logo.getBoundingClientRect();
    splash.style.setProperty("--sx", `${r.left + r.width / 2}px`);
    splash.style.setProperty("--sy", `${r.top + r.height / 2}px`);

    requestAnimationFrame(() => splash.classList.add("splash--leaving"));

    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      splash.remove();
    };
    splash.addEventListener("transitionend", (e) => {
      if (e.propertyName === "clip-path" || e.propertyName === "-webkit-clip-path") finish();
    });
    setTimeout(finish, 1100); // fallback in case transitionend doesn't fire
  }

  function init() {
    const splash = document.getElementById("splash");
    if (!splash) return;
    cycleFeatures();
    keyHandler = () => exit();
    clickHandler = () => exit();
    window.addEventListener("keydown", keyHandler);
    splash.addEventListener("click", clickHandler);
  }

  return { init };
})();

document.addEventListener("DOMContentLoaded", Splash.init);
