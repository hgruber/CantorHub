(function () {
  const LABELS = ["Sehr schwach", "Schwach", "Mittel", "Stark", "Sehr stark"];

  function init() {
    const p1 = document.getElementById("new_password1");
    if (!p1 || typeof zxcvbn === "undefined") return;
    const p2 = document.getElementById("new_password2");

    // Build widget: strength bar row + optional match row
    const widget = document.createElement("div");
    widget.className = "pw-widget";
    widget.innerHTML =
      '<div class="pw-strength" hidden>' +
        '<div class="pw-strength-track"><div class="pw-strength-bar"></div></div>' +
        '<span class="pw-strength-label"></span>' +
      '</div>' +
      (p2 ? '<div class="pw-match" hidden><span class="pw-match-label"></span></div>' : "");

    // Preferred anchor: explicit placeholder between form-grid and buttons.
    // Fallback: after p2 (reset page — no grid), then after p1.
    const anchor = document.getElementById("pw-status");
    if (anchor) {
      anchor.appendChild(widget);
    } else if (p2) {
      p2.insertAdjacentElement("afterend", widget);
    } else {
      p1.insertAdjacentElement("afterend", widget);
    }

    const strengthWrap = widget.querySelector(".pw-strength");
    const bar          = widget.querySelector(".pw-strength-bar");
    const strengthLbl  = widget.querySelector(".pw-strength-label");
    const matchWrap    = widget.querySelector(".pw-match");
    const matchLbl     = matchWrap && matchWrap.querySelector(".pw-match-label");

    function updateStrength() {
      if (!p1.value) { strengthWrap.hidden = true; return; }
      const score = zxcvbn(p1.value).score; // 0-4
      strengthWrap.hidden = false;
      strengthWrap.dataset.score = score;
      bar.style.width = (score + 1) * 20 + "%";
      strengthLbl.textContent = LABELS[score];
    }

    function updateMatch() {
      if (!matchWrap) return;
      if (!p2.value) { matchWrap.hidden = true; return; }
      const ok = p2.value === p1.value;
      matchWrap.hidden = false;
      matchWrap.dataset.match = ok ? "yes" : "no";
      matchLbl.textContent = ok
        ? "✓ Passwörter stimmen überein"
        : "✗ Passwörter stimmen nicht überein";
    }

    p1.addEventListener("input", function () { updateStrength(); updateMatch(); });
    if (p2) p2.addEventListener("input", updateMatch);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
}());
