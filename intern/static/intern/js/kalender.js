/* Kalender-Monatsansicht: Klick auf einen Tag mit Einträgen öffnet eine große,
   lesbare Offcanvas-Leiste mit allen Terminen und Geburtstagen dieses Tages
   (Desktop wie Mobil). Direkter Klick auf einen Eintrag (Chip-Link) navigiert
   wie gewohnt. Event-Delegation auf document, damit htmx-Swaps beim
   Monatswechsel überlebt werden. */
(function initKalender() {
  const panel = document.getElementById("cal-day-panel");
  const overlay = document.getElementById("cal-panel-overlay");
  if (!panel || !overlay) return;

  const dateEl = panel.querySelector(".cal-panel-date");
  const bodyEl = panel.querySelector(".cal-panel-body");

  function openPanel(day) {
    const detail = day.querySelector(".cal-day-detail");
    dateEl.textContent = day.dataset.datum || "";
    bodyEl.innerHTML = detail ? detail.innerHTML : "";
    panel.classList.add("open");
    overlay.classList.add("open");
    panel.setAttribute("aria-hidden", "false");
  }

  function closePanel() {
    panel.classList.remove("open");
    overlay.classList.remove("open");
    panel.setAttribute("aria-hidden", "true");
  }

  document.addEventListener("click", (e) => {
    // Klicks in der Leiste: nur der Schließen-Button schließt, Links navigieren.
    if (e.target.closest(".cal-panel")) {
      if (e.target.closest(".cal-panel-close")) closePanel();
      return;
    }
    // Direkter Klick auf einen Eintrag im Raster -> normale Navigation.
    if (e.target.closest(".cal-chip")) return;

    const day = e.target.closest(".cal-day.has-events");
    if (day && day.closest("#cal-view")) {
      openPanel(day);
    }
  });

  overlay.addEventListener("click", closePanel);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePanel();
  });
  document.body.addEventListener("htmx:afterSwap", closePanel);
})();
