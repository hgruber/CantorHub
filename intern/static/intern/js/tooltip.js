// Erklaerungs-Tooltip: zeigt den Text aus [data-hilfe] in einer einzigen Blase, die
// am Body haengt. Ausloeser sind meist die Info-Icons aus _hilfe_icon.html, deren
// Text als help_text am Model steht.
//
// Alle Handler sind auf das document delegiert und die Blase wird erst beim ersten
// Anzeigen gebaut. Deshalb gibt es bewusst keinen Bail-out ueber ein anfaengliches
// querySelectorAll: das Kalender-Tagesdetail wird von kalender.js befuellt, das
// Termin-Banner per htmx getauscht und Tabellenzeilen per Infinite-Scroll
// nachgeladen -- ein Init beim Laden wuerde diese Ausloeser alle verpassen.
(function () {
    "use strict";

    var HOVER_MS = 200; // Verzoegerung, damit ein Ueberfahren nichts aufblitzen laesst
    var RAND = 8;       // Mindestabstand zum Viewport-Rand
    var ABSTAND = 8;    // Abstand zwischen Ausloeser und Blase

    var blase = null;
    var aktuell = null; // Element, zu dem die Blase gerade offen ist
    var timer = null;

    function hole() {
        if (!blase) {
            blase = document.createElement("div");
            blase.className = "hilfe-bubble";
            blase.id = "hilfe-bubble";
            blase.setAttribute("role", "tooltip");
            document.body.appendChild(blase);
        }
        return blase;
    }

    function positioniere(el) {
        var r = el.getBoundingClientRect();
        var b = blase.getBoundingClientRect();

        // bevorzugt unterhalb, mittig; nach oben kippen, wenn unten kein Platz ist
        var y = r.bottom + ABSTAND;
        if (y + b.height > window.innerHeight - RAND) {
            var oben = r.top - b.height - ABSTAND;
            if (oben >= RAND) y = oben;
        }
        var x = r.left + r.width / 2 - b.width / 2;
        x = Math.max(RAND, Math.min(x, window.innerWidth - b.width - RAND));

        blase.style.transform = "translate(" + Math.round(x) + "px," + Math.round(y) + "px)";
    }

    function zeige(el) {
        var text = el.getAttribute("data-hilfe");
        if (!text) return;
        hole().textContent = text;
        aktuell = el;
        el.setAttribute("aria-describedby", "hilfe-bubble");
        positioniere(el); // erst messen, dann sichtbar schalten
        blase.classList.add("visible");
    }

    function verstecke() {
        if (timer) {
            clearTimeout(timer);
            timer = null;
        }
        if (!aktuell) return;
        aktuell.removeAttribute("aria-describedby");
        aktuell = null;
        if (blase) blase.classList.remove("visible");
    }

    function ausloeser(e) {
        return e.target.closest ? e.target.closest("[data-hilfe]") : null;
    }

    document.addEventListener("mouseover", function (e) {
        var el = ausloeser(e);
        if (!el || el === aktuell) return;
        verstecke();
        timer = setTimeout(function () {
            timer = null;
            zeige(el);
        }, HOVER_MS);
    });

    document.addEventListener("mouseout", function (e) {
        var el = ausloeser(e);
        if (!el) return;
        // innerhalb desselben Ausloesers bewegt: nichts tun
        if (e.relatedTarget && el.contains(e.relatedTarget)) return;
        verstecke();
    });

    // Nur echte Tastaturnavigation. Bei Maus- und Touch-Klick ist :focus-visible
    // falsch -- sonst wuerde der folgende click sofort wieder schliessen.
    document.addEventListener("focusin", function (e) {
        var el = ausloeser(e);
        if (!el || !el.matches(":focus-visible")) return;
        verstecke();
        zeige(el);
    });

    document.addEventListener("focusout", function (e) {
        if (ausloeser(e)) verstecke();
    });

    // Tap/Klick togglet -- der Weg, auf dem Touch-Geraete ueberhaupt herankommen
    document.addEventListener("click", function (e) {
        var el = ausloeser(e);
        if (!el) {
            verstecke();
            return;
        }
        if (el === aktuell) verstecke();
        else {
            verstecke();
            zeige(el);
        }
    });

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") verstecke();
    });

    // capture, damit auch das Scrollen innerer Container (.table-container,
    // .cal-panel-scroll) die Blase mitnimmt
    document.addEventListener("scroll", verstecke, true);
    window.addEventListener("resize", verstecke);
})();
