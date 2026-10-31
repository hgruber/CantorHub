// Forum-Chat: Dubletten entfernen + Emoji-Reaktionen (XEP-0444).
//
// Nachrichten landen über zwei Wege in #messages: die Antwort des Sende-Formulars
// und der 5-Sekunden-Poll (forum_get). Ein zum Sendezeitpunkt bereits laufender
// Poll kann dieselbe Nachricht ein zweites Mal einfügen (Poll/Send-Race). Nach
// jedem HTMX-Swap deshalb Knoten mit gleicher data-id entfernen — der erste
// (oberste) bleibt erhalten.
//
// Reaktionen werden ausschließlich hier gerendert (eine einzige Render-Quelle):
// ein eigener Poll (forum_reactions) liefert den Stand als JSON, Klicks senden an
// forum_react. So bleiben auch eingehende XMPP-Reaktionen sichtbar.
(function () {
    "use strict";

    var QUICK_EMOJIS = ["👍", "❤️", "😂", "🎉", "😮", "😢", "🙏", "👏"];
    // Kuratierte Auswahl fuer PC-Benutzer, denen keine Handytastatur Emojis anbietet:
    // Reaktions-Picker („Mehr“) und Knopf am Nachrichtenfeld teilen sie.
    var EMOJI_GRUPPEN = [
        { titel: "Gesichter", emojis: ["😀", "😃", "😄", "😁", "😆", "😅", "🤣", "😂",
            "🙂", "😉", "😊", "😇", "🥰", "😍", "🤩", "😘", "😋", "😜", "🤪", "🤗",
            "🤔", "🤫", "😐", "🙄", "😏", "😬", "😌", "😴", "🥳", "😎", "🤓", "😮",
            "😲", "🥺", "😢", "😭", "😱", "😤", "😡", "🤯"] },
        { titel: "Gesten & Herzen", emojis: ["👍", "👎", "👌", "✌️", "🤞", "👋", "👏",
            "🙌", "🙏", "💪", "🤝", "✋", "❤️", "🧡", "💛", "💚", "💙", "💜", "🖤",
            "💖"] },
        { titel: "Musik & Feiern", emojis: ["🎵", "🎶", "🎤", "🎹", "🎸", "🥁", "🎺",
            "🎻", "🎼", "🎧", "🎉", "🎊", "🥂", "🍾", "🎂", "🎁", "⭐", "✨", "🔥",
            "🏆"] },
        { titel: "Sonstiges", emojis: ["☀️", "🌧️", "❄️", "🌈", "🌸", "☕", "🍰", "🍕",
            "🚗", "🚆", "📅", "⏰", "📍", "📣", "✅", "❌", "❓", "❗", "💡", "👀"] },
    ];
    var POLL_MS = 5000;

    function dedupe(container) {
        if (!container) return;
        var seen = new Set();
        container.querySelectorAll("[data-id]").forEach(function (el) {
            var id = el.getAttribute("data-id");
            if (seen.has(id)) {
                el.remove();
            } else {
                seen.add(id);
            }
        });
    }

    document.body.addEventListener("htmx:afterSwap", function (evt) {
        var messages = document.getElementById("messages");
        if (messages && (evt.target === messages || messages.contains(evt.target))) {
            dedupe(messages);
        }
    });

    var layout = document.querySelector(".forum-layout");
    if (!layout || !layout.dataset.reactUrl) return;
    var reactUrl = layout.dataset.reactUrl;
    var reactionsUrl = layout.dataset.reactionsUrl;

    // ── Rendering ─────────────────────────────────────────────
    function renderContainer(container, list) {
        container.textContent = "";
        (list || []).forEach(function (entry) {
            var chip = document.createElement("button");
            chip.type = "button";
            chip.className = "reaction-chip" + (entry.mine ? " mine" : "");
            chip.dataset.emoji = entry.emoji;
            chip.textContent = entry.emoji + " " + entry.count;
            if (entry.who && entry.who.length) chip.title = entry.who.join(", ");
            container.appendChild(chip);
        });
    }

    function applyAll(data) {
        document.querySelectorAll(".reactions[data-message-id]").forEach(function (c) {
            renderContainer(c, data[c.dataset.messageId] || []);
        });
    }

    function fetchReactions() {
        fetch(reactionsUrl, { headers: { "X-Requested-With": "fetch" } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { if (d) applyAll(d.reactions || {}); })
            .catch(function () {});
    }

    function sendReaction(messageId, emoji) {
        var body = new URLSearchParams();
        body.set("message_id", messageId);
        body.set("emoji", emoji);
        fetch(reactUrl, {
            method: "POST",
            headers: {
                "X-CSRFToken": getCsrfToken(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body: body.toString(),
        })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d) return;
                var c = document.querySelector(
                    '.reactions[data-message-id="' + messageId + '"]'
                );
                if (c) renderContainer(c, d.reactions || []);
            })
            .catch(function () {});
    }

    // ── Picker-Popover ────────────────────────────────────────
    var picker = null;

    function closePicker() {
        if (picker) { picker.remove(); picker = null; }
    }

    function emojiKnopf(emoji, onPick) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "reaction-pick";
        b.textContent = emoji;
        b.addEventListener("click", function () { onPick(emoji); });
        return b;
    }

    function emojiRaster(onPick) {
        var raster = document.createDocumentFragment();
        EMOJI_GRUPPEN.forEach(function (gruppe) {
            var titel = document.createElement("div");
            titel.className = "emoji-gruppe";
            titel.textContent = gruppe.titel;
            raster.appendChild(titel);
            gruppe.emojis.forEach(function (emoji) {
                raster.appendChild(emojiKnopf(emoji, onPick));
            });
        });
        return raster;
    }

    function platziere(button) {
        var rect = button.getBoundingClientRect();
        picker.style.top = (window.scrollY + rect.bottom + 4) + "px";
        picker.style.left =
            (window.scrollX +
                Math.max(8, Math.min(rect.left, window.innerWidth - picker.offsetWidth - 8))) + "px";
    }

    function openPicker(button) {
        closePicker();
        var messageId = button.dataset.messageId;
        picker = document.createElement("div");
        picker.className = "reaction-picker";
        var waehle = function (emoji) {
            sendReaction(messageId, emoji);
            closePicker();
        };

        QUICK_EMOJIS.forEach(function (emoji) {
            picker.appendChild(emojiKnopf(emoji, waehle));
        });

        var mehr = document.createElement("button");
        mehr.type = "button";
        mehr.className = "reaction-pick";
        mehr.textContent = "…";
        mehr.title = "Mehr Emojis";
        mehr.setAttribute("aria-label", "Mehr Emojis");
        mehr.addEventListener("click", function (e) {
            // Sonst haelt der Dokument-Handler den entfernten Knopf fuer „ausserhalb“.
            e.stopPropagation();
            mehr.remove();
            picker.classList.add("voll");
            picker.appendChild(emojiRaster(waehle));
            platziere(button);
        });
        picker.appendChild(mehr);

        document.body.appendChild(picker);
        platziere(button);
    }

    // Knopf am Nachrichtenfeld: fuegt an der Cursorposition ein und bleibt offen,
    // damit mehrere Emojis hintereinander gehen.
    function openEinfuegePicker(button) {
        closePicker();
        var ta = document.getElementById("mitteilung-textarea");
        if (!ta) return;
        picker = document.createElement("div");
        picker.className = "reaction-picker voll";
        picker.appendChild(emojiRaster(function (emoji) {
            ta.setRangeText(emoji, ta.selectionStart, ta.selectionEnd, "end");
            ta.dispatchEvent(new Event("input", { bubbles: true }));
            ta.focus();
        }));
        document.body.appendChild(picker);
        platziere(button);
    }

    // ── Delegierte Klicks ─────────────────────────────────────
    document.addEventListener("click", function (e) {
        var add = e.target.closest(".reaction-add");
        if (add) {
            e.stopPropagation();
            if (picker && picker._owner === add) { closePicker(); return; }
            openPicker(add);
            if (picker) picker._owner = add;
            return;
        }
        var einfuegen = e.target.closest(".emoji-knopf");
        if (einfuegen) {
            e.stopPropagation();
            if (picker && picker._owner === einfuegen) { closePicker(); return; }
            openEinfuegePicker(einfuegen);
            if (picker) picker._owner = einfuegen;
            return;
        }
        var chip = e.target.closest(".reaction-chip");
        if (chip) {
            var container = chip.closest(".reactions[data-message-id]");
            if (container) sendReaction(container.dataset.messageId, chip.dataset.emoji);
            return;
        }
        if (picker && !picker.contains(e.target)) closePicker();
    });

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") closePicker();
    });

    fetchReactions();
    // Im verborgenen Tab nicht pollen — wie der Nachrichten-Poll in forum.html.
    // Beim Zurueckwechseln sofort einmal nachziehen.
    setInterval(function () {
        if (!document.hidden) fetchReactions();
    }, POLL_MS);
    document.addEventListener("visibilitychange", function () {
        if (!document.hidden) fetchReactions();
    });
})();
