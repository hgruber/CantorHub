// ── Syntax-Hilfe zum Anklicken (Artikel-Editor) ───────────
// Jede Pille der Leiste trägt ihr Muster in data-einfuegen; ein Klick setzt es
// an der Cursorposition ein und markiert den Platzhalter. Geschrieben wird die
// Wiki-Syntax dadurch nicht anders — sie muss nur nicht mehr abgetippt werden.
(function initWikiEinfuegen() {
  // Der Platzhalter im Muster: ${Titel} wird zu "Titel" und danach markiert.
  var PLATZHALTER = /\$\{([^}]*)\}/;

  // Reine Textfunktion — kein DOM, damit sie sich einzeln prüfen lässt.
  // Liefert {text, start, ende}: den neuen Inhalt und die neue Auswahl.
  function einfuegen(text, start, ende, muster, optionen) {
    optionen = optionen || {};
    var markiert = text.substring(start, ende);

    // Umschließen: die Markierung wird zum Inhalt des Platzhalters.
    if (optionen.umschliessen && markiert) {
      muster = muster.replace(PLATZHALTER, markiert);
    }

    // Blockmuster gehören an den Zeilenanfang; steht dort schon etwas, kommt
    // ein Umbruch davor.
    var vorsatz = "";
    if (optionen.block) {
      var zeilenanfang = text.lastIndexOf("\n", start - 1) + 1;
      if (text.substring(zeilenanfang, start).trim() !== "") vorsatz = "\n";
    }

    var eingefuegt = vorsatz + muster;
    var treffer = PLATZHALTER.exec(eingefuegt);
    if (treffer) {
      eingefuegt =
        eingefuegt.substring(0, treffer.index) +
        treffer[1] +
        eingefuegt.substring(treffer.index + treffer[0].length);
    }

    var auswahlStart = start + (treffer ? treffer.index : eingefuegt.length);
    var auswahlEnde = auswahlStart + (treffer ? treffer[1].length : 0);

    return {
      text: text.substring(0, start) + eingefuegt + text.substring(ende),
      start: auswahlStart,
      ende: auswahlEnde,
    };
  }

  // Für die Prüfung von außen (node) und für andere Skripte.
  window.wikiEinfuegen = einfuegen;

  function textarea(knopf) {
    var editor = knopf.closest(".article-editor") || document;
    return editor.querySelector(".wiki textarea");
  }

  function aufKnopf(knopf) {
    var ta = textarea(knopf);
    if (!ta) return;

    var muster = knopf.dataset.einfuegen || "";
    if (knopf.dataset.geruest === "abstimmung" && window.abstimmungGeruest) {
      // Das Gerüst kommt mit dem Ende in zwei Wochen aus abstimmung.js; der
      // erste „Titel“ darin ist der Titelplatz und wird markiert.
      muster = window.abstimmungGeruest().replace("Titel", "${Titel}");
    }

    var ergebnis = einfuegen(ta.value, ta.selectionStart, ta.selectionEnd, muster, {
      block: knopf.hasAttribute("data-block"),
      umschliessen: knopf.hasAttribute("data-umschliessen"),
    });

    ta.value = ergebnis.text;
    ta.focus();
    ta.setSelectionRange(ergebnis.start, ergebnis.ende);

    // Der Medienplayer braucht hinter dem Dateinamen noch |Titel. Die
    // Dateisuche in intern.js verbraucht den Merker, sobald sie den Verweis
    // schließt.
    if (knopf.dataset.suffix) {
      ta.dataset.wikiSuffix = knopf.dataset.suffix;
    } else {
      delete ta.dataset.wikiSuffix;
    }

    // Darauf hören die Dateisuche und der Abstimmungs-Helfer.
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }

  document.addEventListener("click", function (e) {
    var knopf = e.target.closest(".ae-cheat");
    if (knopf) aufKnopf(knopf);
  });
})();
