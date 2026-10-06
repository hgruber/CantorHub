/* Der Zeilen-Editor des Filters (siehe intern/filterbau.py).

   Eine Zeile ist eine Bedingung. Die sichtbaren Bedienelemente tragen keinen Namen --
   eine Mehrfachauswahl erzeugt je Wert einen Eintrag, damit geriete eine Zuordnung
   ueber gleichnamige Felder durcheinander. Stattdessen schreibt dieses Skript beim
   Absenden je Zeile einen versteckten <input name="f"> im Format
   <verbindung>:<feld>:<operator>:<wert,wert>. Jeder Einzelwert wird einzeln
   percent-kodiert, weil Komma und Doppelpunkt die Trennzeichen sind und ein
   getippter Name beide enthalten darf.

   Zwei Dinge, die nur hier stehen:

   * **Der Drei-Zustand-Schalter** bedient den Operator, wo das Feld ein Ja/Nein-Paar
     mit einem Einzelwert hat (Tempo, Tonart, Zusage) -- neben dem Wert. Die
     Ja/Nein-Felder ohne Wert sind feste Schalter unter der Kette, immer da und ohne
     Zeile; eine Mehrfachauswahl hat stattdessen „ist in / ist nicht in".
     Die Pille benutzt die CSS-Klassen von tri-toggle.js, wird aber
     von hier gesteuert -- jenes steigt ohne ein Geschwister .tri-toggle-select
     sofort aus. Das Operator-<select> bleibt dabei im DOM: dieses Skript liest es
     unbedingt, und die Pille setzt nur seinen Wert. Die Mitte („egal") schaltet die
     Zeile still, statt sie zu loeschen -- Feld und Werte bleiben stehen.
   * **Die Auswahllisten kommen als ein JSON-Buendel** (filter-optionen), nicht als
     Markup: es sind dreistellig viele Termine und Personen.

   Neue Zeilen entstehen durch Klonen der <template>-Vorlagen; die Chip-Mehrfachauswahl
   darin initialisiert chip-multiselect.js ueber den von ihm bereitgestellten Einstieg. */
