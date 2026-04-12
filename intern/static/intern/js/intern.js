// Hamburger + mobile overlay
const hamburger = document.getElementById("hamburger");
const sidebar = document.getElementById("sidebar");
const overlay = document.getElementById("sidebar-overlay");

if (hamburger && sidebar) {
  hamburger.addEventListener("click", () => {
    sidebar.classList.toggle("active");
    overlay.classList.toggle("active");
  });
}

if (overlay) {
  overlay.addEventListener("click", () => {
    sidebar.classList.remove("active");
    overlay.classList.remove("active");
  });
}

// Active navigation state
document.querySelectorAll(".sidebar-nav .nav-item[href]").forEach((link) => {
  try {
    const linkPath = new URL(link.href).pathname;
    const current = window.location.pathname;
    const dataPath = link.dataset.path;
    const matchPath = dataPath || linkPath;
    if (matchPath.length > 1 && current.startsWith(matchPath)) {
      link.classList.add("active");
    }
  } catch (e) {}
});

// Filter offcanvas functionality - ensure only one offcanvas is open at a time
function toggle(offcanvas) {
  const offcanvases = document.querySelectorAll(".offcanvas");
  offcanvases.forEach((element) => {
    if (element.id !== offcanvas && element.classList.contains("open")) {
      element.classList.remove("open");
      if (
        element.id === "PoolSelector" &&
        typeof window.sortable !== "undefined"
      ) {
        window.sortable.option("disabled", true);
      }
    }
  });

  const filter = document.getElementById(offcanvas);
  if (filter && filter.classList.contains("open")) {
    filter.classList.remove("open");
    // When hiding PoolSelector, disable sorting
    if (
      offcanvas === "PoolSelector" &&
      typeof window.sortable !== "undefined"
    ) {
      window.sortable.option("disabled", false);
    }
  } else if (filter) {
    filter.classList.add("open");
    // When showing PoolSelector, enable sorting
    if (
      offcanvas === "PoolSelector" &&
      typeof window.sortable !== "undefined"
    ) {
      window.sortable.option("disabled", false);
    }
  }
}

// Dropzone configuration - set autoDiscover to false at the beginning
Dropzone.autoDiscover = false;

