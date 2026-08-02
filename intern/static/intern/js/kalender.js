/* Kalender-Monatsansicht: Klick auf einen Tag öffnet eine große, lesbare
   Offcanvas-Leiste mit allen Terminen und Geburtstagen dieses Tages (Desktop wie
   Mobil) und – für Berechtigte – dem Anlege-Formular mit vorbefülltem Datum.
   Direkter Klick auf einen Eintrag (Chip-Link) navigiert wie gewohnt. Ohne das
   Recht "intern.add_termin" rendert der View kein Formular; dann öffnen wie
   bisher nur Tage mit Einträgen. Event-Delegation auf document, damit
   htmx-Swaps beim Monatswechsel überlebt werden. */
(function initKalender() {
  const panel = document.getElementById("cal-day-panel");
  const overlay = document.getElementById("cal-panel-overlay");
  if (!panel || !overlay) return;

  const dateEl = panel.querySelector(".cal-panel-date");
  const bodyEl = panel.querySelector(".cal-panel-body");
  const addForm = panel.querySelector("[data-cal-add-form]");
  const addOpen = panel.querySelector("[data-cal-add-open]");
  const darfAnlegen = !!addForm;

  function showForm(offen) {
    if (!darfAnlegen) return;
    addForm.hidden = !offen;
    addOpen.hidden = offen;
    if (offen) {
      const erstes = addForm.querySelector('[name="kurz"]');
      if (erstes) erstes.focus();
    }
  }

  function prepareForm(iso) {
    addForm.reset();
    const datum = addForm.querySelector('[name="datum"]');
    if (datum) datum.value = iso || "";
    // Rücksprung in den gerade angezeigten Monat – hx-push-url hält die URL aktuell.
    const next = addForm.querySelector('[name="next"]');
    if (next) next.value = window.location.pathname + window.location.search;
  }

  function openPanel(day) {
    const detail = day.querySelector(".cal-day-detail");
    dateEl.textContent = day.dataset.datum || "";
    bodyEl.innerHTML = detail ? detail.innerHTML : "";
    bodyEl.hidden = !detail;
    if (darfAnlegen) {
      prepareForm(day.dataset.iso);
      // An einem leeren Tag ist das Anlegen das Einzige, was man tun kann –
      // dann steht das Formular ohne Extraklick offen.
      showForm(!detail);
    }
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
    // Klicks in der Leiste: Schließen-Button, Formular auf/zu, sonst durchlassen.
    if (e.target.closest(".cal-panel")) {
      if (e.target.closest(".cal-panel-close")) closePanel();
      else if (e.target.closest("[data-cal-add-open]")) showForm(true);
      else if (e.target.closest("[data-cal-add-cancel]")) showForm(false);
      return;
    }
    // Direkter Klick auf einen Eintrag im Raster -> normale Navigation.
    if (e.target.closest(".cal-chip")) return;

    const day = e.target.closest(".cal-day");
    if (!day || !day.closest("#cal-view")) return;
    if (darfAnlegen || day.classList.contains("has-events")) openPanel(day);
  });

  overlay.addEventListener("click", closePanel);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePanel();
  });
  document.body.addEventListener("htmx:afterSwap", closePanel);
})();
