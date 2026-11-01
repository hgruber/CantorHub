/* Überlaufmenü der Kopfleiste.

   Unter 768 px bleiben nur die Aktionen mit ``data-topbar-bleibt`` in der
   Leiste; alle anderen wandern in ein „…"-Menü, das sie **mit Beschriftung**
   zeigt — auf dem Touchgerät gibt es keinen Tooltip, ein nacktes Icon ist dort
   nicht zu deuten. Die Originale bleiben im DOM und werden nur versteckt:
   ihre ``onclick``-Handler, Formulare und Django-URLs bleiben damit
   unangetastet. Über der Grenze wird alles zurückgebaut, damit ein Drehen des
   Geräts oder ein breites Fenster wieder die volle Leiste zeigt.

   Das Menü nutzt die Bausteine des Download-Menüs (``.dl-trigger`` /
   ``.dl-menu`` / ``.dl-item``) und erbt damit Position, Schatten und
   Tastaturverhalten. */
(function () {
    "use strict";

    var leiste = document.querySelector(".topbar-actions");
    if (!leiste) return;

    var GRENZE = 768;
    var menue = null;
    var versteckt = [];

    function schliessen() {
        if (!menue) return;
        var liste = menue.querySelector(".dl-menu");
        var knopf = menue.querySelector(".dl-trigger-btn");
        if (liste) liste.classList.remove("open");
        if (knopf) knopf.setAttribute("aria-expanded", "false");
    }

    function zuruecksetzen() {
        versteckt.forEach(function (a) { a.hidden = false; });
        versteckt = [];
        if (menue) {
            menue.remove();
            menue = null;
        }
    }

    function eintrag(a) {
        var item = document.createElement("a");
        item.className = "dl-item";
        item.href = a.getAttribute("href") || "#";
        var klick = a.getAttribute("onclick");
        if (klick) item.setAttribute("onclick", klick);

        var ikone = document.createElement("span");
        ikone.className = "dl-item-icon";
        ikone.innerHTML = a.innerHTML;
        ikone.setAttribute("aria-hidden", "true");

        var koerper = document.createElement("span");
        koerper.className = "dl-item-body";
        var titel = document.createElement("span");
        titel.className = "dl-item-title";
        titel.textContent = a.title || a.getAttribute("aria-label") || "";
        koerper.appendChild(titel);

        item.appendChild(ikone);
        item.appendChild(koerper);
        item.addEventListener("click", schliessen);
        return item;
    }

    function bauen(aktionen) {
        var trigger = document.createElement("div");
        trigger.className = "dl-trigger topbar-mehr";

        var knopf = document.createElement("button");
        knopf.type = "button";
        knopf.className = "dl-trigger-btn";
        knopf.title = "Weitere Aktionen";
        knopf.setAttribute("aria-label", "Weitere Aktionen");
        knopf.setAttribute("aria-haspopup", "true");
        knopf.setAttribute("aria-expanded", "false");
        knopf.innerHTML =
            '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">' +
            '<circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="19" cy="12" r="1.7"/></svg>';

        var liste = document.createElement("div");
        liste.className = "dl-menu";
        aktionen.forEach(function (a) { liste.appendChild(eintrag(a)); });

        knopf.addEventListener("click", function (e) {
            e.stopPropagation();
            var offen = liste.classList.toggle("open");
            knopf.setAttribute("aria-expanded", offen ? "true" : "false");
        });

        trigger.appendChild(knopf);
        trigger.appendChild(liste);
        leiste.appendChild(trigger);
        menue = trigger;
    }

    function anpassen() {
        zuruecksetzen();
        if (window.innerWidth > GRENZE) return;

        var kandidaten = Array.prototype.filter.call(
            leiste.querySelectorAll(":scope > a[title]"),
            function (a) { return !a.hasAttribute("data-topbar-bleibt"); }
        );
        /* Ein Menü mit einem einzigen Eintrag ist mehr Klick als Nutzen. */
        if (kandidaten.length < 2) return;

        kandidaten.forEach(function (a) {
            a.hidden = true;
            versteckt.push(a);
        });
        bauen(kandidaten);
    }

    document.addEventListener("click", function (e) {
        if (menue && menue.querySelector(".dl-menu").classList.contains("open") &&
            !menue.contains(e.target)) {
            schliessen();
        }
    });
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") schliessen();
    });

    var laeuft = null;
    window.addEventListener("resize", function () {
        clearTimeout(laeuft);
        laeuft = setTimeout(anpassen, 150);
    });

    anpassen();
})();
