(function () {
  // "na" (Keine Angabe) is intentionally never a move target: enforced here in VALID_TARGETS,
  // in the Sortable `put` guard below, and by COL_TO_OPTION having no "na" entry. Keep all three in sync.
  const COL_TO_OPTION = { yes: "1", no: "2", maybe: "3" };
  const COL_LABELS = { yes: "Zusage", no: "Absage", maybe: "Eventuell" };
  const VALID_TARGETS = ["yes", "no", "maybe"];

  function init() {
    const section = document.getElementById("attendance-section");
    if (!section) return;
    const singleRoot = section.querySelector(".attendance-single");
    const splitRoot = section.querySelector(".attendance-split");
    if (!singleRoot) return;

    const url = section.dataset.anwesenheitUrl;
    const editBtn = section.querySelector(".anwesenheit-edit-btn");
    const saveBtn = section.querySelector(".anwesenheit-save-btn");
    const cancelBtn = section.querySelector(".anwesenheit-cancel-btn");
    if (!url || !editBtn || !saveBtn || !cancelBtn) return;

    let sortables = [];
    let activeRoot = null;
    let popover = null;
    let tapModeHandler = null;

    function isSplitVisible() {
      return !!splitRoot && getComputedStyle(splitRoot).display !== "none";
    }

    function currentCol(chip) {
      return chip.closest(".att-chips").dataset.col;
    }

    function chipsTargetFor(chip, col) {
      const stimme = chip.closest(".att-chips").dataset.stimme;
      return activeRoot.querySelector(
        '.att-chips[data-stimme="' + stimme + '"][data-col="' + col + '"]'
      );
    }

    function refreshDirty() {
      let dirty = 0;
      activeRoot.querySelectorAll(".att-chip").forEach((chip) => {
        const changed = currentCol(chip) !== chip.dataset.originalCol;
        chip.classList.toggle("att-chip-dirty", changed);
        if (changed) dirty++;
      });
      saveBtn.hidden = dirty === 0;
    }

    function revertChips() {
      activeRoot.querySelectorAll(".att-chip").forEach((chip) => {
        const orig = chip.dataset.originalCol;
        if (currentCol(chip) !== orig) {
          const target = chipsTargetFor(chip, orig);
          if (target) target.appendChild(chip);
        }
      });
      refreshDirty();
    }

    function closePopover() {
      if (popover) {
        popover.remove();
        popover = null;
      }
    }

    function openPopover(chip) {
      closePopover();
      const targets = VALID_TARGETS.filter((c) => c !== currentCol(chip));
      if (!targets.length) return;

      popover = document.createElement("div");
      popover.className = "att-move-picker";
      targets.forEach((col) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "att-move-pick";
        b.textContent = COL_LABELS[col];
        b.addEventListener("click", () => {
          const target = chipsTargetFor(chip, col);
          if (target) {
            target.appendChild(chip);
            refreshDirty();
          }
          closePopover();
        });
        popover.appendChild(b);
      });

      document.body.appendChild(popover);
      const rect = chip.getBoundingClientRect();
      popover.style.top = window.scrollY + rect.bottom + 4 + "px";
      const left = window.scrollX + rect.left;
      const maxLeft = window.scrollX + window.innerWidth - popover.offsetWidth - 8;
      popover.style.left = Math.max(window.scrollX + 4, Math.min(left, maxLeft)) + "px";
    }

    function enableTapMode() {
      tapModeHandler = (e) => {
        const chip = e.target.closest(".att-chip");
        if (chip && activeRoot.contains(chip)) {
          e.stopPropagation();
          openPopover(chip);
          return;
        }
        if (popover && !popover.contains(e.target)) closePopover();
      };
      document.addEventListener("click", tapModeHandler);
    }

    function disableTapMode() {
      if (tapModeHandler) {
        document.removeEventListener("click", tapModeHandler);
        tapModeHandler = null;
      }
      closePopover();
    }

    function enableEditMode() {
      activeRoot = isSplitVisible() ? splitRoot : singleRoot;

      if (activeRoot === singleRoot) {
        if (typeof Sortable === "undefined") {
          activeRoot = null;
          return;
        }
        activeRoot.querySelectorAll(".att-chips").forEach((ul) => {
          const stimme = ul.dataset.stimme;
          sortables.push(
            new Sortable(ul, {
              group: {
                name: "att-" + stimme,
                put: (to, from) => {
                  if (to.el.dataset.col === "na") return false;
                  if (from.el.dataset.stimme !== to.el.dataset.stimme) return false;
                  return true;
                },
              },
              animation: 120,
              ghostClass: "sortable-ghost",
              chosenClass: "sortable-chosen",
              onSort: refreshDirty,
            })
          );
        });
      } else {
        enableTapMode();
      }

      section.classList.add("attendance-edit-mode");
      editBtn.hidden = true;
      cancelBtn.hidden = false;
    }

    function exitEditMode() {
      sortables.forEach((s) => s.destroy());
      sortables = [];
      disableTapMode();
      section.classList.remove("attendance-edit-mode");
      cancelBtn.hidden = true;
      saveBtn.hidden = true;
      editBtn.hidden = false;
      activeRoot = null;
    }

    editBtn.addEventListener("click", enableEditMode);
    cancelBtn.addEventListener("click", () => {
      revertChips();
      exitEditMode();
    });

    saveBtn.addEventListener("click", async () => {
      const changes = [];
      activeRoot.querySelectorAll(".att-chip.att-chip-dirty").forEach((chip) => {
        const opt = COL_TO_OPTION[currentCol(chip)];
        if (opt) changes.push({ person_id: Number(chip.dataset.uid), option: opt });
      });
      if (!changes.length) return;
      const csrfEl = section.querySelector("[name=csrfmiddlewaretoken]");
      const csrf = csrfEl ? csrfEl.value : "";
      saveBtn.disabled = true;
      try {
        const resp = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
          body: JSON.stringify({ changes }),
        });
        if (!resp.ok) throw new Error("save failed");
        const html = await resp.text();
        const tmp = document.createElement("div");
        tmp.innerHTML = html;
        const fresh = tmp.querySelector("#attendance-section");
        const current = document.getElementById("attendance-section");
        if (fresh && current) {
          sortables.forEach((s) => s.destroy());
          sortables = [];
          disableTapMode();
          current.replaceWith(fresh);
          init();
        }
      } catch (e) {
        alert("Speichern fehlgeschlagen.");
      } finally {
        saveBtn.disabled = false;
      }
    });

    // If the viewport crosses the single/split breakpoint while editing, the active-root
    // snapshot would point at a now-hidden subtree with no listeners on the newly visible
    // one — bail out cleanly instead of leaving a half-wired edit session.
    const mq = window.matchMedia("(max-width: 768px)");
    const onBreakpointChange = () => {
      if (activeRoot && isSplitVisible() !== (activeRoot === splitRoot)) {
        revertChips();
        exitEditMode();
      }
    };
    if (mq.addEventListener) {
      mq.addEventListener("change", onBreakpointChange);
    } else {
      mq.addListener(onBreakpointChange);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
