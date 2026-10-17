// ── Bearbeiten/Vorschau (Artikel-Editor) ──────────────────
// Die Vorschau rendert der Server (article_preview) mit derselben Wiki-Syntax
// wie die Artikelansicht; gespeichert wird dabei nichts. Das Textfeld bleibt
// im Formular, es wird nur ausgeblendet. Die Vorschau ist zum Ansehen, nicht
// zum Bedienen (inert, siehe artikel.html).
(function initWikiVorschau() {
  var modus = document.querySelector(".ae-modus[data-vorschau-url]");
  if (!modus) return;
  var editor = modus.closest(".article-editor");
  var textfeld = editor.querySelector(".ae-body .wiki textarea");
  var schreibflaeche = textfeld.closest(".wiki");
  var vorschau = editor.querySelector(".ae-vorschau");
  var inhalt = vorschau.querySelector(".ae-vorschau-inhalt");
  var hilfe = editor.querySelector(".ae-help");
  var anfrage = 0;

  function setzeModus(name) {
    var istVorschau = name === "vorschau";
    modus.querySelectorAll(".ae-modus-seg").forEach(function (seg) {
      seg.setAttribute("aria-pressed", seg.dataset.modus === name ? "true" : "false");
    });
    schreibflaeche.hidden = istVorschau;
    vorschau.hidden = !istVorschau;
    if (hilfe) hilfe.hidden = istVorschau;
    if (!istVorschau) textfeld.focus();
  }

  function ladeVorschau() {
    var nummer = ++anfrage;
    var daten = new FormData();
    daten.append("text", textfeld.value);
    daten.append("csrfmiddlewaretoken", getCsrfToken());
    inhalt.textContent = "Vorschau wird geladen …";
    fetch(modus.dataset.vorschauUrl, { method: "POST", body: daten, credentials: "same-origin" })
      .then(function (antwort) {
        if (!antwort.ok) throw new Error(antwort.status);
        return antwort.text();
      })
      .then(function (html) {
        // Ein schneller Wechsel zurück und wieder hin überholt die alte Anfrage.
        if (nummer === anfrage) inhalt.innerHTML = html;
      })
      .catch(function () {
        if (nummer === anfrage) inhalt.textContent = "Die Vorschau konnte nicht geladen werden.";
      });
  }

  modus.addEventListener("click", function (e) {
    var seg = e.target.closest(".ae-modus-seg");
    if (!seg || seg.getAttribute("aria-pressed") === "true") return;
    if (seg.dataset.modus === "vorschau") ladeVorschau();
    setzeModus(seg.dataset.modus);
  });
})();
