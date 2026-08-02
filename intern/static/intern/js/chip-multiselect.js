// Chip-Mehrfachauswahl: baut aus einem <select multiple> die Chip-Oberflaeche von
// _chip_multiselect.html auf. Das <select> bleibt die einzige Quelle der Wahrheit --
// verschoben wird ausschliesslich, indem option.selected gesetzt wird. Laeuft das JS
// nicht, bleibt das native Feld sichtbar und voll bedienbar.
//
// Zeigergeraete ziehen per SortableJS, Touch-Geraete tippen oder oeffnen mit einem
// Long-Press das Ziel-Popover. Drag wird bewusst nur bei "(pointer: fine)"
// eingeschaltet: auf Touch wuerde SortableJS sonst mit dem Scrollen der Seite und mit
// dem Long-Press um dieselbe Geste konkurrieren.
(function () {
    "use strict";

    var LONGPRESS_MS = 500;
    var BEWEGUNG_MAX = 8; // px Toleranz, bis der Long-Press als Wischen gilt
    var instanzen = [];
    var gruppenZaehler = 0;
    var picker = null;

    // ---------------------------------------------------------------- Popover

    function schliessePicker() {
        if (!picker) return;
        picker.remove();
        picker = null;
    }

    // Die Ziele sind bewusst eine Liste, obwohl jede Instanz heute genau zwei
    // Container hat. Bekommen mehrere Instanzen spaeter einen gemeinsamen Vorrat
    // (etwa Lesen/Schreiben/Loeschen auf der Ordner-Berechtigungsseite), aendert
    // sich nur diese Funktion -- oeffnePicker bleibt, wie es ist.
    function ziele(inst, li) {
        var aktuell = li.parentElement;
        return [
            { el: inst.selected, label: inst.auswahlLabel },
            { el: inst.pool, label: inst.vorratLabel },
        ].filter(function (z) {
            return z.el !== aktuell;
        });
    }

    function positioniere(el, anker) {
        // position:fixed und rohe Viewport-Koordinaten: die Offcanvas-Panels sind
        // selbst fixed und scrollen intern, ein an window.scrollY ausgerichtetes
        // Popover bliebe beim Scrollen im Panel stehen.
        var r = anker.getBoundingClientRect();
        var b = el.getBoundingClientRect();
        var top = r.bottom + 4;
        if (top + b.height > window.innerHeight - 4) {
            top = Math.max(4, r.top - b.height - 4);
        }
        var left = Math.min(Math.max(4, r.left), window.innerWidth - b.width - 4);
        el.style.top = top + "px";
        el.style.left = Math.max(4, left) + "px";
    }

    function oeffnePicker(inst, li) {
        schliessePicker();
        var zl = ziele(inst, li);
        if (!zl.length) return;

        picker = document.createElement("div");
        picker.className = "chip-ms-picker";
        zl.forEach(function (z) {
            var b = document.createElement("button");
            b.type = "button";
            b.className = "chip-ms-pick";
            b.textContent = "→ " + z.label;
            b.addEventListener("click", function () {
                verschiebe(inst, li, z.el);
                schliessePicker();
            });
            picker.appendChild(b);
        });

        document.body.appendChild(picker);
        positioniere(picker, li);
    }

    // ------------------------------------------------------------- Zustand

    function setzeRolle(inst, li, gewaehlt) {
        li.classList.toggle("chip-ms-chip", gewaehlt);
        var btn = li.querySelector(".chip-ms-aktion");
        btn.textContent = gewaehlt ? "×" : "+";
        btn.title = gewaehlt ? "Entfernen" : "Hinzufügen";
        btn.setAttribute("aria-label", btn.title);
    }

    // Zustand an den Container angleichen, ohne das Element zu bewegen -- so ruft
    // der Sortable-Handler dieselbe Logik, ohne die per Drag gewaehlte Position
    // wieder zu zerstoeren.
    function uebernehme(inst, li, zielListe) {
        var gewaehlt = zielListe === inst.selected;
        li._option.selected = gewaehlt;
        setzeRolle(inst, li, gewaehlt);
        li.hidden = false;
        if (!gewaehlt) filtere(inst);
        inst.nativ.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function verschiebe(inst, li, zielListe) {
        zielListe.appendChild(li);
        uebernehme(inst, li, zielListe);
    }

    function filtere(inst) {
        if (!inst.suche || inst.suche.hidden) return;
        var q = inst.suche.value.trim().toLowerCase();
        Array.prototype.forEach.call(inst.pool.children, function (li) {
            li.hidden = q !== "" && li._option.text.toLowerCase().indexOf(q) === -1;
        });
    }

    function baueItems(inst) {
        inst.selected.textContent = "";
        inst.pool.textContent = "";
        Array.prototype.forEach.call(inst.nativ.options, function (opt) {
            var li = document.createElement("li");
            li.className = "chip-ms-item";
            li._option = opt;

            var text = document.createElement("span");
            text.className = "chip-ms-text";
            text.textContent = opt.text;
            li.appendChild(text);

            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "chip-ms-aktion";
            btn.tabIndex = -1; // der ganze Eintrag ist die Schaltflaeche
            li.appendChild(btn);

            (opt.selected ? inst.selected : inst.pool).appendChild(li);
            setzeRolle(inst, li, opt.selected);
        });
    }

    // ------------------------------------------------------------- Aufbau

    function initEine(wrap) {
        var nativ = wrap.querySelector(".chip-ms-native");
        var ui = wrap.querySelector(".chip-ms-ui");
        var selected = wrap.querySelector(".chip-ms-selected");
        var pool = wrap.querySelector(".chip-ms-pool");
        // Nie ueber getElementById: auf der Repertoire-Liste stehen Filter- und
        // Anlegen-Formular gleichzeitig im DOM, id_solist gibt es dort doppelt.
        if (!nativ || !ui || !selected || !pool) return;

        var legenden = wrap.querySelectorAll(".chip-ms-legend");
        var inst = {
            wrap: wrap,
            nativ: nativ,
            selected: selected,
            pool: pool,
            suche: wrap.querySelector(".chip-ms-search"),
            auswahlLabel: legenden[0] ? legenden[0].textContent : "Ausgewählt",
            vorratLabel: legenden[1] ? legenden[1].textContent : "Verfügbar",
            sortables: [],
        };

        selected.dataset.leer = wrap.dataset.leerText || "Nichts ausgewählt";
        pool.dataset.leer = "Keine weiteren Einträge";

        baueItems(inst);

        if (inst.suche) {
            inst.suche.placeholder = wrap.dataset.suchPlatzhalter || "Suchen …";
            inst.suche.hidden = nativ.options.length < Number(wrap.dataset.sucheAb || 8);
            inst.suche.addEventListener("input", function () {
                filtere(inst);
            });
        }

        // Das native Feld erst hier ausblenden -- per CSS waere es auch ohne JS weg.
        nativ.hidden = true;
        ui.hidden = false;

        verdrahteKlick(inst);
        verdrahteLongPress(inst);
        verdrahteDrag(inst);

        wrap.dataset.chipMsInit = "1";
        instanzen.push(inst);
    }

    function verdrahteKlick(inst) {
        inst.wrap.addEventListener("click", function (e) {
            if (inst.klickUnterdruecken) {
                // Der Klick, den ein Long-Press hinterherschickt.
                inst.klickUnterdruecken = false;
                e.stopPropagation();
                e.preventDefault();
                return;
            }
            var li = e.target.closest(".chip-ms-item");
            if (!li || !inst.wrap.contains(li)) return;
            e.stopPropagation(); // sonst schliesst der document-Handler das Popover mit
            verschiebe(inst, li, li.parentElement === inst.selected ? inst.pool : inst.selected);
        });
    }

    function verdrahteLongPress(inst) {
        var timer = null;
        var start = null;

        function abbrechen() {
            if (timer) {
                clearTimeout(timer);
                timer = null;
            }
            start = null;
        }

        inst.wrap.addEventListener(
            "touchstart",
            function (e) {
                var li = e.target.closest(".chip-ms-item");
                if (!li) return;
                var t = e.touches[0];
                start = { x: t.clientX, y: t.clientY };
                timer = setTimeout(function () {
                    timer = null;
                    // Zieht SortableJS auf einem Hybridgeraet bereits, hat die Geste
                    // schon einen Besitzer.
                    if (li.classList.contains("sortable-chosen")) return;
                    inst.klickUnterdruecken = true;
                    setTimeout(function () {
                        inst.klickUnterdruecken = false;
                    }, 400);
                    oeffnePicker(inst, li);
                }, LONGPRESS_MS);
            },
            { passive: true }
        );

        inst.wrap.addEventListener(
            "touchmove",
            function (e) {
                if (!timer || !start) return;
                var t = e.touches[0];
                if (
                    Math.abs(t.clientX - start.x) > BEWEGUNG_MAX ||
                    Math.abs(t.clientY - start.y) > BEWEGUNG_MAX
                ) {
                    abbrechen();
                }
            },
            { passive: true }
        );

        inst.wrap.addEventListener("touchend", abbrechen);
        inst.wrap.addEventListener("touchcancel", abbrechen);
    }

    function verdrahteDrag(inst) {
        // Sortable kommt von einem CDN und fehlt ohne Netz.
        if (typeof Sortable === "undefined") return;
        // Auf Touch-Geraeten ist der Long-Press der Weg; ein zusaetzliches Drag
        // wuerde dort mit dem Scrollen um dieselbe Geste streiten.
        if (window.matchMedia && !window.matchMedia("(pointer: fine)").matches) return;

        var gruppe = "chip-ms-" + ++gruppenZaehler; // pro Instanz eigen, sonst
        // liessen sich Solisten in die Dirigentenliste ziehen
        [inst.selected, inst.pool].forEach(function (ul) {
            inst.sortables.push(
                new Sortable(ul, {
                    group: gruppe,
                    animation: 120,
                    ghostClass: "sortable-ghost",
                    chosenClass: "sortable-chosen",
                    scroll: true,
                    delayOnTouchOnly: true,
                    delay: 400,
                    onAdd: function (evt) {
                        uebernehme(inst, evt.item, evt.to);
                    },
                })
            );
        });
    }

    // ------------------------------------------------------------- Einstieg

    function initAlle() {
        // Nach einem htmx-Swap sind Instanzen aus dem Dokument verschwunden.
        instanzen = instanzen.filter(function (inst) {
            if (document.contains(inst.wrap)) return true;
            inst.sortables.forEach(function (s) {
                s.destroy();
            });
            return false;
        });
        document.querySelectorAll("[data-chip-multiselect]").forEach(function (wrap) {
            if (wrap.dataset.chipMsInit) return;
            initEine(wrap);
        });
    }

    function init() {
        if (!document.querySelector("[data-chip-multiselect]")) return;
        initAlle();
    }

    document.addEventListener("click", function (e) {
        if (picker && !picker.contains(e.target)) schliessePicker();
    });
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") schliessePicker();
    });
    // Capture, damit auch das interne Scrollen der Offcanvas-Panels erfasst wird.
    window.addEventListener("scroll", schliessePicker, true);
    window.addEventListener("resize", schliessePicker);
    document.addEventListener("htmx:afterSwap", initAlle);

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