document.addEventListener("DOMContentLoaded", function () {
  // ── Table row selection (event delegation) ──────────────
  function updateSelectionState() {
    const checked = document.querySelectorAll(
      'input[type="checkbox"][name="select"]:checked',
    );
    const count = checked.length;
    const countEl = document.getElementById("selected-count");
    if (countEl) countEl.textContent = count;
    const action = document.getElementById("Action");
    if (action) action.classList.toggle("open", count > 0);
  }

  document.addEventListener("change", function (e) {
    const cb = e.target;
    if (cb.type !== "checkbox") return;
    if (cb.classList.contains("select-all")) {
      // header checkbox: toggle all row checkboxes
      document
        .querySelectorAll('input[type="checkbox"][name="select"]')
        .forEach((row) => { row.checked = cb.checked; });
    }
    if (cb.classList.contains("select-all") || cb.name === "select") {
      updateSelectionState();
    }
  });

  // Dropzone initialization
  var myDropzone = new Dropzone("#InternDropzone", {
    url: "/intern/upload/",
    paramName: "file",
    maxFilesize: 50,
    headers: {
      "X-CSRFToken": "{{ csrf_token }}",
    },
    init: function () {
      this.on("success", function (file, response) {
        console.log(file);
        console.log(response);
        const textarea = document.getElementById("mitteilung-textarea");
        if (textarea) {
          textarea.value += response.url;
        }
      });
      this.on("queuecomplete", function () {
        console.log("Alle Uploads abgeschlossen!");
        if (window.location.pathname.startsWith("/intern/ordner/")) {
          window.location.reload();
        }
      });
    },
  });

  // Sortable functionality
  const tbody = document.querySelectorAll(".table-container table tbody");
  const moderation = document.querySelector("#PoolSelector table tbody");
  if (tbody && tbody.length >= 2) {
    const sortable = new Sortable(tbody[1], {
      group: { name: "shared" },
      disabled: true,
      animation: 150,
      ghostClass: "blue-background-class",
    });
    const pool = new Sortable(tbody[0], {
      group: { name: "shared" },
      sortable: false,
      animation: 150,
      ghostClass: "blue-background-class",
    });
    const moderate = new Sortable(moderation, {
      group: { name: "shared", pull: "clone", put: false },
      sortable: false,
      animation: 150,
      ghostClass: "blue-background-class",
    });

    window.sortable = sortable;

    // Function to save order
    function saveOrder() {
      const order = [...tbody[1].children].map(
        (row) => row.querySelector("td[data-id]")?.dataset.id,
      );

      // Get CSRF token from Django
      const csrfTokenElement = document.querySelector(
        "[name=csrfmiddlewaretoken]",
      );
      const csrfToken = csrfTokenElement ? csrfTokenElement.value : "";
      const konzert = document.querySelector('select[name="konzert"]');
      const konzert_id = konzert ? konzert.value : "";

      fetch("/intern/update-order/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({ order: order, konzert_id: konzert_id }),
      });
    }

    // Make saveOrder globally accessible
    window.saveOrder = saveOrder;
  }

  // Audio play/pause functionality
  let currentAudio = null;
  let currentAudioElement = null;

  document.addEventListener("click", function (e) {
    // Check if the target has classList before accessing it
    if (
      e.target &&
      e.target.classList &&
      e.target.classList.contains("audio-button")
    ) {
      const button = e.target;
      const audioUrl = button.getAttribute("data-audio-url");
      const songId = button.getAttribute("data-song-id");

      // If there's a currently playing audio and it's not the same song, stop it
      if (currentAudio && currentAudio !== button) {
        if (currentAudioElement) {
          currentAudioElement.pause();
          currentAudioElement = null;
        }
        currentAudio.classList.remove("playing");
        currentAudio.textContent = "▶";
        currentAudio = null;
      }

      // Create audio element if it doesn't exist or if it's a different song
      if (!currentAudio || currentAudio !== button) {
        // If there's an existing audio element, pause it
        if (currentAudioElement) {
          currentAudioElement.pause();
        }

        const audio = new Audio(audioUrl);
        audio.play();
        currentAudio = button;
        currentAudioElement = audio;
        button.classList.add("playing");
        button.textContent = "⏸";

        audio.addEventListener("ended", function () {
          button.classList.remove("playing");
          button.textContent = "▶";
          currentAudio = null;
          currentAudioElement = null;
        });

        audio.addEventListener("error", function () {
          console.error("Error playing audio:", audioUrl);
          button.classList.remove("playing");
          button.textContent = "▶";
          currentAudio = null;
          currentAudioElement = null;
        });
      } else {
        // Toggle play/pause for the same song
        if (currentAudioElement.paused) {
          currentAudioElement.play();
          button.classList.add("playing");
          button.textContent = "⏸";
        } else {
          currentAudioElement.pause();
          button.classList.remove("playing");
          button.textContent = "▶";
          currentAudio = null;
          currentAudioElement = null;
        }
      }
    }
  });

  // File actions: delete / move / copy
  window.fileAction = function (action) {
    const formId = action === "delete" ? "delete-form"
                 : action === "move"   ? "move-form"
                 :                       "copy-form";
    const form = document.getElementById(formId);
    if (!form) return;

    // Collect selected items via data-type on each checkbox
    const items = [];
    document.querySelectorAll('input[type="checkbox"][name="select"]:checked')
      .forEach((cb) => {
        if (cb.dataset.type) items.push(cb.dataset.type + ":" + cb.value);
      });

    if (items.length === 0) { alert("Keine Elemente ausgewählt."); return; }

    if (action === "delete") {
      if (!confirm(`${items.length} Element(e) wirklich löschen?`)) return;
    } else {
      const targetRadio = document.querySelector('input[name="folder-target"]:checked');
      if (!targetRadio) { alert("Bitte erst einen Zielordner auswählen."); return; }
      const targetInput = document.getElementById(
        action === "move" ? "move-target" : "copy-target"
      );
      if (targetInput) targetInput.value = targetRadio.value;
    }

    // Append item inputs and submit
    form.querySelectorAll('input[name="item"]').forEach((el) => el.remove());
    items.forEach((val) => {
      const inp = document.createElement("input");
      inp.type = "hidden"; inp.name = "item"; inp.value = val;
      form.appendChild(inp);
    });
    form.submit();
  };

  // ── Folder drag-and-drop ──────────────────────────────────
  (function initFolderDragDrop() {
    const moveForm = document.getElementById("move-form");
    if (!moveForm) return; // only active on folder views

    const allRows = document.querySelectorAll(".table-container tbody tr");
    let draggedItems = [];

    // ── Drag sources: rows that have a select checkbox ──────
    allRows.forEach((row) => {
      const cb = row.querySelector('input[type="checkbox"][name="select"]');
      if (!cb) return;

      row.draggable = true;

      row.addEventListener("dragstart", (e) => {
        const checked = document.querySelectorAll(
          'input[type="checkbox"][name="select"]:checked'
        );
        // If this row is part of the selection, drag the whole selection
        if (checked.length > 0 && cb.checked) {
          draggedItems = [...checked]
            .filter((c) => c.dataset.type)
            .map((c) => c.dataset.type + ":" + c.value);
        } else {
          draggedItems = cb.dataset.type ? [cb.dataset.type + ":" + cb.value] : [];
        }
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", draggedItems.join(","));
        setTimeout(() => row.classList.add("dnd-dragging"), 0);
      });

      row.addEventListener("dragend", () => {
        row.classList.remove("dnd-dragging");
        clearHighlights();
      });
    });

    // ── Drop targets: folder rows (including "..") ──────────
    allRows.forEach((row) => {
      // Extract folder pk from the first ordner link in this row
      const link = row.querySelector('a[href*="/ordner/"]');
      if (!link) return;
      const m = link.getAttribute("href").match(/\/ordner\/(\d+)\//);
      if (!m) return;
      const targetPk = m[1];

      row.addEventListener("dragover", (e) => {
        const isExternalFile = e.dataTransfer.types.includes("Files");
        e.preventDefault();
        e.dataTransfer.dropEffect = isExternalFile ? "copy" : "move";
        row.classList.toggle("dnd-file-over", isExternalFile);
        row.classList.toggle("dnd-over", !isExternalFile);
      });

      row.addEventListener("dragleave", () => {
        row.classList.remove("dnd-over", "dnd-file-over");
      });

      row.addEventListener("drop", (e) => {
        e.preventDefault();
        row.classList.remove("dnd-over", "dnd-file-over");

        // External file drop: upload files to this folder
        if (e.dataTransfer.files.length > 0) {
          uploadFilesToFolder(e.dataTransfer.files, targetPk);
          return;
        }

        // Internal move: don't drop a folder into itself
        const items = draggedItems.filter((item) => {
          const [type, id] = item.split(":");
          return !(type === "Folder" && id === targetPk);
        });
        if (!items.length) return;

        submitDragMove(items, targetPk);
      });
    });

    function clearHighlights() {
      document.querySelectorAll(".dnd-over, .dnd-file-over").forEach((el) =>
        el.classList.remove("dnd-over", "dnd-file-over")
      );
    }

    function uploadFilesToFolder(files, targetPk) {
      const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]").value;
      const promises = [...files].map((file) => {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("folder_id", targetPk);
        return fetch("/intern/upload/", {
          method: "POST",
          headers: { "X-CSRFToken": csrfToken },
          body: formData,
        });
      });
      Promise.all(promises).then(() => window.location.reload());
    }

    function submitDragMove(items, targetPk) {
      moveForm.querySelectorAll('input[name="item"]').forEach((el) => el.remove());
      items.forEach((val) => {
        const inp = document.createElement("input");
        inp.type = "hidden";
        inp.name = "item";
        inp.value = val;
        moveForm.appendChild(inp);
      });
      const targetInput = document.getElementById("move-target");
      if (targetInput) targetInput.value = targetPk;
      moveForm.submit();
    }
  })();

  // Add event listener for save order button
  const saveOrderButton = document.getElementById("saveOrderButton");
  if (saveOrderButton) {
    saveOrderButton.addEventListener("click", function () {
      // Save the order
      if (typeof window.saveOrder !== "undefined") {
        window.saveOrder();
      }
    });
  }

  const input = document.getElementById("new_password1");
  const colors = ["#d9534f", "#f0ad4e", "#ffd500", "#9bc53d", "#28a745"];
  if (input) {
    function evaluatePassword() {
      if (!input.value) return;
      const score = zxcvbn(input.value).score;
      const percent = (score + 1) * 20;
      input.style.setProperty("--strength-width", percent + "%");
      input.style.setProperty("--strength-color", colors[score]);
    }
    input.addEventListener("input", evaluatePassword);
  }
});
