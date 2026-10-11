// ── Kontextmenü der eingebetteten Vorschaubilder (Artikelansicht) ─────────
// Ein Klick auf ein Vorschaubild öffnet statt der Datei ein Menü. Herunterladen
// und Anzeigen gibt es für jeden Leser; mit Schreibrecht für den Artikel
// (data-datei-menue="1") fragt das Menü /intern/datei/<pk>/aktionen/, was
// außerdem geht: Ordner anzeigen, Referenz erzeugen, Datei löschen.
// Aussehen und Platzierung wie das Zeilenmenü im Ordner-Browser (.context-menu).
(function initWikiDateimenue() {
  var wiki = document.querySelector(".wiki[data-artikel]");
  if (!wiki) return;
  var artikel = wiki.dataset.artikel;
  var schreiben = wiki.dataset.dateiMenue === "1";

  var S = 'xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
  var ICON = {
    herunterladen: "<svg " + S + '><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
    anzeigen:      "<svg " + S + '><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
    ordner:        "<svg " + S + '><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
    verknuepfen:   "<svg " + S + '><path d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
    loeschen:      "<svg " + S + '><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>',
  };

  var menuEl = null;
  function schliessen() {
    if (menuEl) { menuEl.remove(); menuEl = null; }
  }

  // eintraege: [{label, icon, title, danger, action} | {sep: true}]
  function zeigen(kopf, eintraege, x, y, liste) {
    schliessen();
    menuEl = document.createElement("div");
    menuEl.className = "context-menu" + (liste ? " context-menu-liste" : "");
    var k = document.createElement("div");
    k.className = "context-menu-header";
    k.textContent = kopf;
    menuEl.appendChild(k);
    eintraege.forEach(function (it) {
      if (it.sep) {
        var s = document.createElement("div");
        s.className = "context-menu-sep";
        menuEl.appendChild(s);
        return;
      }
      var b = document.createElement("button");
      b.type = "button";
      b.className = "context-menu-item" + (it.danger ? " danger" : "");
      if (it.title) b.title = it.title;
      if (it.icon) b.insertAdjacentHTML("beforeend", it.icon);
      b.appendChild(document.createTextNode(it.label));
      b.addEventListener("click", function () { schliessen(); it.action(); });
      menuEl.appendChild(b);
    });
    document.body.appendChild(menuEl);
    var rect = menuEl.getBoundingClientRect();
    menuEl.style.left = Math.max(4, Math.min(x, window.innerWidth - rect.width - 4)) + "px";
    menuEl.style.top = Math.max(4, Math.min(y, window.innerHeight - rect.height - 4)) + "px";
  }

  function formularSenden(action, felder) {
    var f = document.createElement("form");
    f.method = "POST";
    f.action = action;
    felder.csrfmiddlewaretoken = getCsrfToken();
    Object.keys(felder).forEach(function (name) {
      var inp = document.createElement("input");
      inp.type = "hidden"; inp.name = name; inp.value = felder[name];
      f.appendChild(inp);
    });
    document.body.appendChild(f);
    f.submit();
  }

  function loeschen(id, name, warnungen) {
    // Dass dieser Artikel die Datei verwendet, weiß man — der Verweis geht ja mit.
    warnungen = warnungen
      .filter(function (w) { return w.url !== window.location.pathname; })
      .map(function (w) { return w.label; });
    var frage = "„" + name + "“ löschen und den Verweis aus diesem Artikel entfernen?";
    if (warnungen.length) {
      frage += "\n\nDie Datei wird auch hier verwendet:\n" +
        warnungen.map(function (w) { return "• " + w; }).join("\n");
    }
    if (!confirm(frage)) return;
    var body = new FormData();
    body.append("datei", id);
    fetch("/intern/artikel/" + encodeURIComponent(artikel) + "/datei-loeschen/", {
      method: "POST",
      headers: { "X-CSRFToken": getCsrfToken() },
      body: body,
    }).then(function (r) {
      if (r.ok) window.location.reload();
      else alert("Löschen fehlgeschlagen.");
    });
  }

  function zieleZeigen(id, name, ziele, x, y) {
    zeigen("Referenz von „" + name + "“ ablegen in …", ziele.map(function (z) {
      return {
        label: z.path,
        icon: ICON.ordner,
        action: function () {
          formularSenden("/intern/ordner/verknuepfen/", {
            item: "File:" + id,
            target_pk: z.id,
            referer_pk: 0,
            next: window.location.pathname,
          });
        },
      };
    }), x, y, true);
  }

  wiki.addEventListener("click", function (e) {
    var img = e.target.closest(".wiki-figure[data-datei-id] img");
    if (!img) return;
    e.preventDefault();
    var fig = img.closest(".wiki-figure");
    var url = img.closest("a").href;
    var id = fig.dataset.dateiId;
    var name = fig.dataset.dateiName;
    var x = e.clientX, y = e.clientY;

    var eintraege = [
      { label: "Datei herunterladen", icon: ICON.herunterladen, action: function () {
        var a = document.createElement("a");
        a.href = url; a.download = name;
        document.body.appendChild(a); a.click(); a.remove();
      }},
      { label: "Datei anzeigen", icon: ICON.anzeigen, action: function () {
        window.open(url, "_blank", "noopener");
      }},
    ];
    if (!schreiben) { zeigen(name, eintraege, x, y); return; }

    fetch("/intern/datei/" + id + "/aktionen/")
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; })
      .then(function (d) {
        if (d) {
          var verwaltung = [];
          if (d.ordner) {
            verwaltung.push({ label: "Enthaltenen Ordner anzeigen", icon: ICON.ordner,
              title: d.ordner.pfad,
              action: function () { window.location.href = d.ordner.url; } });
          }
          if (d.ziele && d.ziele.length) {
            verwaltung.push({ label: "Referenz erzeugen …", icon: ICON.verknuepfen,
              title: "Dieselbe Datei erscheint zusätzlich im Zielordner — Änderungen wirken überall",
              action: function () { zieleZeigen(id, name, d.ziele, x, y); } });
          }
          if (verwaltung.length) eintraege = eintraege.concat([{ sep: true }], verwaltung);
          if (d.darf_loeschen) {
            eintraege.push({ sep: true });
            eintraege.push({ label: "Datei löschen", icon: ICON.loeschen, danger: true,
              action: function () { loeschen(id, name, d.warnungen || []); } });
          }
        }
        zeigen(name, eintraege, x, y);
      });
  });

  document.addEventListener("mousedown", function (e) {
    if (menuEl && !menuEl.contains(e.target)) schliessen();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") schliessen();
  });
  window.addEventListener("resize", schliessen);
})();