(function () {
    "use strict";

    var baukasten = document.querySelector("[data-filter-baukasten]");
    if (!baukasten) return;

    var datenBeh = document.getElementById("filter-felder");
    if (!datenBeh) return;
    var felder = JSON.parse(datenBeh.textContent);
    var nachSchluessel = {};
    felder.forEach(function (feld) {
        nachSchluessel[feld.key] = feld;
    });

    var optionenBeh = document.getElementById("filter-optionen");
    var optionen = optionenBeh ? JSON.parse(optionenBeh.textContent) : {};

    var behaelter = baukasten.querySelector("[data-filter-zeilen]");
    var leerHinweis = baukasten.querySelector("[data-filter-leer]");
    var form = document.getElementById("filter-form");

    var SCHALTER_OFFSETS = { "0": "0px", "1": "14px", "2": "28px" };

    function zeilen() {
        return Array.prototype.slice.call(behaelter.querySelectorAll("[data-filter-zeile]"));
    }

    function vorlage(art) {
        var t = document.querySelector('[data-filter-vorlage="' + art + '"]');
        return t ? t.content : null;
    }

    function feldVon(zeile) {
        return zeile.querySelector("[data-filter-feld]").value;
    }

    function artVon(zeile) {
        var feld = nachSchluessel[feldVon(zeile)];
        return feld ? feld.art : null;
    }

    /* ------------------------------------------------------------ Operator */

    /* Die Operatoren haengen am Feld: „Gruppen" kennt „ist in"/„ist nicht in",
       „Name" dagegen „enthaelt"/„beginnt mit"/… Wo ein Ja/Nein-Paar einen Einzelwert
       hat (Tempo, Tonart, Zusage), tritt die Pille neben dem Wert an die Stelle der
       Auswahlliste. */
    function setzeOperatoren(zeile) {
        var feld = nachSchluessel[feldVon(zeile)];
        if (!feld) return;
        var bereich = zeile.querySelector("[data-filter-schalterplatz]");
        var auswahl = zeile.querySelector("[data-filter-operator]");
        var vorher = auswahl.value;
        auswahl.textContent = "";
        auswahl.hidden = feld.schalter;

        feld.operatoren.forEach(function (op) {
            var option = document.createElement("option");
            option.value = op.key;
            option.textContent = op.label;
            if (op.nicht) option.dataset.nicht = "1";
            auswahl.appendChild(option);
        });
        if (vorher && feld.operatoren.some(function (op) { return op.key === vorher; })) {
            auswahl.value = vorher;
        }

        var alt = bereich.querySelector("[data-filter-schalter]");
        if (alt) alt.remove();
        if (!feld.schalter) return;

        var pille = document.createElement("span");
        pille.className = "tri-toggle filter-zeile-schalter";
        pille.dataset.filterSchalter = "";
        pille.setAttribute("role", "group");
        pille.setAttribute("aria-label", "Bedingung ein-, aus- oder stillschalten");
        pille.innerHTML =
            '<span class="tri-toggle-thumb"></span>' +
            '<button type="button" class="tri-toggle-seg" data-val="' + feld.operatoren[1].key +
            '" title="' + feld.operatoren[1].label + '">&#x2717;</button>' +
            '<button type="button" class="tri-toggle-seg" data-val="egal" title="Egal">&#x00b7;</button>' +
            '<button type="button" class="tri-toggle-seg" data-val="' + feld.operatoren[0].key +
            '" title="' + feld.operatoren[0].label + '">&#x2713;</button>';
        bereich.appendChild(pille);
        zeile.dataset.egal = "";
        zeichneSchalter(zeile);
    }

    /* Die Pille spiegelt den Operatorwert; „egal" hat keinen Operator und steht in
       der Mitte. */
    function zeichneSchalter(zeile) {
        var pille = zeile.querySelector("[data-filter-schalter]");
        if (!pille) return;
        var auswahl = zeile.querySelector("[data-filter-operator]");
        var feld = nachSchluessel[feldVon(zeile)];
        var stelle = zeile.dataset.egal === "1" ? 1
            : (auswahl.value === (feld ? feld.operatoren[0].key : "") ? 2 : 0);
        var thumb = pille.querySelector(".tri-toggle-thumb");
        if (thumb) thumb.style.transform = "translateX(" + SCHALTER_OFFSETS[stelle] + ")";
        pille.dataset.value = stelle === 1 ? "unknown" : (stelle === 2 ? "true" : "false");
        pille.querySelectorAll(".tri-toggle-seg").forEach(function (seg) {
            seg.classList.toggle("selected", seg.dataset.val === auswahl.value && stelle !== 1);
        });
    }

    /* ------------------------------------------------------------- Werte */

    function fuelleAuswahl(auswahl, liste, vorauswahl) {
        var gewuenscht = (vorauswahl || "").split(",");
        auswahl.textContent = "";
        (liste || []).forEach(function (eintrag) {
            var option = document.createElement("option");
            option.value = eintrag.wert;
            option.textContent = eintrag.label;
            if (gewuenscht.indexOf(eintrag.wert) !== -1) option.selected = true;
            auswahl.appendChild(option);
        });
    }

    /* Die Auswahllisten der Zeile aus dem Buendel fuellen. Die Antwort der Zusage hat
       einen eigenen Schluessel, weil eine Zeile nur einen Feldnamen hat. */
    function setzeAuswahllisten(zeile) {
        var feld = feldVon(zeile);
        var art = artVon(zeile);
        if (art === "mehrfach") {
            var nativ = zeile.querySelector(".chip-ms-native");
            var ziel = zeile.querySelector("[data-filter-werte]");
            if (nativ && !nativ.options.length) {
                fuelleAuswahl(nativ, optionen[feld], ziel.dataset.werte);
            }
            return;
        }
        if (art === "auswahl") {
            var auswahl = zeile.querySelector("[data-filter-auswahl]");
            if (auswahl && !auswahl.options.length) {
                fuelleAuswahl(auswahl, optionen[feld], auswahl.dataset.werte);
            }
            return;
        }
        if (art === "zusage") {
            var termin = zeile.querySelector("[data-filter-termin]");
            if (termin && !termin.options.length) {
                fuelleAuswahl(termin, optionen[feld], termin.dataset.werte);
            }
            var antwort = zeile.querySelector("[data-filter-antwort]");
            if (antwort && !antwort.options.length) {
                fuelleAuswahl(antwort, optionen[feld + "-antwort"], antwort.dataset.werte);
            }
        }
    }

    /* chip-multiselect.js laedt nach dieser Datei (der Block steht im <head> vor ihm),
       steht aber laengst, bevor hier geklickt wird. */
    function initialisiereChips() {
        ohneNamen();
        if (window.chipMultiSelectInitAlle) window.chipMultiSelectInitAlle();
    }

    /* Die Werte-Widgets sind reine Bedienoberflaeche: den Zustand traegt der versteckte
       <input name="f">. Ohne diese Zeile stuenden die Werte aller Zeilen unter einem
       Namen in der Adresse, und aus mehreren Zeilen vermischt. */
    function ohneNamen() {
        behaelter.querySelectorAll(
            ".chip-ms-native, [data-filter-text], [data-filter-datum], " +
            "[data-filter-auswahl], [data-filter-termin], [data-filter-antwort]"
        ).forEach(function (element) {
            element.removeAttribute("name");
        });
    }

    /* Das Werte-Widget wechselt mit dem Feld -- nicht erst mit der Art: Solist und
       Dirigent sind beide „mehrfach", haben aber eigene Eintraege und Beschriftungen.
       Die Vorlage ist unbenutztes Markup; eine schon initialisierte Chip-Liste zu
       klonen ergaebe kaputte Eintraege. */
    function setzeWidget(zeile) {
        var feld = feldVon(zeile);
        var ziel = zeile.querySelector("[data-filter-werte]");
        if (ziel.dataset.feld === feld) return;
        var inhalt = vorlage("feld-" + feld);
        if (!inhalt) return;
        ziel.textContent = "";
        ziel.appendChild(inhalt.cloneNode(true));
        ziel.dataset.feld = feld;
        ziel.dataset.werte = "";
        setzeAuswahllisten(zeile);
        initialisiereChips();
    }

    /* Liest die Werte einer Zeile. Je Wertart woanders her -- „ohne" hat gar keine
       und „egal" will keine: dort traegt der Operator die Aussage. */
    function werteVon(zeile) {
        var art = artVon(zeile);
        if (art === "ohne") return [];
        if (art === "text") {
            var text = zeile.querySelector("[data-filter-text]");
            var eingabe = text ? text.value.trim() : "";
            return eingabe ? [eingabe] : [];
        }
        if (art === "datum") {
            var datum = zeile.querySelector("[data-filter-datum]");
            return datum && datum.value ? [datum.value] : [];
        }
        if (art === "auswahl") {
            var auswahl = zeile.querySelector("[data-filter-auswahl]");
            return auswahl && auswahl.value ? [auswahl.value] : [];
        }
        if (art === "zusage") {
            // Feste Reihenfolge: Termin, dann Antwort -- nicht die DOM-Reihenfolge.
            var t = zeile.querySelector("[data-filter-termin]");
            var a = zeile.querySelector("[data-filter-antwort]");
            if (!t || !t.value || !a || !a.value) return [];
            return [t.value, a.value];
        }
        var chips = zeile.querySelector("[data-filter-werte] .chip-ms-native");
        if (!chips) return [];
        return Array.prototype.map.call(chips.options, function (option) {
            return option.selected ? option.value : null;
        }).filter(function (wert) { return wert; });
    }

    function aktualisiere(zeile) {
        var art = artVon(zeile);
        // „egal" ist kein Wert, sondern die stille Zeile: sie wird gar nicht gesendet.
        var still = zeile.dataset.egal === "1";
        var werte = still ? [] : werteVon(zeile);
        var eingabe = zeile.querySelector("[data-filter-wert]");
        if (!still && (werte.length || art === "ohne")) {
            eingabe.value = [
                zeile.querySelector("[data-filter-verbindung]").value || "und",
                feldVon(zeile),
                zeile.querySelector("[data-filter-operator]").value,
                werte.map(encodeURIComponent).join(","),
            ].join(":");
            eingabe.disabled = false;
        } else {
            eingabe.value = "";
            eingabe.disabled = true;
        }

        // Roter Ausschluss, sobald der Operator verneint -- dieselbe Variante, die
        // der feste „Nicht in Gruppen"-Filter schon trug.
        var operator = zeile.querySelector("[data-filter-operator] option:checked");
        var wurzel = zeile.querySelector(".chip-ms");
        if (wurzel) {
            wurzel.classList.toggle("chip-ms--exclude", !!(operator && operator.dataset.nicht));
        }
        zeichneSchalter(zeile);
    }

    /* Nur die erste Zeile traegt keinen Konnektor -- davor ist nichts, womit sie sich
       verknuepfen koennte. */
    function nummeriere() {
        zeilen().forEach(function (zeile, i) {
            zeile.querySelector("[data-filter-verbindung]").hidden = i === 0;
        });
        leerHinweis.hidden = zeilen().length > 0;
    }

    function neueZeile() {
        var inhalt = vorlage("zeile");
        if (!inhalt) return;
        var zeile = inhalt.cloneNode(true).firstElementChild;
        behaelter.appendChild(zeile);
        setzeOperatoren(zeile);
        setzeWidget(zeile);
        setzeAuswahllisten(zeile);
        // Die Vorlage bringt eine uninitialisierte Chip-Liste mit; das muss auch dann
        // laufen, wenn die Feldart dieselbe bleibt und setzeWidget nichts tauscht.
        initialisiereChips();
        // Eine leere Zeile wird gleich stillgelegt, sonst stuende ein f ohne Werte in
        // der Adresse.
        aktualisiere(zeile);
        nummeriere();
    }

    baukasten.querySelector("[data-filter-hinzufuegen]").addEventListener("click", neueZeile);

    behaelter.addEventListener("change", function (e) {
        var zeile = e.target.closest("[data-filter-zeile]");
        if (!zeile) return;
        if (e.target.matches("[data-filter-feld]")) {
            setzeOperatoren(zeile);
            setzeWidget(zeile);
            setzeAuswahllisten(zeile);
        }
        aktualisiere(zeile);
    });
    // Text- und Datumsfelder melden sich beim Tippen, nicht erst beim Verlassen.
    behaelter.addEventListener("input", function (e) {
        if (!e.target.matches("[data-filter-text], [data-filter-datum]")) return;
        var zeile = e.target.closest("[data-filter-zeile]");
        if (zeile) aktualisiere(zeile);
    });

    // Die Segmente der Pille melden sich nicht als change -- ein eigener Handler.
    behaelter.addEventListener("click", function (e) {
        var weg = e.target.closest("[data-filter-weg]");
        if (weg) {
            weg.closest("[data-filter-zeile]").remove();
            nummeriere();
            return;
        }
        var seg = e.target.closest("[data-filter-schalter] .tri-toggle-seg");
        if (!seg) return;
        var zeile = seg.closest("[data-filter-zeile]");
        var wert = seg.dataset.val;
        if (wert === "egal") {
            zeile.dataset.egal = "1";
        } else {
            zeile.dataset.egal = "";
            zeile.querySelector("[data-filter-operator]").value = wert;
        }
        aktualisiere(zeile);
    });

    // Die Chip-Listen melden ihre Verschiebungen nicht als change-Event; der Zustand
    // wird deshalb unmittelbar vor dem Absenden aus den Zeilen gelesen.
    if (form) {
        form.addEventListener("submit", function () {
            zeilen().forEach(aktualisiere);
            setzeMarker();
        });
    }

    /* Steht ein fester Schalter mit Marker auf „egal", geht der Marker mit -- sonst
       haengte der Server die Zugangs-Vorgabe sofort wieder an, und „egal" bei
       „Zugang" taete nichts. */
    function setzeMarker() {
        baukasten.querySelectorAll("[data-filter-fest]").forEach(function (fest) {
            var marker = fest.dataset.marker;
            if (!marker || !fest.querySelector("[data-filter-fest-wert]").disabled) return;
            var teile = marker.split("=");
            if (form.querySelector('input[name="' + teile[0] + '"]')) return;
            var traeger = document.createElement("input");
            traeger.type = "hidden";
            traeger.name = teile[0];
            traeger.value = teile[1];
            baukasten.appendChild(traeger);
        });
    }

    /* Die festen Schalter: je ein versteckter <input name="f">, auf „egal"
       stillgelegt. Eine Zeile gibt es dafuer nicht -- sie stehen immer da. */
    var FEST_STELLEN = { nein: 0, egal: 1, ja: 2 };
    baukasten.addEventListener("click", function (e) {
        var seg = e.target.closest("[data-filter-fest-schalter] .tri-toggle-seg");
        if (!seg) return;
        var fest = seg.closest("[data-filter-fest]");
        var pille = seg.closest("[data-filter-fest-schalter]");
        var eingabe = fest.querySelector("[data-filter-fest-wert]");
        var stellung = seg.dataset.val;
        if (stellung === "egal") {
            eingabe.value = "";
            eingabe.disabled = true;
        } else {
            eingabe.value = ["und", fest.dataset.feld, fest.dataset[stellung], ""].join(":");
            eingabe.disabled = false;
        }
        var stelle = FEST_STELLEN[stellung];
        pille.querySelector(".tri-toggle-thumb").style.transform =
            "translateX(" + SCHALTER_OFFSETS[stelle] + ")";
        pille.dataset.value = stelle === 1 ? "unknown" : (stelle === 2 ? "true" : "false");
        pille.querySelectorAll(".tri-toggle-seg").forEach(function (s) {
            s.classList.toggle("selected", s === seg);
        });
    });

    zeilen().forEach(function (zeile) {
        setzeAuswahllisten(zeile);
        aktualisiere(zeile);
    });
    nummeriere();
    initialisiereChips();
})();
