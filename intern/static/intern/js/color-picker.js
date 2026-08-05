// Farbwahl: haelt Textfeld und natives <input type="color"> aus
// _color_picker.html synchron. Das Textfeld bleibt die einzige Quelle der
// Wahrheit -- der Picker ist reine Zusatz-UI (Auswahl + Vorschau-Swatch in
// einem). Laeuft das JS nicht, bleibt das Textfeld sichtbar und voll bedienbar.
(function () {
    "use strict";

    var HEX_RE = /^#[0-9a-fA-F]{6}$/;

    function wire(wrap) {
        if (wrap.dataset.colorPickerInit) return;
        wrap.dataset.colorPickerInit = "1";
        var text = wrap.querySelector(".color-picker-text");
        var swatch = wrap.querySelector(".color-picker-swatch");
        if (!text || !swatch) return;

        text.addEventListener("input", function () {
            // Ungueltig/leer: Picker unveraendert lassen, kein Fehlerzustand --
            // <input type="color"> kann "leer" ohnehin nicht abbilden.
            if (HEX_RE.test(text.value)) swatch.value = text.value;
        });

        swatch.addEventListener("input", function () {
            text.value = swatch.value;
            // Damit Change-Tracking, das auf dem Textfeld lauscht (z.B.
            // konfiguration.js), den Picker-Klick mitbekommt.
            text.dispatchEvent(new Event("input", { bubbles: true }));
        });
    }

    function initAlle() {
        document.querySelectorAll("[data-color-picker]").forEach(wire);
    }

    function init() {
        if (!document.querySelector("[data-color-picker]")) return;
        initAlle();
    }

    document.addEventListener("htmx:afterSwap", initAlle);

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
