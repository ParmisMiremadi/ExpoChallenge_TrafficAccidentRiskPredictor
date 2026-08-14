/* Dangerous Zones & Alerts view: a live, ranked list of the highest-risk
   areas under the current hour, each with its reason and recommendation.
   Merges the "dangerous zones", "alerts", and "recommendations" outputs. */

const Zones = (() => {
  let currentTier = "all";
  let lastRows = [];

  function tierClass(tier) {
    return (tier || "").toLowerCase();
  }

  function render(rows) {
    lastRows = rows;
    const list = document.getElementById("zone-list");
    if (!rows.length) {
      list.innerHTML = `<div class="placeholder">No zones at this level right now.</div>`;
      return;
    }
    list.innerHTML = rows.map((z) => `
      <div class="card zone-card" data-name="${z.name}">
        <div class="zone-main">
          <div class="zone-rank">${z.rank}</div>
          <div class="zone-body">
            <div class="zone-title">
              ${z.name}
              <span class="badge ${tierClass(z.tier)}">${z.tier}</span>
            </div>
            <div class="zone-reason">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16v.5"/></svg>
              ${z.reason}
            </div>
            <div class="zone-rec">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 1 4 10c-.7.7-1 1.3-1 2H9c0-.7-.3-1.3-1-2a6 6 0 0 1 4-10Z"/></svg>
              ${z.recommendation}
            </div>
            <button class="zone-details-btn" data-idx="${z.rank}">Details &darr;</button>
          </div>
          <div class="zone-score">
            <div class="num" style="color:${Charts.TIER_COLORS[z.tier] || 'var(--ink)'}">${fmt.prob(z.prob)}</div>
            <div class="unit">est. accident probability</div>
          </div>
        </div>
        <div class="zone-detail" hidden>
          <div class="zd-grid">
            <div><span class="zd-k">Estimated probability</span><span class="zd-v">${fmt.prob(z.prob)}</span></div>
            <div><span class="zd-k">Risk level</span><span class="zd-v">${z.tier}</span></div>
            <div><span class="zd-k">Avg severity</span><span class="zd-v">${z.severity.toFixed(1)} / 4</span></div>
            <div><span class="zd-k">Conditions</span><span class="zd-v">${z.time_period} · ${z.weather}</span></div>
            <div><span class="zd-k">Coordinates</span><span class="zd-v">${z.lat.toFixed(2)}, ${z.lng.toFixed(2)}</span></div>
          </div>
          <div class="zd-factors">
            <span class="zd-k">Contributing factors</span>
            <ul>${z.factors.map((f) => `<li>${f}</li>`).join("")}</ul>
          </div>
          <div class="zd-note">Probability is the calibrated chance of at least one crash in this area during this time window.</div>
        </div>
      </div>
    `).join("");

    list.querySelectorAll(".zone-details-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const card = btn.closest(".zone-card");
        const panel = card.querySelector(".zone-detail");
        const open = !panel.hidden;
        panel.hidden = open;
        btn.innerHTML = open ? "Details &darr;" : "Hide details &uarr;";
      });
    });
  }

  async function load(hour) {
    const rows = await API.zones(hour, currentTier);
    render(rows);
  }

  function wire(getHour) {
    document.querySelectorAll("#view-zones .chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        document.querySelectorAll("#view-zones .chip").forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");
        currentTier = chip.dataset.tier;
        load(getHour());
      });
    });

    document.getElementById("btn-export").addEventListener("click", () => {
      exportCsv(lastRows);
    });
  }

  function exportCsv(rows) {
    const header = ["Rank", "Area", "Tier", "Est. probability", "Reason", "Recommendation"];
    const lines = rows.map((r) =>
      [r.rank, r.name, r.tier, fmt.prob(r.prob), r.reason, r.recommendation]
        .map((v) => `"${String(v).replace(/"/g, '""')}"`)
        .join(",")
    );
    const csv = [header.join(","), ...lines].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "roadguard-dangerous-zones.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return { load, wire };
})();
