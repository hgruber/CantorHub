// Gruppen-Berechtigungen: das Radio "Alle Mitglieder / Nur bestimmte Gruppen"
// blendet die Chip-Mehrfachauswahl ein, darunter steht, welche Mitglieder die
// gewaehlten Gruppen zusammen umfassen.
//
// Gemeinsam genutzt von folder_berechtigungen (read/write/delete),
// artikel_berechtigungen (read/edit) und forum_zugriff (read). Die Abschnitte
// werden ueber die id-Konvention "<abschnitt>-groups" / "<abschnitt>-members"
// gefunden, die Seite muss also nichts konfigurieren.
(function () {
    "use strict";

    var groupMembers = {};

    function updateChips(section, zeigen) {
        var chips = document.getElementById(section + "-members");
        if (!chips) return;
        chips.textContent = "";
        if (!zeigen) {
            chips.setAttribute("hidden", "");
            return;
        }
        var groupsEl = document.getElementById(section + "-groups");
        if (!groupsEl) return;

        // Gelesen wird der Auswahlzustand des <select>, nicht die Chip-Oberflaeche:
        // chip-multiselect.js setzt option.selected, das <select> bleibt die
        // Quelle der Wahrheit.
        var namen = new Set();
        groupsEl.querySelectorAll("select option:checked").forEach(function (opt) {
            (groupMembers[opt.value] || []).forEach(function (n) {
                namen.add(n);
            });
        });

        if (namen.size === 0) {
            chips.setAttribute("hidden", "");
            return;
        }
        chips.removeAttribute("hidden");
        Array.from(namen)
            .sort()
            .forEach(function (name) {
                var span = document.createElement("span");
                span.className = "member-chip";
                span.textContent = name;
                chips.appendChild(span);
            });
    }

    // Wird aus dem Markup per onchange aufgerufen (wie toggle() in intern.js).
    window.toggleGroups = function (section, value) {
        var el = document.getElementById(section + "-groups");
        if (!el) return;
        if (value === "restricted") {
            el.removeAttribute("hidden");
        } else {
            el.setAttribute("hidden", "");
        }
        updateChips(section, value === "restricted");
    };

    function init() {
        var daten = document.getElementById("group-members");
        if (!daten) return;
        groupMembers = JSON.parse(daten.textContent);

        document.querySelectorAll('[id$="-groups"]').forEach(function (groupsEl) {
            var section = groupsEl.id.replace("-groups", "");
            updateChips(section, !groupsEl.hasAttribute("hidden"));
            // Ein Listener am Container genuegt: das change-Event des <select>
            // bubbelt, egal ob es aus der Chip-Oberflaeche oder dem nativen Feld kommt.
            groupsEl.addEventListener("change", function () {
                updateChips(section, true);
            });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
