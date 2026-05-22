/* Tri-state sliding toggle: drives the hidden <select> and the pill switch. */
(function () {
    var OFFSETS = { "false": "0px", "unknown": "14px", "true": "28px" };

    function syncState(toggle, val) {
        var thumb = toggle.querySelector(".tri-toggle-thumb");
        toggle.dataset.value = val;                           // triggers CSS colour change
        if (thumb) thumb.style.transform = "translateX(" + (OFFSETS[val] || "0px") + ")";
        toggle.querySelectorAll(".tri-toggle-seg").forEach(function (s) {
            s.classList.toggle("selected", s.dataset.val === val);
        });
    }

    function initToggles() {
        document.querySelectorAll(".tri-toggle").forEach(function (toggle) {
            var wrap = toggle.parentElement;
            var select = wrap && wrap.querySelector(".tri-toggle-select");
            if (!select) return;

            syncState(toggle, select.value || "unknown");

            toggle.querySelectorAll(".tri-toggle-seg").forEach(function (seg) {
                seg.addEventListener("click", function () {
                    select.value = seg.dataset.val;
                    syncState(toggle, seg.dataset.val);
                });
            });
        });

        /* Omit "unknown" selects from GET params so the URL stays clean.
           Exception: selects marked data-keep-unknown stay in the URL so a
           server-side default isn't re-applied when the user picks "Egal". */
        document.querySelectorAll(".filter-form").forEach(function (form) {
            form.addEventListener("submit", function () {
                form.querySelectorAll(".tri-toggle-select").forEach(function (sel) {
                    if (sel.value === "unknown" && !sel.dataset.keepUnknown) {
                        sel.disabled = true;
                    }
                });
            });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initToggles);
    } else {
        initToggles();
    }
})();
