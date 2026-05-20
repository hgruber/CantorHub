(function () {
  const COL_TO_OPTION = { yes: "1", no: "2", maybe: "3" };

  function init() {
    const section = document.getElementById("attendance-section");
    if (!section) return;
    const root = section.querySelector(".attendance-single[data-editable='1']");
    if (!root || typeof Sortable === "undefined") return;

    const url = root.dataset.anwesenheitUrl;
    const editBtn = section.querySelector(".anwesenheit-edit-btn");
    const saveBtn = section.querySelector(".anwesenheit-save-btn");
    const cancelBtn = section.querySelector(".anwesenheit-cancel-btn");
    if (!url || !editBtn || !saveBtn || !cancelBtn) return;

    let sortables = [];

    function currentCol(chip) {
      return chip.closest(".att-chips").dataset.col;
    }

    function chipsTargetFor(chip, col) {
      const tr = chip.closest("tr");
      return tr ? tr.querySelector('.att-chips[data-col="' + col + '"]') : null;
    }

    function refreshDirty() {
      let dirty = 0;
      root.querySelectorAll(".att-chip").forEach((chip) => {
        const changed = currentCol(chip) !== chip.dataset.originalCol;
        chip.classList.toggle("att-chip-dirty", changed);
        if (changed) dirty++;
      });
      saveBtn.hidden = dirty === 0;
    }

    function revertChips() {
      root.querySelectorAll(".att-chip").forEach((chip) => {
        const orig = chip.dataset.originalCol;
        if (currentCol(chip) !== orig) {
          const target = chipsTargetFor(chip, orig);
          if (target) target.appendChild(chip);
        }
      });
      refreshDirty();
    }

    function enableEditMode() {
      root.querySelectorAll(".att-chips").forEach((ul) => {
        const stimme = ul.dataset.stimme;
        sortables.push(new Sortable(ul, {
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
        }));
      });
      root.classList.add("attendance-edit-mode");
      editBtn.hidden = true;
      cancelBtn.hidden = false;
    }

    function exitEditMode() {
      sortables.forEach((s) => s.destroy());
      sortables = [];
      root.classList.remove("attendance-edit-mode");
      cancelBtn.hidden = true;
      saveBtn.hidden = true;
      editBtn.hidden = false;
    }

    editBtn.addEventListener("click", enableEditMode);
    cancelBtn.addEventListener("click", () => {
      revertChips();
      exitEditMode();
    });

    saveBtn.addEventListener("click", async () => {
      const changes = [];
      root.querySelectorAll(".att-chip.att-chip-dirty").forEach((chip) => {
        const opt = COL_TO_OPTION[currentCol(chip)];
        if (opt) changes.push({ person_id: Number(chip.dataset.uid), option: opt });
      });
      if (!changes.length) return;
      const csrfEl = document.querySelector("[name=csrfmiddlewaretoken]");
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
          current.replaceWith(fresh);
          init();
        }
      } catch (e) {
        alert("Speichern fehlgeschlagen.");
      } finally {
        saveBtn.disabled = false;
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
