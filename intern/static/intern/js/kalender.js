/* Kalender-Monatsansicht: auf schmalen Bildschirmen klappt ein Tipp auf einen
   Tag mit Einträgen dessen Detailliste auf (Punkte-Darstellung). Auf großen
   Bildschirmen sind die Chips ohnehin sichtbar, dann passiert nichts.
   Event-Delegation auf document, damit htmx-Swaps beim Monatswechsel überlebt
   werden (kein Re-Init nötig). */
(function initKalender() {
  function closeAll(except) {
    document.querySelectorAll(".cal-day.is-open").forEach((d) => {
      if (d !== except) d.classList.remove("is-open");
    });
  }

  document.addEventListener("click", (e) => {
    // Klick auf einen Eintrag (Link) nie abfangen – normale Navigation.
    if (e.target.closest(".cal-chip")) return;

    const day = e.target.closest(".cal-day.has-events");
    if (!day || !day.closest("#cal-view")) {
      closeAll(null);
      return;
    }
    // Nur im kompakten (mobilen) Layout aufklappen.
    if (window.matchMedia("(max-width: 768px)").matches) {
      const wasOpen = day.classList.contains("is-open");
      closeAll(day);
      day.classList.toggle("is-open", !wasOpen);
    }
  });

  // Beim Monatswechsel (htmx) etwaigen offenen Tag schließen.
  document.body.addEventListener("htmx:afterSwap", () => closeAll(null));
})();
