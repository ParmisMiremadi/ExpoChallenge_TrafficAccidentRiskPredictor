/* Welcome screen. Purely a friendly intro overlay -- no auth, nothing gated
   behind it. The real app underneath is already booting (main.js's
   DOMContentLoaded handler runs regardless), so by the time someone dismisses
   this it's usually already populated.

   On open: the title and tagline type themselves in, then the description's
   two lines and the feature pills each pop up one at a time (no typing), then
   the hint fades in and starts its pulse. A key press or click dismisses it
   immediately at any point, whatever stage it's at.

   Dismissal "flies through" the logo (it bursts outward while the overlay's
   visible region collapses to a circle centered on the logo) revealing the
   app underneath. */

const Splash = (() => {
  let left = false;
  let cycleTimer = null;
  let typeTimers = [];
  let keyHandler = null;
  let clickHandler = null;

  const TYPE_SPEED = 45;    // ms per character -- readable, not sluggish
  const TYPE_GAP = 200;     // pause between each typed line
  const REVEAL_GAP = 150;   // pause before the pills start popping
  const LINE_STAGGER = 180; // ms between each description line popping in
  const POP_STAGGER = 90;   // ms between each feature pill popping in

  function wait(ms) {
    return new Promise((resolve) => { typeTimers.push(setTimeout(resolve, ms)); });
  }

  function typeInto(el, text, speed) {
    return new Promise((resolve) => {
      el.textContent = "";
      el.classList.add("is-typing");
      let i = 0;
      const tick = () => {
        i++;
        el.textContent = text.slice(0, i);
        if (i >= text.length) {
          el.classList.remove("is-typing");
          resolve();
          return;
        }
        typeTimers.push(setTimeout(tick, speed));
      };
      typeTimers.push(setTimeout(tick, speed));
    });
  }

  // Pop a set of elements in one at a time (no typing -- just a quick "pop"),
  // used for both the description lines and the feature pills.
  function popEach(selector, className, stagger) {
    return new Promise((resolve) => {
      const els = [...document.querySelectorAll(selector)];
      if (!els.length) { resolve(); return; }
      els.forEach((el, i) => {
        typeTimers.push(setTimeout(() => el.classList.add(className), i * stagger));
      });
      typeTimers.push(setTimeout(resolve, (els.length - 1) * stagger + 300));
    });
  }

  async function runIntro() {
    const title = document.getElementById("splash-title");
    const tagline = document.getElementById("splash-tagline");
    const content = document.querySelector(".splash-content");
    if (!title || !tagline || !content) return;

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      document.querySelectorAll("#splash-desc .sd-line").forEach((l) => l.classList.add("line-in"));
      document.querySelectorAll("#splash-features .sf-pill").forEach((p) => p.classList.add("pill-in"));
      content.classList.add("is-revealed");
      cycleFeatures();
      return;
    }

    const titleText = title.textContent.trim();
    const taglineText = tagline.textContent.trim();

    await typeInto(title, titleText, TYPE_SPEED);
    await wait(TYPE_GAP);
    await typeInto(tagline, taglineText, TYPE_SPEED);
    await wait(TYPE_GAP);
    await popEach("#splash-desc .sd-line", "line-in", LINE_STAGGER);
    await wait(REVEAL_GAP);
    await popEach("#splash-features .sf-pill", "pill-in", POP_STAGGER);
    if (left) return;
    content.classList.add("is-revealed");
    cycleFeatures();
  }

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
    typeTimers.forEach(clearTimeout);
    typeTimers = [];
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
    runIntro();
    keyHandler = () => exit();
    clickHandler = () => exit();
    window.addEventListener("keydown", keyHandler);
    splash.addEventListener("click", clickHandler);
  }

  return { init };
})();

document.addEventListener("DOMContentLoaded", Splash.init);
