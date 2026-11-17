(function () {
  "use strict";

  // 1. Before / After CHILL+ comparison slider
  var viewport = document.getElementById("compare-viewport");
  var range = document.getElementById("compare-range");
  var readout = document.getElementById("compare-readout");
  var presets = document.querySelectorAll(".preset-btn[data-split]");

  function setSplit(val) {
    var n = Math.max(0, Math.min(100, Number(val)));
    if (!viewport || !range) return;
    viewport.style.setProperty("--split", n + "%");
    range.value = String(n);
    if (readout) {
      if (n >= 95) readout.textContent = "Raw O (unclassified)";
      else if (n <= 5) readout.textContent = "CHILL+ labels";
      else readout.textContent = "Raw O / CHILL+";
    }
    for (var i = 0; i < presets.length; i++) {
      var active = Number(presets[i].getAttribute("data-split")) === n;
      presets[i].classList.toggle("is-active", active);
      presets[i].setAttribute("aria-pressed", active ? "true" : "false");
    }
  }

  if (range && viewport) {
    setSplit(range.value || 50);
    range.addEventListener("input", function () {
      setSplit(range.value);
    });
    presets.forEach(function (btn) {
      btn.addEventListener("click", function () {
        setSplit(btn.getAttribute("data-split"));
      });
    });
  }

  // 2. Language tabs
  var tabs = Array.prototype.slice.call(document.querySelectorAll('[role="tab"]'));
  var panels = Array.prototype.slice.call(document.querySelectorAll('[role="tabpanel"]'));

  function activateTab(tab, moveFocus) {
    var targetId = tab.getAttribute("aria-controls");
    tabs.forEach(function (t) {
      var selected = t === tab;
      t.setAttribute("aria-selected", selected ? "true" : "false");
      t.classList.toggle("is-active", selected);
      if (selected) t.removeAttribute("tabindex");
      else t.setAttribute("tabindex", "-1");
    });
    panels.forEach(function (panel) {
      var match = panel.id === targetId;
      panel.hidden = !match;
      panel.classList.toggle("is-active", match);
    });
    if (moveFocus) tab.focus();
  }

  tabs.forEach(function (tab, index) {
    tab.addEventListener("click", function () {
      activateTab(tab, false);
    });
    tab.addEventListener("keydown", function (e) {
      var next = null;
      if (e.key === "ArrowRight") next = (index + 1) % tabs.length;
      else if (e.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
      else if (e.key === "Home") next = 0;
      else if (e.key === "End") next = tabs.length - 1;
      if (next !== null) {
        e.preventDefault();
        activateTab(tabs[next], true);
      }
    });
  });

  // 3. Copy buttons (install commands + BibTeX)
  var statusEl = document.getElementById("copy-status");
  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".copy-btn[data-copy]");
    if (!btn) return;
    var text = btn.getAttribute("data-copy");
    if (!text || !navigator.clipboard) return;
    var original = btn.textContent;
    navigator.clipboard.writeText(text).then(function () {
      btn.textContent = "Copied";
      if (btn.id === "copy-bibtex-btn" && statusEl) {
        statusEl.textContent = "BibTeX citation copied to clipboard.";
      }
      setTimeout(function () {
        btn.textContent = original;
      }, 1600);
    }).catch(function () {});
  });

  // 4. Close Docs dropdown on Escape or outside click
  var docsMenu = document.querySelector(".docs-dropdown");
  if (docsMenu) {
    document.addEventListener("click", function (e) {
      if (docsMenu.open && !docsMenu.contains(e.target)) {
        docsMenu.open = false;
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && docsMenu.open) {
        docsMenu.open = false;
        var summary = docsMenu.querySelector("summary");
        if (summary) summary.focus();
      }
    });
  }
})();
