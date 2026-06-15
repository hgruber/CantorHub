// Forum-Chat: Dubletten entfernen.
//
// Nachrichten landen über zwei Wege in #messages: die Antwort des Sende-Formulars
// und der 5-Sekunden-Poll (forum_get). Ein zum Sendezeitpunkt bereits laufender
// Poll kann dieselbe Nachricht ein zweites Mal einfügen (Poll/Send-Race). Nach
// jedem HTMX-Swap deshalb Knoten mit gleicher data-id entfernen — der erste
// (oberste) bleibt erhalten.
(function () {
    "use strict";

    function dedupe(container) {
        if (!container) return;
        const seen = new Set();
        container.querySelectorAll("[data-id]").forEach(function (el) {
            const id = el.getAttribute("data-id");
            if (seen.has(id)) {
                el.remove();
            } else {
                seen.add(id);
            }
        });
    }

    document.body.addEventListener("htmx:afterSwap", function (evt) {
        const messages = document.getElementById("messages");
        if (messages && (evt.target === messages || messages.contains(evt.target))) {
            dedupe(messages);
        }
    });
})();
