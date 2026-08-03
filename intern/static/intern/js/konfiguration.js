"use strict";
(function () {
    const changeMap = new Map();   // id -> {value, description}
    const newRowMap = new Map();   // tempId -> {key, value, description}
    const deleteIds = new Set();
    let tempIdCounter = 0;

    const MAIL_NON_TEXT_KEYS = ["MAIL_BEI_AKTIVIERUNG"];
    const STORAGE_KEY = "konfig-gruppen-offen";
    // Modul-Flag: toggle feuert auch bei programmatischem details.open = true.
    // Die Suche würde sonst den gemerkten Aufklapp-Zustand aller Gruppen überschreiben.
    let programmatisch = false;

    const PENCIL_SVG = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>';
    const CANCEL_SVG = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

    const applyBar = document.getElementById("konfig-apply-bar");
    const mailhelp = document.getElementById("konfig-mailhelp");
    const leerHinweis = document.getElementById("kf-leer");

    function autoGrow(ta) {
        if (ta.tagName !== "TEXTAREA" || ta.offsetParent === null) return;   // input/checkbox: kein scrollHeight; zugeklappt: 0
        // Mindesthöhe aus rows (4 für Textfelder) — nie unter 4 Zeilen schrumpfen.
        const cs = getComputedStyle(ta);
        const lh = parseFloat(cs.lineHeight) || 1.45 * parseFloat(cs.fontSize);
        const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
        const basis = (parseInt(ta.rows, 10) || 1) * lh + pad;
        ta.style.minHeight = "0";
        ta.style.minHeight = Math.max(ta.scrollHeight, basis) + "px";
    }

    function measureBars() {
        const barH = applyBar.classList.contains("visible") ? applyBar.offsetHeight : 0;
        const helpH = mailhelp.classList.contains("visible") ? mailhelp.offsetHeight : 0;
        const root = document.documentElement;
        root.style.setProperty("--kf-applybar-h", barH + "px");
        root.style.setProperty("--kf-bars-h", (barH + helpH) + "px");
    }

    function countChanges() {
        let n = changeMap.size + deleteIds.size;
        newRowMap.forEach(function (r) { if (r.key.trim()) n++; });
        return n;
    }

    function updateApplyBar() {
        const n = countChanges();
        document.getElementById("konfig-change-count").textContent = n;
        applyBar.classList.toggle("visible", n > 0);
        document.getElementById("konfig-change-summary").textContent =
            n === 1 ? "1 ungespeicherte Änderung"
            : n > 1 ? n + " ungespeicherte Änderungen"
            : "";
        measureBars();
    }

    function getCsrfToken() {
        const m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : "";
    }

    // --- Aufklapp-Zustand in localStorage ---------------------------------
    function getSavedOpen() {
        try { return new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]")); }
        catch (_) { return new Set(); }
    }
    function persistOpenState() {
        const ids = [];
        document.querySelectorAll(".kf-gruppe").forEach(function (g) {
            if (g.open && !g.hidden) ids.push(g.id.replace(/^kf-g-/, ""));
        });
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(ids)); } catch (_) {}
    }

    // --- Mail-Legende am Fokus -------------------------------------------
    function keyOfEintrag(entry) {
        const explicit = entry.dataset.key;
        if (explicit) return explicit.toUpperCase();
        const keyInput = entry.querySelector(".kf-key-input");
        return (keyInput ? keyInput.value : "").trim().toUpperCase();
    }
    function syncMailHelp(focused) {
        const entry = focused && focused.closest && focused.closest(".kf-eintrag");
        let show = false;
        if (entry) {
            const key = keyOfEintrag(entry);
            if (key.startsWith("MAIL_") && MAIL_NON_TEXT_KEYS.indexOf(key) === -1) show = true;
        }
        mailhelp.classList.toggle("visible", show);
        measureBars();
    }
    document.addEventListener("focusin", function (e) { syncMailHelp(e.target); });
    // focusout feuert vor focusin — erst nach einer Mikrotask auswerten, sonst
    // blinkt die Legende beim Tabben von einem Mailtext zum nächsten.
    document.addEventListener("focusout", function () {
        setTimeout(function () { syncMailHelp(document.activeElement); }, 0);
    });

    // --- Beschreibung umschalten -----------------------------------------
    function wireDesc(entry, onInput) {
        const text = entry.querySelector(".kf-desc-text");
        const edit = entry.querySelector(".kf-desc-edit");
        const input = entry.querySelector(".kf-desc-input");
        function begin() {
            text.hidden = true;
            edit.hidden = true;
            input.hidden = false;
            input.value = text.textContent;
            input.focus();
            input.select();
        }
        function commit() {
            text.textContent = input.value;
            input.hidden = true;
            text.hidden = false;
            edit.hidden = false;
            onInput();
        }
        text.addEventListener("click", begin);
        edit.addEventListener("click", begin);
        input.addEventListener("blur", commit);
        input.addEventListener("keydown", function (e) {
            if (e.key === "Enter") { e.preventDefault(); input.blur(); }
            else if (e.key === "Escape") { input.blur(); }
        });
        input.addEventListener("input", onInput);
    }

    // --- Bestehende Einträge verdrahten ----------------------------------
    function wireExisting(entry) {
        const id = parseInt(entry.dataset.id, 10);
        const typ = entry.dataset.typ;
        const widget = entry.querySelector(".kf-value-input");
        const delBtn = entry.querySelector(".kf-del-btn");
        function track() {
            // Boolean bleibt die Zeichenkette "1"/"0" — nur das Widget ist eine
            // Checkbox; alle anderen Typen lesen .value als Zeichenkette.
            const val = (typ === "bool") ? (widget.checked ? "1" : "0") : widget.value;
            changeMap.set(id, {
                value: val,
                description: entry.querySelector(".kf-desc-input").value,
            });
            updateApplyBar();
        }
        if (widget.tagName === "TEXTAREA") {
            widget.addEventListener("input", function () { autoGrow(widget); track(); });
        } else {
            // input/checkbox: input feuert beim Tippen, change zuverlässig bei
            // Checkbox-Umschaltung und number-Spinner.
            widget.addEventListener("input", track);
            widget.addEventListener("change", track);
        }
        delBtn.addEventListener("click", function (e) {
            e.stopPropagation();
            if (entry.classList.contains("to-delete")) {
                deleteIds.delete(id);
                entry.classList.remove("to-delete");
            } else {
                deleteIds.add(id);
                changeMap.delete(id);
                entry.classList.add("to-delete");
            }
            updateApplyBar();
        });
        wireDesc(entry, track);
    }

    document.querySelectorAll(".kf-eintrag[data-id]").forEach(wireExisting);

    // --- Neue Einträge in .kf-neu ----------------------------------------
    function removeNewRow(entry, tempId) {
        newRowMap.delete(tempId);
        entry.remove();
        const neu = document.getElementById("kf-neu");
        if (!neu.children.length) neu.hidden = true;
        updateApplyBar();
    }
    function insertNewRow() {
        const tempId = ++tempIdCounter;
        const rowData = { key: "", value: "", description: "" };
        newRowMap.set(tempId, rowData);

        const neu = document.getElementById("kf-neu");
        neu.hidden = false;

        const entry = document.createElement("div");
        entry.className = "kf-eintrag";
        entry.dataset.tempId = String(tempId);
        entry.dataset.typ = "text";   // ad-hoc-Schlüssel: Typ unbekannt → Textarea
        entry.innerHTML =
            '<div class="kf-key">' +
            '<input type="text" class="inline-input kf-key-input" placeholder="SCHLUESSEL" maxlength="64">' +
            '<button type="button" class="kf-del-btn" title="Abbrechen" aria-label="Abbrechen">' + CANCEL_SVG + "</button>" +
            "</div>" +
            '<div class="kf-wert"><textarea class="inline-input kf-value-input" rows="4"></textarea></div>' +
            '<div class="kf-desc">' +
            '<span class="kf-desc-text" tabindex="0"></span>' +
            '<button type="button" class="kf-desc-edit" title="Beschreibung bearbeiten" aria-label="Beschreibung bearbeiten">' + PENCIL_SVG + "</button>" +
            '<input type="text" class="inline-input kf-desc-input" maxlength="256" hidden>' +
            "</div>";
        neu.prepend(entry);

        const keyInput = entry.querySelector(".kf-key-input");
        const valueTa = entry.querySelector(".kf-value-input");
        const cancelBtn = entry.querySelector(".kf-del-btn");
        function syncRow() {
            rowData.key = keyInput.value;
            rowData.value = valueTa.value;
            rowData.description = entry.querySelector(".kf-desc-input").value;
            updateApplyBar();
        }
        keyInput.addEventListener("input", syncRow);
        valueTa.addEventListener("input", function () { autoGrow(valueTa); syncRow(); });
        [keyInput, valueTa].forEach(function (inp) {
            inp.addEventListener("keydown", function (e) {
                if (e.key === "Escape") removeNewRow(entry, tempId);
            });
        });
        cancelBtn.addEventListener("click", function (e) {
            e.stopPropagation();
            removeNewRow(entry, tempId);
        });
        wireDesc(entry, syncRow);
        keyInput.focus();
        updateApplyBar();
    }
    document.getElementById("add-konfig-btn").addEventListener("click", insertNewRow);

    // --- Suche (Progressive Enhancement) ---------------------------------
    function filtern(q) {
        if (!q) {
            const saved = getSavedOpen();
            programmatisch = true;
            document.querySelectorAll(".kf-gruppe").forEach(function (g) {
                g.hidden = false;
                g.querySelectorAll(".kf-eintrag").forEach(function (e) { e.hidden = false; });
                g.open = saved.has(g.id.replace(/^kf-g-/, ""));
            });
            programmatisch = false;
            leerHinweis.hidden = true;
            return;
        }
        let total = 0;
        programmatisch = true;
        document.querySelectorAll(".kf-gruppe").forEach(function (g) {
            let sichtbar = 0;
            g.querySelectorAll(".kf-eintrag").forEach(function (e) {
                const key = (e.dataset.key || (e.querySelector(".kf-key-input") || {}).value || "").toLowerCase();
                const widget = e.querySelector(".kf-value-input");
                // Bool-Checkbox hat keinen sinnvollen .value-Text — „an"/„aus"
                // durchsuchbar machen, sonst den Feldwert wie heute.
                let wert;
                if (e.dataset.typ === "bool" && widget && widget.type === "checkbox") {
                    wert = widget.checked ? "an" : "aus";
                } else {
                    wert = (widget ? widget.value : "") || "";
                }
                wert = wert.toLowerCase();
                const beschrEl = e.querySelector(".kf-desc-text");
                const beschr = (beschrEl ? beschrEl.textContent : "").toLowerCase();
                const treffer = key.indexOf(q) !== -1 || wert.indexOf(q) !== -1 || beschr.indexOf(q) !== -1;
                e.hidden = !treffer;
                if (treffer) sichtbar++;
            });
            g.hidden = sichtbar === 0;
            if (sichtbar > 0) g.open = true;
            total += sichtbar;
        });
        programmatisch = false;
        leerHinweis.hidden = total > 0;
    }
    const suche = document.getElementById("kf-suche");
    const suchfeld = document.getElementById("kf-suchfeld");
    if (suchfeld) {
        suche.hidden = false;   // ohne JS stünde hier sonst ein totes Feld
        suchfeld.addEventListener("input", function () {
            filtern(suchfeld.value.trim().toLowerCase());
        });
        suchfeld.addEventListener("keydown", function (e) {
            if (e.key === "Enter") e.preventDefault();   // kein Submit — würde Änderungen wegwerfen
        });
    }

    // --- Aufklapp-Zustand wiederherstellen + Autogrow beim ersten Öffnen --
    const saved = getSavedOpen();
    document.querySelectorAll(".kf-gruppe").forEach(function (d) {
        const gid = d.id.replace(/^kf-g-/, "");
        if (saved.has(gid)) {
            d.open = true;
            d.querySelectorAll(".kf-value-input").forEach(autoGrow);
            d.dataset.grown = "1";
        }
    });
    document.querySelectorAll(".kf-gruppe").forEach(function (d) {
        d.addEventListener("toggle", function () {
            if (!d.dataset.grown && d.open) {
                d.querySelectorAll(".kf-value-input").forEach(autoGrow);
                d.dataset.grown = "1";
            }
            if (!programmatisch) persistOpenState();
        });
    });

    // --- Anwenden --------------------------------------------------------
    document.getElementById("konfig-apply-btn").addEventListener("click", async function () {
        const btn = document.getElementById("konfig-apply-btn");
        btn.disabled = true;
        const payload = {
            changes: [],
            new: [],
            delete: Array.from(deleteIds),
        };
        changeMap.forEach(function (v, id) {
            payload.changes.push({ id: id, value: v.value, description: v.description });
        });
        newRowMap.forEach(function (r) {
            if (r.key.trim()) {
                payload.new.push({ key: r.key.trim(), value: r.value, description: r.description });
            }
        });
        try {
            const resp = await fetch(window.location.href, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken(),
                },
                body: JSON.stringify(payload),
            });
            const data = await resp.json();
            if (data.ok) {
                location.reload();
            } else {
                btn.disabled = false;
            }
        } catch (_) {
            btn.disabled = false;
        }
    });

    measureBars();
})();