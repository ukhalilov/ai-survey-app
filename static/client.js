function showVal(slider) {
  const bubble = slider.nextElementSibling;
  if (bubble) bubble.textContent = slider.value;
}
function beforeSubmit(hiddenId) {
  const h = document.getElementById(hiddenId);
  if (h) {
    const started = window.__start_ts || Date.now();
    h.value = Date.now() - started;
  }
  return true;
}
window.addEventListener("load", () => {
  window.__start_ts = Date.now();
  document.querySelectorAll("input[type=range]").forEach(s => showVal(s));
});
function enforceUniqueRanks(sel) {
  const selects = Array.from(document.querySelectorAll(".rank-select"));
  const values = selects.map(s => s.value).filter(v => v);
  const duplicates = values.filter((v, i, a) => a.indexOf(v) !== i);
  if (duplicates.length > 0) {
    selects.forEach(s => { if (s !== sel && s.value === sel.value) s.value = ""; });
  }
}
function togglePrepend(btn, id) {
  const el = document.getElementById(id);
  if (!el) return;
  const show = el.style.display === "none" || el.style.display === "";
  el.style.display = show ? "inline" : "none";
  btn.textContent = show ? "hide prepend" : "see prepend";
}
// expose globally
window.togglePrepend = togglePrepend;

// Part B ranking: toggle, auto-complete last, and no hard disables
(function () {
  function providers() {
    return Array.from(document.querySelectorAll(".rank-card"))
      .map(card => card.getAttribute("data-provider"));
  }
  function currentAssignments() {
    const used = {};
    providers().forEach(p => {
      const el = document.getElementById("rank_" + p);
      if (el && el.value) used[p] = parseInt(el.value, 10);
    });
    return used;
  }
  function setRank(provider, rankOrEmpty) {
    const el = document.getElementById("rank_" + provider);
    if (el) el.value = rankOrEmpty ? String(rankOrEmpty) : "";
  }
  function refreshUI() {
    const used = currentAssignments();
    const usedVals = Object.values(used);

    document.querySelectorAll(".rank-card").forEach(card => {
      const prov = card.getAttribute("data-provider");
      const mine = used[prov] || 0;
      card.querySelectorAll(".pill").forEach(btn => {
        const r = parseInt(btn.dataset.rank, 10);
        const takenElsewhere = usedVals.includes(r) && mine !== r;

        // visual states (no disabling)
        btn.classList.toggle("active", mine === r);
        btn.classList.toggle("taken", takenElsewhere);
        btn.setAttribute("aria-pressed", String(mine === r));
        btn.removeAttribute("disabled");  // ensure clickable
      });
    });

    const chosen = providers().filter(p => used[p]).length;
    const prog = document.getElementById("b-progress");
    if (prog) prog.textContent = `Chosen ${chosen}/4 ranks (no ties).`;

    const submit = document.getElementById("b-submit");
    if (submit) submit.disabled = (chosen !== 4);
  }

  // Assign / toggle / move rank
  window.pickRank = function (provider, rank) {
    const used = currentAssignments();
    const current = used[provider] || 0;

    if (current === rank) {
      // Toggle OFF
      setRank(provider, "");
    } else {
      // Move this rank here (clear it from whoever had it)
      Object.entries(used).forEach(([p, val]) => {
        if (p !== provider && val === rank) setRank(p, "");
      });
      setRank(provider, rank);
    }

    // Auto-complete last one
    const after = currentAssignments();
    const provs = providers();
    const unassigned = provs.filter(p => !after[p]);
    const remainingRanks = [1, 2, 3, 4].filter(r => !Object.values(after).includes(r));
    if (unassigned.length === 1 && remainingRanks.length === 1) {
      setRank(unassigned[0], remainingRanks[0]);
    }

    refreshUI();
  };

  document.addEventListener("DOMContentLoaded", refreshUI);
})();


// Part C zoom handlers
(function(){
  window.openZoom = function(src){
    const dlg = document.getElementById("c-zoom");
    const img = document.getElementById("c-zoom-img");
    if (!dlg || !img) return;
    img.src = src;
    if (typeof dlg.showModal === "function") dlg.showModal();
    else dlg.setAttribute("open",""); // very old browsers
  };
  window.closeZoom = function(){
    const dlg = document.getElementById("c-zoom");
    if (!dlg) return;
    if (typeof dlg.close === "function") dlg.close();
    else dlg.removeAttribute("open");
  };
  document.addEventListener("keydown", (e)=>{
    if (e.key === "Escape") closeZoom();
  });
  // click outside image to close
  const dlg = document.getElementById("c-zoom");
  if (dlg) {
    dlg.addEventListener("click",(e)=>{
      const img = document.getElementById("c-zoom-img");
      if (e.target === dlg && img && !img.contains(e.target)) closeZoom();
    });
  }
})();

// Part A: show/hide "How to rate" block using localStorage
(function() {
  const KEY = "hide_a_instructions";

  function apply() {
    const box = document.getElementById("a-instructions");
    const toggle = document.getElementById("a-instructions-toggle");
    if (!box || !toggle) return; // not on Part A page
    const hidden = localStorage.getItem(KEY) === "1";
    box.style.display = hidden ? "none" : "";
    toggle.style.display = hidden ? "" : "none";
  }

  window.hideAInstructions = function() {
    localStorage.setItem(KEY, "1");
    apply();
  };

  window.showAInstructions = function() {
    localStorage.removeItem(KEY);
    apply();
  };

  document.addEventListener("DOMContentLoaded", apply);
})();
