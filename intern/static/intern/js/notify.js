/* ── Site-wide notification bubbles (ChangeLog-based) ── */
(function () {
    "use strict";

    var body = document.body;
    var baseline = parseInt(body.dataset.latestChangelogId, 10);
    // isNaN means the data attribute was absent (unauthenticated); 0 means
    // no ChangeLog rows exist yet.  In both cases we start polling but the
    // first response will sync us to the current head without flashing stale
    // entries.
    if (isNaN(baseline)) return; // not authenticated (no data attribute)
    var firstPoll = !baseline;  // true when baseline is 0 (fresh DB / first visit)
    var currentForum = body.dataset.currentForum || "";
    var notifyEnabled = body.dataset.notifyEnabled !== "0";
    var stack = document.getElementById("notify-stack");
    if (!stack) return;

    var POLL_MS = parseInt(body.dataset.notifyPollMs, 10) || 10000;
    var DISMISS_MS = parseInt(body.dataset.notifyDismissMs, 10) || 6000;
    var MAX_VISIBLE = 5;
    var pollTimer = null;

    /* ── Sidebar toggle ── */
    var toggleBtn = document.getElementById("notify-toggle");
    if (toggleBtn) {
        updateToggleUI();
        toggleBtn.addEventListener("click", function () {
            fetch("/intern/notify/toggle/", { method: "POST", headers: { "X-CSRFToken": getCSRF() } })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    notifyEnabled = data.notify_enabled;
                    body.dataset.notifyEnabled = notifyEnabled ? "1" : "0";
                    updateToggleUI();
                    if (notifyEnabled) { poll(); startPolling(); }
                    else { stopPolling(); clearAllBubbles(); }
                })
                .catch(function () {});
        });
    }

    function getCSRF() {
        var m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : "";
    }

    function updateToggleUI() {
        if (!toggleBtn) return;
        var offIcon = toggleBtn.querySelector(".notify-icon-off");
        var onIcon = toggleBtn.querySelector(".nav-icon:not(.notify-icon-off)");
        var label = toggleBtn.querySelector(".notify-label");
        if (notifyEnabled) {
            if (offIcon) offIcon.style.display = "none";
            if (onIcon) onIcon.style.display = "";
            if (label) label.textContent = "Benachrichtigungen";
        } else {
            if (offIcon) offIcon.style.display = "";
            if (onIcon) onIcon.style.display = "none";
            if (label) label.textContent = "Benachrichtigungen (aus)";
        }
    }

    function clearAllBubbles() {
        while (stack.firstChild) stack.removeChild(stack.firstChild);
    }

    /* ── Polling ── */
    function poll() {
        if (document.hidden) return;
        if (!notifyEnabled) return;
        fetch("/intern/notify/?since=" + baseline)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var entries = data.entries || [];
                // On the very first poll after a fresh page load where the DB
                // had no ChangeLog rows (baseline was 0), sync baseline to the
                // server's latest_id and skip showing any entries — they all
                // predate the user opening the page.
                if (data.latest_id && firstPoll) {
                    baseline = data.latest_id;
                    firstPoll = false;
                    return;
                }
                for (var i = 0; i < entries.length; i++) {
                    var e = entries[i];
                    if (e.id > baseline) baseline = e.id;
                    // Skip Mitteilung in the forum currently being viewed (inline HTMX handles it)
                    if (e.model === "Mitteilung" && String(e.forum) === currentForum) continue;
                    showBubble(e);
                }
            })
            .catch(function () { /* network error — ignore */ });
    }

    /* ── Build detail URL ── */
    function detailURL(entry) {
        if (entry.action === "delete") return null;
        switch (entry.model) {
            case "Lied": return "/intern/titel/" + entry.object_id + "/";
            case "Termin": return "/intern/termin/" + entry.object_id + "/";
            case "Forum": return "/intern/forum/" + entry.object_id + "/";
            case "Mitteilung": return "/intern/forum/" + entry.forum + "/";
            case "Artikel": return "/intern/artikel/" + encodeURIComponent(entry.object_repr) + "/";
            case "User": return "/intern/mitglied/" + entry.object_id + "/";
            default: return null;
        }
    }

    /* ── Render a bubble ── */
    function showBubble(e) {
        if (!notifyEnabled) return;

        while (stack.children.length >= MAX_VISIBLE) {
            stack.removeChild(stack.firstChild);
        }

        var el = document.createElement("a");
        el.className = "notify-bubble notify-model-" + e.model.toLowerCase();
        var url = detailURL(e);
        if (url) {
            el.href = url;
        } else {
            // deletes have no detail page — use a div instead
            el = document.createElement("div");
            el.className = "notify-bubble notify-model-" + e.model.toLowerCase();
        }

        // Icon per model
        var iconSvg = modelIcon(e.model);
        if (iconSvg) {
            var iconSpan = document.createElement("span");
            iconSpan.className = "notify-icon";
            iconSpan.innerHTML = iconSvg;
            el.appendChild(iconSpan);
        }

        // Avatar (Mitteilung only)
        if (e.avatar) {
            var img = document.createElement("img");
            img.className = "notify-avatar";
            img.src = e.avatar;
            img.alt = "";
            img.loading = "lazy";
            el.appendChild(img);
        }

        var body_ = document.createElement("div");
        body_.className = "notify-body";

        var header = document.createElement("div");
        header.className = "notify-header";

        if (e.model === "Mitteilung" && e.user) {
            var sender = document.createElement("strong");
            sender.textContent = e.user;
            header.appendChild(sender);
        } else {
            var modelLabel = document.createElement("strong");
            modelLabel.textContent = e.model_label;
            header.appendChild(modelLabel);
        }

        var meta = document.createElement("span");
        meta.className = "notify-meta";
        if (e.model === "Mitteilung" && e.thema) {
            meta.textContent = e.thema;
        } else if (e.model !== "Mitteilung") {
            meta.textContent = e.action_label;
        }
        header.appendChild(meta);

        body_.appendChild(header);

        // Snippet / object repr
        var desc = document.createElement("div");
        desc.className = "notify-snippet";
        if (e.model === "Mitteilung" && e.snippet) {
            desc.textContent = e.snippet;
        } else if (e.object_repr) {
            desc.textContent = e.object_repr;
        }
        body_.appendChild(desc);

        // Who did it (non-Mitteilung)
        if (e.model !== "Mitteilung" && e.user && e.user !== "?") {
            var who = document.createElement("div");
            who.className = "notify-who";
            who.textContent = "von " + e.user;
            body_.appendChild(who);
        }

        el.appendChild(body_);
        stack.appendChild(el);

        var timer = setTimeout(function () { dismiss(el); }, DISMISS_MS);
        el.addEventListener("click", function () {
            clearTimeout(timer);
            dismiss(el);
        }, { once: true });
    }

    function dismiss(el) {
        el.classList.add("notify-bubble-out");
        el.addEventListener("transitionend", function () {
            if (el.parentNode) el.parentNode.removeChild(el);
        }, { once: true });
        setTimeout(function () {
            if (el.parentNode) el.parentNode.removeChild(el);
        }, 400);
    }

    /* ── Model icons (small SVG) ── */
    function modelIcon(model) {
        switch (model) {
            case "Mitteilung":
                return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
            case "Termin":
                return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>';
            case "Lied":
                return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>';
            case "Artikel":
                return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8M15 18h-5M10 6h8v4h-8z"/></svg>';
            case "Forum":
                return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>';
            default:
                return null;
        }
    }

    /* ── Start / stop polling ── */
    function startPolling() {
        if (pollTimer) return;
        pollTimer = setInterval(poll, POLL_MS);
    }

    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    document.addEventListener("visibilitychange", function () {
        if (document.hidden) {
            stopPolling();
        } else {
            poll();
            startPolling();
        }
    });

    if (notifyEnabled) startPolling();
})();