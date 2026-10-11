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

// Theme toggle
(function initTheme() {
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;

  function current() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  // persist nur beim ausdruecklichen Klick: sonst wuerde schon der erste
  // Seitenaufruf die erkannte Systemeinstellung festschreiben und ein
  // spaeterer Wechsel am Betriebssystem bliebe wirkungslos.
  function apply(theme, persist) {
    document.documentElement.setAttribute("data-theme", theme);
    if (persist) localStorage.setItem("theme", theme);
    const meta = document.getElementById("meta-theme-color");
    if (meta) meta.setAttribute("content", theme === "dark" ? "#1a1a2e" : "#ffffff");
    const lightIcon = btn.querySelector(".theme-icon-light");
    const darkIcon = btn.querySelector(".theme-icon-dark");
    const label = btn.querySelector(".theme-label");
    if (theme === "dark") {
      lightIcon.style.display = "none";
      darkIcon.style.display = "";
      if (label) label.textContent = "Hell";
    } else {
      lightIcon.style.display = "";
      darkIcon.style.display = "none";
      if (label) label.textContent = "Dunkel";
    }
  }

  apply(current(), false);

  btn.addEventListener("click", () => {
    apply(current() === "dark" ? "light" : "dark", true);
  });

  // Solange nichts gespeichert ist, dem System live folgen.
  if (window.matchMedia) {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", (e) => {
      if (localStorage.getItem("theme") === null) {
        apply(e.matches ? "dark" : "light", false);
      }
    });
  }
})();

// Schriftgroesse (Einstellungen in der Sidebar). Der Faktor skaliert ueber
// --schrift-faktor die Wurzel-Schriftgroesse; _theme_boot.html setzt ihn schon
// vor dem ersten Paint. Bei 100 % wird der Key entfernt statt gespeichert.
(function initSchriftgroesse() {
  const box = document.getElementById("schriftgroesse");
  if (!box) return;
  const KEY = "schriftgroesse";
  const STUFEN = [0.9, 1, 1.15, 1.3, 1.5];
  const wert = box.querySelector(".schriftgroesse-wert");
  const kleiner = box.querySelector('[data-schritt="-1"]');
  const groesser = box.querySelector('[data-schritt="1"]');

  function gespeicherteStufe() {
    let f = 1;
    try { f = parseFloat(localStorage.getItem(KEY)) || 1; } catch (_) {}
    // naechstgelegene Stufe, falls sich die Stufen einmal aendern
    let beste = STUFEN.indexOf(1);
    STUFEN.forEach((s, i) => {
      if (Math.abs(s - f) < Math.abs(STUFEN[beste] - f)) beste = i;
    });
    return beste;
  }

  let stufe = gespeicherteStufe();

  function anwenden(speichern) {
    const f = STUFEN[stufe];
    const root = document.documentElement;
    if (f === 1) root.style.removeProperty("--schrift-faktor");
    else root.style.setProperty("--schrift-faktor", f);
    if (speichern) {
      try {
        if (f === 1) localStorage.removeItem(KEY);
        else localStorage.setItem(KEY, String(f));
      } catch (_) {}
    }
    wert.textContent = Math.round(f * 100) + " %";
    kleiner.disabled = stufe === 0;
    groesser.disabled = stufe === STUFEN.length - 1;
  }

  anwenden(false);

  box.addEventListener("click", (e) => {
    const btn = e.target.closest(".schriftgroesse-btn");
    if (!btn || btn.disabled) return;
    const neu = stufe + parseInt(btn.dataset.schritt, 10);
    if (neu < 0 || neu >= STUFEN.length) return;
    stufe = neu;
    anwenden(true);
  });
})();

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

// Settings submenu toggle
function toggleSettingsMenu() {
  const submenu = document.getElementById("settings-submenu");
  const toggle = document.getElementById("settings-toggle");
  if (!submenu || !toggle) return;
  submenu.classList.toggle("open");
  toggle.classList.toggle("open");
}

// Admin submenu toggle
function toggleAdminMenu() {
  const submenu = document.getElementById("admin-submenu");
  const toggle = document.getElementById("admin-toggle");
  if (!submenu || !toggle) return;
  submenu.classList.toggle("open");
  toggle.classList.toggle("open");
}

// Auto-open a submenu when one of its sub-destinations is the current page
function autoOpenSubmenu(submenuId, toggleId) {
  const submenu = document.getElementById(submenuId);
  const toggle  = document.getElementById(toggleId);
  if (!submenu || !toggle) return;
  const current = window.location.pathname;
  const isActive = Array.from(submenu.querySelectorAll("a[href]")).some((link) => {
    try {
      const path = link.dataset.path || new URL(link.href).pathname;
      return path.length > 1 && current.startsWith(path);
    } catch (e) { return false; }
  });
  if (isActive) {
    submenu.classList.add("open");
    toggle.classList.add("open");
  }
}
autoOpenSubmenu("admin-submenu",    "admin-toggle");
autoOpenSubmenu("settings-submenu", "settings-toggle");

// Global reference to the app-main Dropzone, set in DOMContentLoaded below
var appMainDz = null;

function refreshFolderTable() {
  var container = document.querySelector(".table-container");
  var tbody = container && container.querySelector("tbody");
  if (!tbody) return;
  var p = new URLSearchParams(window.location.search);
  p.delete("offset");
  var url = window.location.pathname + "?" + p.toString();
  fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      tbody.innerHTML = data.html;
      tbody.querySelectorAll("tr").forEach(function (tr) {
        tr.classList.add("row-fresh");
        setTimeout(function () { tr.classList.remove("row-fresh"); }, 600);
      });
    })
    .catch(function () {});
}

// Filter offcanvas functionality - ensure only one offcanvas is open at a time
function toggle(offcanvas) {
  const offcanvases = document.querySelectorAll(".offcanvas");
  offcanvases.forEach((element) => {
    if (element.id !== offcanvas && element.classList.contains("open")) {
      element.classList.remove("open");
    }
  });

  const filter = document.getElementById(offcanvas);
  if (filter && filter.classList.contains("open")) {
    filter.classList.remove("open");
    // When hiding AddPanel, re-enable the app-main dropzone
    if (offcanvas === "AddPanel" && appMainDz) {
      appMainDz.enable();
    }
  } else if (filter) {
    filter.classList.add("open");
    // When showing AddPanel with file dropzones, disable app-main dropzone
    // so it doesn't steal drag events from the panel's own dropzones
    if (offcanvas === "AddPanel" && appMainDz) {
      appMainDz.disable();
    }
  }
}

// Dropzone configuration - set autoDiscover to false at the beginning
Dropzone.autoDiscover = false;

function getCsrfToken() {
  const el = document.querySelector("[name=csrfmiddlewaretoken]");
  if (el) return el.value;
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : "";
}

document.addEventListener("DOMContentLoaded", function () {
  // ── Clickable table rows ──────────────────────────────────
  document.addEventListener("click", function (e) {
    const tr = e.target.closest("tr[data-href]");
    if (!tr) return;
    // Don't navigate if clicking on interactive elements
    if (e.target.closest("a, button, input, select, textarea, label")) return;
    window.location.href = tr.dataset.href;
  });

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

  // App-main overlay dropzone
  const appMain = document.getElementById("app-main");
  const uploadMaxMb = appMain ? (parseInt(appMain.dataset.uploadMaxMb, 10) || 50) : 50;
  const artikelDateien = [];  // Namen der Uploads in der Artikelansicht
  if (appMain) {
    appMainDz = new Dropzone(appMain, {
      url: "/intern/upload/",
      paramName: "file",
      maxFilesize: uploadMaxMb,
      clickable: false,
      previewsContainer: false,
      headers: { "X-CSRFToken": getCsrfToken() },
      init: function () {
        this.on("sending", function (file, xhr, formData) {
          const folderId = appMain.dataset.uploadFolderId;
          const renameTo = appMain.dataset.uploadRenameTo;
          const avatarUserId = appMain.dataset.uploadAvatarUserId;
          const routeByType = appMain.dataset.uploadRouteByType;
          const liedId = appMain.dataset.uploadLiedId;
          if (folderId) formData.append("folder_id", folderId);
          if (renameTo) formData.append("rename_to", renameTo);
          if (avatarUserId) formData.append("avatar_user_id", avatarUserId);
          if (routeByType) formData.append("route_by_type", "1");
          if (liedId) formData.append("lied_id", liedId);
        });
        this.on("success", function (file, response) {
          const textarea = document.getElementById("mitteilung-textarea");
          if (textarea) textarea.value += response.url;
          // Artikel-Editor: der Verweis kommt vorn ins Textfeld, gespeichert
          // wird erst mit „Speichern".
          const editor = document.querySelector('.article-editor textarea[name="text"]');
          if (editor && response.name) {
            editor.value = "[[Datei:" + response.name + "]]\n" + editor.value;
            editor.dispatchEvent(new Event("input", { bubbles: true }));
          }
          if (appMain.dataset.uploadArtikel && response.name) {
            artikelDateien.push(response.name);
          }
        });
        this.on("queuecomplete", function () {
          // Artikelansicht: alle Dateien dieses Uploads in einer neuen Version
          // vorn einfügen — ein Request, sonst stritten parallele Uploads um
          // dieselbe Versionsnummer.
          const artikel = appMain.dataset.uploadArtikel;
          if (artikel) {
            if (!artikelDateien.length) return;
            const body = new FormData();
            artikelDateien.splice(0).forEach((n) => body.append("datei", n));
            fetch("/intern/artikel/" + encodeURIComponent(artikel) + "/dateien/", {
              method: "POST",
              headers: { "X-CSRFToken": getCsrfToken() },
              body: body,
            }).then(() => window.location.reload());
            return;
          }
          if (window.location.pathname.startsWith("/intern/ordner/")) {
            refreshFolderTable();
          } else if (appMain.dataset.uploadLiedId) {
            window.location.reload();
          }
        });
      },
    });

    // Artikelansicht ohne Schreibrecht: kein Zielordner, und ohne ihn landete
    // ein Drop in der Wurzel — dort wird gar nicht hochgeladen.
    const uploadGesperrt =
      !!document.querySelector(".wiki[data-artikel]") && !appMain.dataset.uploadFolderId;
    if (uploadGesperrt) appMainDz.disable();

    // Topbar-Button: für Geräte ohne Drag & Drop. Die gewählten Dateien laufen
    // durch dieselbe Dropzone wie ein Drop — Zielordner, Fortschrittskarte und
    // Neuladen gelten damit unverändert.
    const uploadBtn = document.getElementById("uploadBtn");
    const uploadInput = document.getElementById("uploadInput");
    if (uploadBtn && uploadInput) {
      uploadBtn.addEventListener("click", () => uploadInput.click());
      uploadInput.addEventListener("change", () => {
        Array.from(uploadInput.files).forEach((f) => appMainDz.addFile(f));
        uploadInput.value = "";  // dieselbe Datei lässt sich erneut wählen
      });
    }

    let dragCounter = 0;
    appMain.addEventListener("dragenter", (e) => {
      if (uploadGesperrt || !e.dataTransfer || !e.dataTransfer.types.includes("Files")) return;
      // Don't show overlay when a panel dropzone is active
      if (document.querySelector('.add-panel.open') || document.querySelector('.dropzone-field.dz-dragover')) return;
      dragCounter++;
      appMain.classList.add("drag-active");
    });
    appMain.addEventListener("dragleave", (e) => {
      if (!e.dataTransfer || !e.dataTransfer.types.includes("Files")) return;
      if (--dragCounter <= 0) {
        dragCounter = 0;
        appMain.classList.remove("drag-active");
      }
    });
    appMain.addEventListener("drop", () => {
      dragCounter = 0;
      appMain.classList.remove("drag-active");
    });
    document.addEventListener("dragleave", (e) => {
      if (e.relatedTarget === null) {
        dragCounter = 0;
        appMain.classList.remove("drag-active");
      }
    });
  }

  // ── Dropzone for filer widgets (AddPanel + edit pages) ──────
  (function initFilerDropzones() {
    // On AddPanel pages, scope to the panel; on edit pages, scope to .wiki or
    // .detail-page (both render AdminImageWidget/AdminFileWidget as .filer-widget
    // elements containing a hidden text input with the foreign-key ID, plus a
    // complex admin lookup UI we replace with a simpler dropzone).
    const scope =
      document.getElementById("AddPanel") ||
      document.querySelector(".wiki") ||
      document.querySelector(".detail-page");
    if (!scope) return;

    const filerWidgets = scope.querySelectorAll(".filer-widget");
    filerWidgets.forEach((widget) => {
      const formGroup = widget.closest(".form-group");
      if (!formGroup) return;
      const label = formGroup.querySelector("label");
      const labelText = label ? label.textContent.trim() : "";

      const fkInput = widget.querySelector("input.vForeignKeyRawIdAdminField");
      if (!fkInput) return;
      const name = fkInput.name; // e.g. "bild", "original"
      const existingId = fkInput.value; // pre-filled on edit pages

      // Hide the entire filer widget UI
      widget.style.display = "none";

      // On AddPanel: create a separate hidden input with _filer_id suffix
      // (the view reads <field>_filer_id from POST). On edit pages: keep
      // the original input name so form.save() picks up the new value.
      let valueInput;
      if (document.getElementById("AddPanel")) {
        fkInput.removeAttribute("name");
        valueInput = document.createElement("input");
        valueInput.type = "hidden";
        valueInput.name = name + "_filer_id";
        valueInput.value = existingId || "";
        formGroup.appendChild(valueInput);
      } else {
        valueInput = fkInput;
      }

      // Create dropzone area
      const dz = document.createElement("div");
      dz.className = "dropzone-field";
      dz.dataset.fieldName = name;

      const preview = document.createElement("div");
      preview.className = "dropzone-field-preview";
      // Dateinamen nur über textContent einfügen — nie über innerHTML.
      function showDone(thumbSrc, fileName) {
        preview.textContent = "";
        if (thumbSrc) {
          const img = document.createElement("img");
          img.className = "dropzone-field-thumb";
          img.src = thumbSrc;
          preview.appendChild(img);
        }
        const span = document.createElement("span");
        span.className = "dropzone-field-done";
        span.textContent = fileName;
        preview.appendChild(span);
      }
      if (existingId) {
        // Show current file thumbnail + name on edit pages
        const thumbImg = widget.querySelector("img.thumbnail_img");
        const descEl = widget.querySelector(".description_text");
        const fileName = descEl && descEl.textContent.trim() ? descEl.textContent.trim() : "aktuelle Datei";
        showDone(thumbImg && thumbImg.src, fileName);
      } else {
        preview.innerHTML = '<span class="dropzone-field-placeholder">' + labelText + ' ablegen oder klicken</span>';
      }

      dz.appendChild(preview);

      new Dropzone(dz, {
        url: "/intern/upload/",
        paramName: "file",
        maxFilesize: uploadMaxMb,
        maxFiles: 1,
        clickable: true,
        previewsContainer: false,
        headers: { "X-CSRFToken": getCsrfToken() },
        init: function () {
          this.on("success", function (file, response) {
            valueInput.value = response.id;
            showDone(response.thumbnail_url, file.name);
          });
          this.on("addedfile", function () {
            preview.innerHTML = '<span class="dropzone-field-uploading">Hochladen…</span>';
          });
        },
      });

      formGroup.appendChild(dz);
    });
  })();

  // Sortable functionality — split layout (konzert reorder mode)
  const splitLayout = document.querySelector(".split-layout");
  const konzertList = document.getElementById("konzert-list");
  const poolList = document.getElementById("pool-list");

  if (splitLayout && konzertList && poolList) {
    const konzertId = splitLayout.dataset.konzertId;

    function updatePositions() {
      konzertList.querySelectorAll(".split-item").forEach((item, i) => {
        const pos = item.querySelector(".split-item-pos");
        if (pos) pos.textContent = i + 1;
      });
    }

    function ensurePositionNumber(item) {
      if (!item.querySelector(".split-item-pos")) {
        const pos = document.createElement("span");
        pos.className = "split-item-pos";
        item.insertBefore(pos, item.querySelector(".split-item-titel"));
      }
    }

    function removePositionNumber(item) {
      const pos = item.querySelector(".split-item-pos");
      if (pos) pos.remove();
    }

    const konzertSortable = new Sortable(konzertList, {
      group: { name: "shared" },
      animation: 150,
      ghostClass: "sortable-ghost",
      chosenClass: "sortable-chosen",
      handle: ".split-item-handle",
      onAdd(evt) {
        ensurePositionNumber(evt.item);
        updatePositions();
        var empty = konzertList.querySelector(".split-empty");
        if (empty) empty.remove();
      },
      onEnd: updatePositions,
      onRemove(evt) {
        updatePositions();
        if (!konzertList.querySelector(".split-item")) {
          var empty = document.createElement("div");
          empty.className = "split-empty";
          empty.textContent = "Keine Titel zugeordnet";
          konzertList.appendChild(empty);
        }
      },
    });

    const poolSortable = new Sortable(poolList, {
      group: { name: "shared" },
      animation: 150,
      ghostClass: "sortable-ghost",
      chosenClass: "sortable-chosen",
      handle: ".split-item-handle",
      onAdd(evt) {
        removePositionNumber(evt.item);
        var empty = poolList.querySelector(".split-empty");
        if (empty) empty.remove();
      },
      onRemove(evt) {
        if (!poolList.querySelector(".split-item")) {
          var empty = document.createElement("div");
          empty.className = "split-empty";
          empty.textContent = "Alle Titel zugeordnet";
          poolList.appendChild(empty);
        }
      },
    });

    window.sortable = konzertSortable;

    function saveOrder() {
      const order = [...konzertList.querySelectorAll(".split-item")].map(
        (item) => item.dataset.id,
      );
      fetch("/intern/update-order/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify({ order: order, konzert_id: konzertId }),
      });
    }

    window.saveOrder = saveOrder;

    // Split divider resize
    const divider = document.getElementById("split-divider");
    if (divider) {
      const panels = splitLayout.querySelectorAll(".split-panel");
      let isDragging = false;

      function isVertical() {
        return getComputedStyle(splitLayout).flexDirection === "column";
      }

      function getPointerPos(e) {
        var src = e.touches ? e.touches[0] : e;
        return isVertical() ? src.clientY : src.clientX;
      }

      function onPointerDown(e) {
        isDragging = true;
        divider.classList.add("dragging");
        document.body.style.cursor = isVertical() ? "row-resize" : "col-resize";
        document.body.style.userSelect = "none";
        e.preventDefault();
      }

      function onPointerMove(e) {
        if (!isDragging) return;
        var vert = isVertical();
        var containerRect = splitLayout.getBoundingClientRect();
        var dividerSize = vert ? divider.offsetHeight : divider.offsetWidth;
        var totalSize = (vert ? containerRect.height : containerRect.width) - dividerSize;
        var minSize = totalSize * 0.15;
        var pointerPos = getPointerPos(e) - (vert ? containerRect.top : containerRect.left);
        var firstSize = Math.max(minSize, Math.min(totalSize - minSize, pointerPos));
        var secondSize = totalSize - firstSize;
        if (vert) {
          panels[0].style.height = firstSize + "px";
          panels[0].style.width = "";
          panels[1].style.height = secondSize + "px";
          panels[1].style.width = "";
        } else {
          panels[0].style.width = firstSize + "px";
          panels[0].style.height = "";
          panels[1].style.width = secondSize + "px";
          panels[1].style.height = "";
        }
      }

      function onPointerUp() {
        if (!isDragging) return;
        isDragging = false;
        divider.classList.remove("dragging");
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }

      divider.addEventListener("mousedown", onPointerDown);
      divider.addEventListener("touchstart", onPointerDown, { passive: false });
      document.addEventListener("mousemove", onPointerMove);
      document.addEventListener("touchmove", onPointerMove, { passive: false });
      document.addEventListener("mouseup", onPointerUp);
      document.addEventListener("touchend", onPointerUp);

      // Clear inline sizes when switching between horizontal/vertical layout
      var mql = window.matchMedia("(max-width: 600px)");
      function clearInlineSizes() {
        panels.forEach(function (p) {
          p.style.width = "";
          p.style.height = "";
        });
      }
      mql.addEventListener("change", clearInlineSizes);
      clearInlineSizes();
    }
  }

  // ── Audio mini-player ─────────────────────────────────────
  (function initMiniPlayer() {
    const player = document.getElementById("mini-player");
    if (!player) return;

    const titleEl    = player.querySelector(".mp-title");
    const composerEl = player.querySelector(".mp-composer");
    const typeEl     = player.querySelector(".mp-type");
    const prevBtn    = player.querySelector(".mp-prev");
    const playBtn    = player.querySelector(".mp-play");
    const nextBtn    = player.querySelector(".mp-next");
    const currentEl  = player.querySelector(".mp-current");
    const totalEl    = player.querySelector(".mp-total");
    const progress   = player.querySelector(".mp-progress");
    const bar        = player.querySelector(".mp-progress-bar");
    const closeBtn   = player.querySelector(".mp-close");

    const ICON_PLAY  = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>';
    const ICON_PAUSE = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>';

    let audio = null;
    let activeBtn = null;
    let queue = [];
    let queueIndex = -1;
    // Der schwebende Player ist nur eine von mehreren Anzeigen: die Wiki-Artikel
    // betten Leisten (.wiki-player) in den Text ein, die dieselbe Wiedergabe
    // spiegeln. Es klingt immer nur eine Quelle — `audio`.
    let aktuellerItem = null;   // was gerade läuft, für den Abgleich mit den Leisten
    let trackAbbruch = null;    // AbortController für die Listener des laufenden Tracks
    let fremdesMedium = false;  // `audio` ist ein <video> aus dem DOM, kein new Audio()

    // ── Media Session (lock screen / OS media controls) ──────
    const HAS_MS = "mediaSession" in navigator;
    const ARTWORK = [
      { src: "/static/intern/brand/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/static/intern/brand/icon-512.png", sizes: "512x512", type: "image/png" },
    ];
    function msState(state) {
      if (HAS_MS) { try { navigator.mediaSession.playbackState = state; } catch (_) {} }
    }
    function msAction(action, handler) {
      if (HAS_MS) { try { navigator.mediaSession.setActionHandler(action, handler); } catch (_) {} }
    }
    function updateNavButtons() {
      const hasPrev = queue.length > 0 && queueIndex > 0;
      const hasNext = queue.length > 0 && queueIndex < queue.length - 1;
      prevBtn.disabled = !hasPrev;
      nextBtn.disabled = !hasNext;
    }
    function msMetadata(item) {
      if (!HAS_MS) return;
      try {
        navigator.mediaSession.metadata = new MediaMetadata({
          title: item.title || "",
          artist: item.composer || item.type || "",
          album: document.body.dataset.vereinsnameLang || "",
          artwork: ARTWORK,
        });
      } catch (_) {}
      const hasPrev = queueIndex > 0;
      const hasNext = queue.length > 0 && queueIndex < queue.length - 1;
      msAction("previoustrack", hasPrev ? playPrev : null);
      msAction("nexttrack",     hasNext ? playNext : null);
    }
    function playPrev() {
      if (queueIndex <= 0) return;
      queueIndex--;
      loadTrack(queue[queueIndex], advance);
    }
    function playNext() { advance(); }

    function fmt(t) {
      if (!isFinite(t) || t < 0) return "0:00";
      const m = Math.floor(t / 60);
      const s = Math.floor(t % 60).toString().padStart(2, "0");
      return `${m}:${s}`;
    }
    function setBtnPlaying(btn, playing) {
      if (!btn) return;
      btn.classList.toggle("playing", playing);
    }
    function setMainIcon(playing) {
      playBtn.innerHTML = playing ? ICON_PAUSE : ICON_PLAY;
    }

    // ── Inline-Leisten im Wikitext ───────────────────────────
    // Bewusst keine Registrierung: die Leisten werden bei jedem Rendern frisch
    // aus dem DOM geholt. Damit überleben sie htmx-Swaps, und es bleibt kein
    // Zustand zurück, der auf entfernte Knoten zeigt.
    function leisten() {
      return Array.from(document.querySelectorAll(".wiki-player"));
    }
    function leistenRendern() {
      const alle = leisten();
      if (!alle.length) return;
      const url = aktuellerItem ? aktuellerItem.url : null;
      const laeuft = !!(audio && !audio.paused);
      alle.forEach((l) => {
        const aktiv = !!audio && url !== null && l.dataset.url === url;
        l.classList.toggle("playing", aktiv);
        l.querySelector(".mp-play").innerHTML = (aktiv && laeuft) ? ICON_PAUSE : ICON_PLAY;
        l.querySelector(".mp-current").textContent = aktiv ? fmt(audio.currentTime) : "0:00";
        l.querySelector(".mp-total").textContent = aktiv ? fmt(audio.duration) : "0:00";
        l.querySelector(".mp-progress-bar").style.width =
          (aktiv && audio.duration) ? (audio.currentTime / audio.duration * 100) + "%" : "0%";
        l.querySelector(".mp-prev").disabled = !aktiv || queueIndex <= 0;
        l.querySelector(".mp-next").disabled = !aktiv || queueIndex >= queue.length - 1;
      });
    }
    // Das <video> einer Leiste, falls der Track zu einer gehört — die Engine
    // übernimmt es dann, statt ein eigenes Audio-Objekt zu bauen.
    function medienElement(url) {
      const treffer = leisten().find(
        (l) => l.dataset.typ === "video" && l.dataset.url === url
      );
      return treffer ? treffer.querySelector("video") : null;
    }
    function show() {
      player.classList.add("open");
      player.setAttribute("aria-hidden", "false");
    }
    function hide() {
      player.classList.remove("open");
      player.setAttribute("aria-hidden", "true");
    }
    function stop() {
      if (audio) { try { audio.pause(); } catch (_) {} }
      if (trackAbbruch) { trackAbbruch.abort(); trackAbbruch = null; }
      if (audio && fremdesMedium) { try { audio.currentTime = 0; } catch (_) {} }
      audio = null;
      fremdesMedium = false;
      aktuellerItem = null;
      setBtnPlaying(activeBtn, false);
      activeBtn = null;
      queue = [];
      queueIndex = -1;
      leistenRendern();
      bar.style.width = "0%";
      currentEl.textContent = "0:00";
      totalEl.textContent = "0:00";
      composerEl.textContent = "";
      setMainIcon(false);
      updateNavButtons();
      hide();
      msState("none");
      if (HAS_MS) { try { navigator.mediaSession.metadata = null; } catch (_) {} }
    }
    function loadTrack(item, onEnded) {
      if (audio) { try { audio.pause(); } catch (_) {} }
      // Ein wiederverwendetes <video> aus dem DOM behielte sonst die Listener
      // jedes vorigen Durchlaufs — bei new Audio() starben sie mit dem Objekt.
      if (trackAbbruch) trackAbbruch.abort();
      if (audio && fremdesMedium) { try { audio.currentTime = 0; } catch (_) {} }
      trackAbbruch = new AbortController();
      const opt = { signal: trackAbbruch.signal };
      aktuellerItem = item;
      titleEl.textContent = item.title || "";
      composerEl.textContent = item.composer || "";
      let typeText = item.type || "";
      if (queue.length > 1) {
        typeText += ` · ${queueIndex + 1} / ${queue.length}`;
      }
      typeEl.textContent = typeText;
      bar.style.width = "0%";
      currentEl.textContent = "0:00";
      totalEl.textContent = "0:00";
      updateNavButtons();
      // Gehört der Track zu einer Video-Leiste, spielt deren <video> — sonst
      // gäbe es Ton ohne Bild. HTMLVideoElement und HTMLAudioElement teilen
      // sich die HTMLMediaElement-API, alles darunter bleibt gleich.
      const medium = medienElement(item.url);
      fremdesMedium = !!medium;
      audio = medium || new Audio(item.url);
      audio.addEventListener("loadedmetadata", () => {
        totalEl.textContent = fmt(audio.duration);
        leistenRendern();
      }, opt);
      audio.addEventListener("timeupdate", () => {
        currentEl.textContent = fmt(audio.currentTime);
        if (audio.duration) {
          bar.style.width = (audio.currentTime / audio.duration * 100) + "%";
        }
        leistenRendern();
      }, opt);
      audio.addEventListener("ended", onEnded, opt);
      audio.addEventListener("error", () => {
        console.error("Error playing audio:", item.url);
        onEnded();
      }, opt);
      audio.addEventListener("play",  () => { msState("playing"); leistenRendern(); }, opt);
      audio.addEventListener("pause", () => { msState("paused");  leistenRendern(); }, opt);
      msMetadata(item);
      audio.play().catch((err) => {
        // Beim Weiterschalten in der Warteschlange fehlt die Nutzergeste —
        // manche Browser lehnen Autoplay dann ab. Die Leiste zeigt wieder Play.
        console.error("Audio play() rejected:", err);
        setMainIcon(false);
        leistenRendern();
      });
      if (medium) medium.scrollIntoView({ block: "nearest", behavior: "smooth" });
      setMainIcon(true);
      // Ein Video spielt in seiner Leiste, die schon die Steuerung trägt —
      // der schwebende Player daneben wäre eine zweite.
      if (medium) hide(); else show();
      leistenRendern();
    }
    function play(btn) {
      setBtnPlaying(activeBtn, false);
      queue = [];
      queueIndex = -1;
      activeBtn = btn;
      setBtnPlaying(btn, true);
      loadTrack({
        url: btn.dataset.audioUrl,
        title: btn.dataset.title || "",
        type: btn.dataset.type || "",
        composer: btn.dataset.composer || "",
      }, stop);
    }
    function advance() {
      queueIndex++;
      if (queueIndex < queue.length) {
        loadTrack(queue[queueIndex], advance);
      } else {
        stop();
      }
    }
    // `start` ist der Index, ab dem gespielt wird — die Wiki-Leisten starten
    // mitten in der Liste. Ohne dritten Parameter bleibt es beim Anfang.
    function playQueue(items, shuffle, start) {
      if (!items || !items.length) {
        alert("Keine spielbaren Audios in der Liste.");
        return;
      }
      setBtnPlaying(activeBtn, false);
      activeBtn = null;
      queue = items.slice();
      if (shuffle) {
        for (let i = queue.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          [queue[i], queue[j]] = [queue[j], queue[i]];
        }
      }
      queueIndex = shuffle ? 0 : Math.max(0, start || 0);
      loadTrack(queue[queueIndex], advance);
    }

    // Die Warteschlange eines Artikels sind seine Video-Leisten und
    // Audio-Figuren (.wiki-audio) in Dokumentreihenfolge. Sie kommt aus dem
    // DOM statt aus einem json_script: so spiegelt sie genau das, was der Leser sieht — auch in alten Versionen
    // eines Artikels — und die View muss den Wikitext nicht ein zweites Mal
    // auflösen.
    function artikelQueueStarten(leiste) {
      const bereich = leiste.closest(".wiki") || document;
      const alle = Array.from(bereich.querySelectorAll(".wiki-player, .wiki-audio"));
      const items = alle.map((l) => ({
        url: l.dataset.url,
        title: l.dataset.titel || "",
        type: l.dataset.typ === "video" ? "Video" : "Audio",
      }));
      playQueue(items, false, alle.indexOf(leiste));
    }
    // Für Aufrufer, die ihre Liste selbst mitbringen (Ordner-Kontextmenü) —
    // ein einzelner Titel ist einfach eine Warteschlange der Länge 1.
    window.startPlayQueue = function (items, shuffle) {
      playQueue(items, shuffle);
    };
    window.startPlaylist = function (shuffle) {
      const dataEl = document.getElementById("playlist-data");
      let items = [];
      if (dataEl) {
        try { items = JSON.parse(dataEl.textContent); } catch (_) { items = []; }
      }
      playQueue(items, shuffle);
    };
    // Warteschlangen einer Listenseite. Der Ordner bettet seine eine Liste ein
    // (#playlists-data); das Repertoire waeren 72 KB in jedem Seitenaufruf, also
    // traegt die Seite nur die Adresse und wir holen sie beim ersten Klick.
    let geholtePlaylists = null;
    window.startPlaylistType = async function (type, shuffle) {
      const dataEl = document.getElementById("playlists-data");
      let playlists = {};
      if (dataEl) {
        try { playlists = JSON.parse(dataEl.textContent); } catch (_) {}
      } else if (geholtePlaylists) {
        playlists = geholtePlaylists;
      } else {
        const urlEl = document.getElementById("playlists-url");
        if (urlEl && urlEl.dataset.url) {
          try {
            const antwort = await fetch(urlEl.dataset.url, { headers: { "X-Requested-With": "fetch" } });
            if (antwort.ok) playlists = geholtePlaylists = await antwort.json();
          } catch (_) { playlists = {}; }
        }
      }
      playQueue(playlists[type] || [], shuffle);
    };

    document.addEventListener("click", function (e) {
      const btn = e.target.closest && e.target.closest(".audio-btn");
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      if (btn === activeBtn && audio) {
        if (audio.paused) { audio.play(); setMainIcon(true); setBtnPlaying(btn, true); }
        else              { audio.pause(); setMainIcon(false); setBtnPlaying(btn, false); }
      } else {
        play(btn);
      }
    });

    // Die Knöpfe der Inline-Leisten. Bewusst nicht über .audio-btn: dessen
    // Handler leert die Warteschlange, hier soll sie gerade entstehen.
    document.addEventListener("click", function (e) {
      const leiste = e.target.closest && e.target.closest(".wiki-player");
      if (!leiste) return;
      const knopf = e.target.closest("button, .mp-progress");
      if (!knopf) return;
      e.preventDefault();
      const aktiv = !!aktuellerItem && aktuellerItem.url === leiste.dataset.url;
      if (knopf.classList.contains("mp-play")) {
        if (aktiv && audio) {
          if (audio.paused) audio.play(); else audio.pause();
        } else {
          artikelQueueStarten(leiste);
        }
      } else if (!aktiv || !audio) {
        return;  // Vor/Zurück/Suchlauf gehören zum laufenden Track
      } else if (knopf.classList.contains("mp-prev")) {
        if (queueIndex > 0) { queueIndex--; loadTrack(queue[queueIndex], advance); }
      } else if (knopf.classList.contains("mp-next")) {
        if (queueIndex < queue.length - 1) advance();
      } else if (knopf.classList.contains("mp-progress") && audio.duration) {
        const rect = knopf.getBoundingClientRect();
        const pct = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
        audio.currentTime = pct * audio.duration;
        leistenRendern();
      }
    });

    // Das Symbol einer Audio-Figur: startet die Warteschlange ab hier, beim
    // laufenden Titel schaltet es zwischen Pause und Wiedergabe.
    document.addEventListener("click", function (e) {
      const start = e.target.closest && e.target.closest(".wiki-audio-start");
      if (!start) return;
      const figur = start.closest(".wiki-audio");
      if (!figur) return;
      e.preventDefault();
      if (audio && aktuellerItem && aktuellerItem.url === figur.dataset.url) {
        if (audio.paused) { audio.play(); setMainIcon(true); }
        else              { audio.pause(); setMainIcon(false); }
      } else {
        artikelQueueStarten(figur);
      }
    });

    // Startet irgendein anderes Medium auf der Seite — etwa ein <audio controls>
    // aus einer externen URL im Wikitext —, schweigt unseres. Es soll nie mehr
    // als eine Quelle klingen. `play` bubbelt nicht, daher capture.
    document.addEventListener("play", function (e) {
      if (e.target === audio) return;
      if (audio && !audio.paused) {
        try { audio.pause(); } catch (_) {}
        setMainIcon(false);
        leistenRendern();
      }
    }, true);

    playBtn.addEventListener("click", () => {
      if (!audio) return;
      if (audio.paused) { audio.play(); setMainIcon(true); setBtnPlaying(activeBtn, true); }
      else              { audio.pause(); setMainIcon(false); setBtnPlaying(activeBtn, false); }
    });

    closeBtn.addEventListener("click", stop);

    prevBtn.addEventListener("click", () => {
      if (queueIndex > 0) { queueIndex--; loadTrack(queue[queueIndex], advance); }
    });
    nextBtn.addEventListener("click", () => {
      if (queueIndex < queue.length - 1) { advance(); }
    });

    progress.addEventListener("click", (e) => {
      if (!audio || !audio.duration) return;
      const rect = progress.getBoundingClientRect();
      const pct = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      audio.currentTime = pct * audio.duration;
    });

    msAction("play", () => {
      if (audio && audio.paused) { audio.play(); setMainIcon(true); setBtnPlaying(activeBtn, true); }
    });
    msAction("pause", () => {
      if (audio && !audio.paused) { audio.pause(); setMainIcon(false); setBtnPlaying(activeBtn, false); }
    });
    msAction("stop", stop);
  })();

  // ── Warnung vor brechenden Verweisen ──────────────────────
  // Wiki-Links zeigen auf den Dateinamen, Lied-/Forum-/Avatar-/Konfigurations-
  // einträge auf die Datei-ID: beides bricht beim Löschen bzw. Umbenennen.
  // Der Server sagt, was betroffen ist (datei_verwendung).
  async function verwendungenAbfragen(items, neuerName) {
    const body = new URLSearchParams();
    items.forEach((val) => body.append("item", val));
    if (neuerName) body.append("neuer_name", neuerName);
    try {
      const res = await fetch("/intern/datei/verwendung/", {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRFToken": getCsrfToken(),
        },
        body: body.toString(),
      });
      if (!res.ok) return [];
      const data = await res.json();
      return data.warnungen || [];
    } catch (err) {
      return []; // Prüfung ist Komfort, kein Wächter — nie den Ablauf blockieren
    }
  }

  // Kleiner Bestätigungsdialog auf <dialog>-Basis. Liefert den Wert des
  // geklickten Buttons (oder null bei Abbruch/Esc).
  // `auswahl` ({label, an}) setzt ein Häkchen über die Knöpfe; sein Stand
  // steht danach in `auswahl.an`.
  function verwendungsDialog({ titel, hinweis, warnungen, buttons, auswahl }) {
    return new Promise((resolve) => {
      const dlg = document.createElement("dialog");
      dlg.className = "verwendung-dialog";

      const h = document.createElement("h3");
      h.textContent = titel;
      dlg.appendChild(h);

      if (hinweis) {
        const p = document.createElement("p");
        p.className = "verwendung-hinweis";
        p.textContent = hinweis;
        dlg.appendChild(p);
      }

      (warnungen || []).forEach((w) => {
        const block = document.createElement("div");
        block.className = "verwendung-block";
        const name = document.createElement("strong");
        name.textContent = w.datei;
        block.appendChild(name);
        const ul = document.createElement("ul");
        (w.verwendungen || []).forEach((label) => {
          const li = document.createElement("li");
          li.textContent = label;
          ul.appendChild(li);
        });
        block.appendChild(ul);
        dlg.appendChild(block);
      });

      if (auswahl) {
        const label = document.createElement("label");
        label.className = "verwendung-auswahl";
        const box = document.createElement("input");
        box.type = "checkbox";
        box.checked = !!auswahl.an;
        box.addEventListener("change", () => { auswahl.an = box.checked; });
        label.appendChild(box);
        label.appendChild(document.createTextNode(" " + auswahl.label));
        dlg.appendChild(label);
      }

      const leiste = document.createElement("div");
      leiste.className = "verwendung-buttons";
      buttons.forEach((b) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn " + (b.klasse || "btn-secondary");
        btn.textContent = b.text;
        btn.addEventListener("click", () => { dlg.close(); resolve(b.wert); });
        leiste.appendChild(btn);
      });
      dlg.appendChild(leiste);

      dlg.addEventListener("cancel", () => resolve(null));
      dlg.addEventListener("close", () => dlg.remove());
      document.body.appendChild(dlg);
      dlg.showModal();
    });
  }

  // ── Ein Name, eine Datei: Rückfragen bei vergebenen Namen ──
  // Der Server (dateiablage) nennt je Konflikt Art und Wahl; hier wird nur
  // gefragt. Was ohne Wahl bleibt, überspringt er — nie wird still verschmolzen.
  const ABLAGE_WAHL = {
    verschmelzen: { text: "Verschmelzen", klasse: "btn-primary" },
    jetzt:        { text: "Datum auf jetzt", klasse: "btn-primary" },
    einsortieren: { text: "Datum lassen und einsortieren" },
    loeschen:     { text: "Weiter (hier löschen)", klasse: "btn-danger" },
  };

  function ablageFrage(aktion, k) {
    const wo = `„${k.datei}“ in ${k.ordner}`;
    if (k.art === "name") {
      return { titel: `${wo} gibt es schon`,
               hinweis: aktion === "umbenennen"
                 ? "Diese Datei wird eine Fassung der vorhandenen und steht vorne."
                 : "Die hinzukommende Datei wird die vordere Fassung der vorhandenen — danach sind beide eine Datei." };
    }
    if (k.art === "name_aelter") {
      return { titel: `${wo} ist jünger`,
               hinweis: `Stand dort: ${k.ziel_datum}, hinzukommend: ${k.eingehend_datum}. ` +
                        "Damit die hinzukommende vorne steht, bekommt sie das Datum von jetzt — " +
                        "oder sie wird nach ihrem Datum als ältere Fassung einsortiert." };
    }
    if (aktion === "verschieben") {   // identisch oder dieselbe Datei
      return { titel: "Eine identische Datei liegt bereits im Ziel",
               hinweis: `${wo}. Weiter löscht sie hier.` };
    }
    return { titel: `${wo} hat denselben Inhalt`,
             hinweis: "Verschmelzen legt keine neue Fassung an — danach sind beide eine Datei." };
  }

  // Konflikte ohne Wahl: was nicht abgelegt wird. Kopieren auf einen
  // vergebenen Namen fragt nicht — die Kopie wird dort neue Fassung.
  function ablageHinweis(aktion, k) {
    const wo = `„${k.datei}“ in ${k.ordner}`;
    if (k.art === "ordnername") return `Den Ordner ${wo} gibt es schon — er bleibt, wo er ist.`;
    if (k.art === "in_sich_selbst") {
      return `Der Ordner „${k.datei}“ kann nicht in sich selbst oder einen eigenen Unterordner — er bleibt, wo er ist.`;
    }
    if (k.art === "gesperrt") return `${wo} darfst du nicht ändern — wird übersprungen.`;
    if (aktion === "verknuepfen" && k.art === "vorhanden") return `${wo} liegt dort schon.`;
    if (aktion === "kopieren" && (k.art === "identisch" || k.art === "vorhanden")) {
      return `${wo} hat schon diesen Inhalt — wird nicht abgelegt.`;
    }
    return null;
  }

  // Fragt jeden Konflikt ab; liefert die Felder `entscheidung` („Schlüssel=Wahl")
  // oder null, wenn der ganze Vorgang abgebrochen wurde.
  async function konflikteKlaeren(aktion, konflikte) {
    const hinweise = [], fragen = [], entscheidungen = [], fuerAlle = {};
    konflikte.forEach((k) => {
      const h = ablageHinweis(aktion, k);
      if (h) hinweise.push(h);
      else if (k.optionen && k.optionen.length) fragen.push(k);
    });
    for (let i = 0; i < fragen.length; i++) {
      const k = fragen[i];
      let wert = fuerAlle[k.art];
      if (wert === undefined) {
        const { titel, hinweis } = ablageFrage(aktion, k);
        const weitere = fragen.slice(i + 1).some((x) => x.art === k.art);
        const auswahl = weitere ? { label: "Für alle weiteren gleichen Fälle übernehmen", an: false } : null;
        const buttons = [{ text: "Abbrechen", wert: "abbrechen" }].concat(
          k.optionen.slice().reverse().map((w) => ({
            text: aktion === "umbenennen" && w === "verschmelzen"
              ? "Wird Version dieser Datei" : ABLAGE_WAHL[w].text,
            klasse: ABLAGE_WAHL[w].klasse,
            wert: w,
          })),
        );
        wert = (await verwendungsDialog({ titel, hinweis, buttons, auswahl })) || "abbrechen";
        if (auswahl && auswahl.an) fuerAlle[k.art] = wert;
      }
      entscheidungen.push(`${k.schluessel}=${wert}`);
    }
    if (hinweise.length) {
      const weiter = await verwendungsDialog({
        titel: "Nicht alles wird abgelegt",
        warnungen: [{ datei: "", verwendungen: hinweise }],
        buttons: [
          { text: "Abbrechen", wert: null },
          { text: "Weiter", wert: "ok", klasse: "btn-primary" },
        ],
      });
      if (weiter !== "ok") return null;
    }
    return entscheidungen;
  }

  // Vorabprüfung für Verschieben, Referenz und Kopieren (auch aus dem
  // Datei-Menü eines Artikels). Ohne Antwort des Servers bleibt die Liste
  // leer — dann überspringt er die Konflikte selbst.
  window.ablageKlaeren = async function (aktion, items, zielPk) {
    const body = new URLSearchParams();
    body.append("aktion", aktion);
    body.append("target_pk", zielPk || "0");
    items.forEach((val) => body.append("item", val));
    let konflikte = [];
    try {
      const res = await fetch("/intern/ordner/konflikte/", {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRFToken": getCsrfToken(),
        },
        body: body.toString(),
      });
      if (res.ok) konflikte = (await res.json()).konflikte || [];
    } catch (err) { /* der Server prüft beim Absenden erneut */ }
    return konflikteKlaeren(aktion, konflikte);
  };

  function entscheidungenAnhaengen(form, liste) {
    form.querySelectorAll('input[name="entscheidung"]').forEach((el) => el.remove());
    liste.forEach((wert) => {
      const inp = document.createElement("input");
      inp.type = "hidden"; inp.name = "entscheidung"; inp.value = wert;
      form.appendChild(inp);
    });
  }

  // File actions: delete / move / copy (= link) / duplicate / zip
  window.fileAction = async function (action) {
    const formId = action === "delete"    ? "delete-form"
                 : action === "move"      ? "move-form"
                 : action === "link"       ? "link-form"
                 : action === "duplicate" ? "duplicate-form"
                 : action === "zip"       ? "zip-form"
                 :                          null;
    if (!formId) return;
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
      // Deleting removes the entry here; a file linked into further folders
      // keeps existing there — filer only drops the blob with the last link.
      const hinweis = "Dateien, die zusätzlich in anderen Ordnern verknüpft " +
                      "sind, bleiben dort erhalten.";
      const warnungen = await verwendungenAbfragen(items);
      if (warnungen.length) {
        const wahl = await verwendungsDialog({
          titel: `${items.length} Element(e) löschen?`,
          hinweis: "Diese Verweise gehen dabei ins Leere:",
          warnungen,
          buttons: [
            { text: "Abbrechen", wert: null },
            { text: "Trotzdem löschen", wert: "ok", klasse: "btn-danger" },
          ],
        });
        if (wahl !== "ok") return;
      } else if (!confirm(`${items.length} Element(e) wirklich löschen?\n\n${hinweis}`)) {
        return;
      }
    } else if (action !== "zip") {
      const targetRadio = document.querySelector('input[name="folder-target"]:checked');
      if (!targetRadio) { alert("Bitte erst einen Zielordner auswählen."); return; }
      const targetInput = document.getElementById(
        action === "move" ? "move-target"
        : action === "duplicate" ? "duplicate-target"
        : "link-target"
      );
      if (targetInput) targetInput.value = targetRadio.value;
      const aktion = { move: "verschieben", link: "verknuepfen", duplicate: "kopieren" }[action];
      const entscheidungen = await window.ablageKlaeren(aktion, items, targetRadio.value);
      if (entscheidungen === null) return;
      entscheidungenAnhaengen(form, entscheidungen);
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
      // Backstage und darunter: kein Ziel fürs Verschieben (der Server lehnt ab).
      const gesperrt = (moveForm.dataset.gesperrteZiele || "").split(",").includes(targetPk);

      row.addEventListener("dragover", (e) => {
        const isExternalFile = e.dataTransfer.types.includes("Files");
        if (gesperrt && !isExternalFile) return;
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
          e.stopPropagation();
          document.getElementById("app-main")?.classList.remove("drag-active");
          uploadFilesToFolder(e.dataTransfer.files, targetPk);
          return;
        }

        if (gesperrt) return;

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
      const promises = [...files].map((file) => {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("folder_id", targetPk);
        return fetch("/intern/upload/", {
          method: "POST",
          headers: { "X-CSRFToken": getCsrfToken() },
          body: formData,
        });
      });
      Promise.all(promises).then(() => refreshFolderTable());
    }

    async function submitDragMove(items, targetPk) {
      const entscheidungen = await window.ablageKlaeren("verschieben", items, targetPk);
      if (entscheidungen === null) return;
      entscheidungenAnhaengen(moveForm, entscheidungen);
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

  // ── Row context menu (right-click / long-press) ─────────
  (function initRowContextMenu() {
    const tbody = document.querySelector(".table-container tbody");
    if (!tbody) return;
    const actionPanel = document.getElementById("Action");
    if (!actionPanel || !actionPanel.dataset.canWrite) return; // only on folder views
    const canWrite = actionPanel.dataset.canWrite === "true";
    const canDelete = actionPanel.dataset.canDelete === "true";

    // Sprung aus dem Datei-Menü eines Artikels (`?datei=<pk>`): die Ansicht
    // hat die erste Seite bis zu dieser Zeile verlängert, hier wird sie gezeigt.
    const sprung = new URLSearchParams(window.location.search).get("datei");
    const sprungZeile = sprung &&
      tbody.querySelector(`tr[data-type="File"][data-id="${CSS.escape(sprung)}"]`);
    if (sprungZeile) {
      sprungZeile.classList.add("zeile-markiert");
      sprungZeile.scrollIntoView({ block: "center" });
    }

    // Dieselben Icons wie die Aktions-Buttons im Panel (table.html) — Menü und
    // Panel benennen und bebildern dieselben Aktionen gleich.
    const S = 'xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
    const ICON = {
      umbenennen:  `<svg ${S}><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>`,
      zip:         `<svg ${S}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`,
      verschieben: `<svg ${S}><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>`,
      verknuepfen: `<svg ${S}><path d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>`,
      duplizieren: `<svg ${S}><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`,
      entpacken:   `<svg ${S}><path d="M21 8v13H3V8"/><rect x="1" y="3" width="22" height="5" rx="1"/><line x1="10" y1="12" x2="14" y2="12"/></svg>`,
      loeschen:    `<svg ${S}><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>`,
      abspielen:   `<svg ${S}><circle cx="12" cy="12" r="9"/><polygon points="10 8 17 12 10 16" fill="currentColor" stroke="none"/></svg>`,
      zufall:      `<svg ${S}><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>`,
      galerie:     `<svg ${S}><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>`,
      historie:    `<svg ${S}><path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><polyline points="12 7 12 12 15 14"/></svg>`,
    };

    // Die Playlist eines Ordners wird erst beim Klick geholt — sie für jeden
    // sichtbaren Unterordner mitzurendern, blähte die Seite unnötig auf.
    async function ordnerAbspielen(id, shuffle) {
      try {
        const res = await fetch("/intern/ordner/" + id + "/playlist/", {
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        if (!res.ok) { alert("Playlist konnte nicht geladen werden."); return; }
        const data = await res.json();
        if (window.startPlayQueue) window.startPlayQueue(data.items || [], shuffle);
      } catch (err) {
        alert("Netzwerkfehler beim Laden der Playlist.");
      }
    }

    function rowFrom(target) {
      const tr = target.closest("tr");
      if (!tr || !tr.dataset.id || !tr.dataset.type) return null;
      return tr;
    }

    let menuEl = null;
    function closeMenu() {
      if (menuEl) { menuEl.remove(); menuEl = null; }
    }

    // Zeile markieren und das Auswahl-Panel zeigen. Nicht toggle() — war schon
    // eine andere Zeile markiert, ist das Panel offen und toggle() würde es
    // schliessen statt es zu zeigen.
    function auswahlPanelOeffnen(tr) {
      const cb = tr.querySelector('input[type="checkbox"][name="select"]');
      if (cb && !cb.checked) { cb.checked = true; updateSelectionState(); }
      document.querySelectorAll(".offcanvas.open").forEach((el) => {
        if (el !== actionPanel) el.classList.remove("open");
      });
      actionPanel.classList.add("open");
    }

    function openMenu(tr, x, y) {
      closeMenu();
      const id = tr.dataset.id;
      const type = tr.dataset.type;
      const name = tr.dataset.name || "";
      const isZip = type === "File" && name.toLowerCase().endsWith(".zip");

      menuEl = document.createElement("div");
      menuEl.className = "context-menu";
      const medien = [];   // was diese Datei betrifft
      const above = [];    // Verwaltung
      const ordner = [];   // was den ganzen Ordner betrifft
      const below = [];

      if (tr.dataset.audio === "1" && tr.dataset.url) {
        medien.push({ label: "Abspielen", icon: ICON.abspielen, action: () => {
          if (window.startPlayQueue) {
            window.startPlayQueue([{ url: tr.dataset.url, title: name, type: "", composer: "" }]);
          }
        }});
      }
      if (tr.dataset.versionen === "1") {
        medien.push({ label: "Frühere Versionen", icon: ICON.historie,
                      title: "Versionshistorie dieser Datei anzeigen",
                      action: () => { window.location.href = "/intern/datei/" + id + "/"; }});
      }

      if (canWrite) {
        above.push({ label: "Umbenennen", icon: ICON.umbenennen,
                     action: () => startInlineRename(tr, type, id, name) });
      }
      if (type === "Folder") {
        above.push({ label: "Als ZIP herunterladen", icon: ICON.zip, action: () => {
          window.location.href = "/intern/ordner/" + id + "/zip/";
        }});
      }
      if (canWrite) {
        above.push({
          label: "Verschieben nach…", icon: ICON.verschieben,
          title: "Element wird hier entfernt und liegt danach nur noch im Zielordner",
          action: () => auswahlPanelOeffnen(tr),
        });
        above.push({
          label: "Verknüpfen nach…", icon: ICON.verknuepfen,
          title: "Dieselbe Datei erscheint zusätzlich im Zielordner — Änderungen wirken überall",
          action: () => auswahlPanelOeffnen(tr),
        });
        above.push({
          label: "Duplizieren nach…", icon: ICON.duplizieren,
          title: "Unabhängige Kopie mit eigenem Inhalt",
          action: () => auswahlPanelOeffnen(tr),
        });
        if (isZip) {
          above.push({ label: "Entpacken", icon: ICON.entpacken, action: () => submitUnzip(id) });
        }
      }
      // Was den ganzen Ordner betrifft, hängt am Ordner — nicht an einer Datei
      // darin. Der geöffnete Ordner hat keine eigene Zeile; für ihn sind die
      // beiden Knöpfe in der Topbar zuständig.
      if (type === "Folder") {
        const audios = parseInt(tr.dataset.audios, 10) || 0;
        const bilder = parseInt(tr.dataset.bilder, 10) || 0;
        if (audios) {
          ordner.push({ label: `Alle ${audios} Audios abspielen`, icon: ICON.abspielen,
                        action: () => ordnerAbspielen(id, false) });
          ordner.push({ label: `Alle ${audios} Audios zufällig abspielen`, icon: ICON.zufall,
                        action: () => ordnerAbspielen(id, true) });
        }
        if (bilder) {
          ordner.push({ label: `Alle ${bilder} Bilder als Galerie anzeigen`, icon: ICON.galerie,
                        action: () => { window.location.href = "/intern/gallerie/" + id + "/"; }});
        }
      }

      if (canDelete) {
        below.push({ label: "Löschen", icon: ICON.loeschen, danger: true,
                     action: () => submitDelete(type, id, name) });
      }

      const allItems = [];
      for (const gruppe of [medien, above, ordner, below]) {
        if (!gruppe.length) continue;
        if (allItems.length) allItems.push({ sep: true });
        allItems.push(...gruppe);
      }

      if (!allItems.length) { menuEl = null; return; }

      // Kopfzeile mit dem Namen des Elements — wie das "N ausgewählt" im Panel.
      const kopf = document.createElement("div");
      kopf.className = "context-menu-header";
      kopf.textContent = name || (type === "Folder" ? "Ordner" : "Datei");
      menuEl.appendChild(kopf);

      for (const it of allItems) {
        if (it.sep) {
          const s = document.createElement("div");
          s.className = "context-menu-sep";
          menuEl.appendChild(s);
          continue;
        }
        const b = document.createElement("button");
        b.type = "button";
        b.className = "context-menu-item" + (it.danger ? " danger" : "");
        if (it.title) b.title = it.title;
        if (it.icon) b.insertAdjacentHTML("beforeend", it.icon);
        b.appendChild(document.createTextNode(it.label));
        b.addEventListener("click", () => { closeMenu(); it.action(); });
        menuEl.appendChild(b);
      }

      document.body.appendChild(menuEl);
      const rect = menuEl.getBoundingClientRect();
      const maxX = window.innerWidth - rect.width - 4;
      const maxY = window.innerHeight - rect.height - 4;
      menuEl.style.left = Math.max(4, Math.min(x, maxX)) + "px";
      menuEl.style.top = Math.max(4, Math.min(y, maxY)) + "px";
    }

    function submitDelete(type, id, name) {
      const deleteForm = document.getElementById("delete-form");
      if (!deleteForm) return;
      if (!confirm(`"${name}" wirklich löschen?`)) return;
      deleteForm.querySelectorAll('input[name="item"]').forEach((el) => el.remove());
      const inp = document.createElement("input");
      inp.type = "hidden"; inp.name = "item"; inp.value = type + ":" + id;
      deleteForm.appendChild(inp);
      deleteForm.submit();
    }

    function submitUnzip(id) {
      const f = document.createElement("form");
      f.method = "POST";
      f.action = "/intern/file/" + id + "/entpacken/";
      const tok = document.createElement("input");
      tok.type = "hidden"; tok.name = "csrfmiddlewaretoken"; tok.value = getCsrfToken();
      f.appendChild(tok);
      document.body.appendChild(f);
      f.submit();
    }

    function startInlineRename(tr, type, id, oldName) {
      // The name cell has <a>TEXT</a>; the icon cell has <a><img></a>. Pick the text one.
      const link = Array.from(tr.querySelectorAll("td a")).find((a) => !a.querySelector("img"));
      const cell = link ? link.parentElement : null;
      if (!cell || !link) return;

      const input = document.createElement("input");
      input.type = "text";
      input.className = "rename-input";
      input.value = oldName;
      const originalHTML = cell.innerHTML;
      cell.innerHTML = "";
      cell.appendChild(input);
      input.focus();
      // Preselect the stem for files (before the last dot) — folders get full selection.
      if (type === "File" && oldName.includes(".")) {
        input.setSelectionRange(0, oldName.lastIndexOf("."));
      } else {
        input.select();
      }

      let finished = false;
      let laeuft = false;   // Enter + blur dürfen commit() nicht zweimal starten
      function restore() {
        if (finished) return;
        finished = true;
        cell.innerHTML = originalHTML;
      }

      async function commit() {
        if (finished || laeuft) return;
        laeuft = true;
        const newName = input.value.trim();
        if (!newName || newName === oldName) { restore(); return; }

        // Wiki-Links zeigen auf den Dateinamen — vor dem Umbenennen fragen,
        // ob sie mitgezogen werden sollen.
        let mitziehen = false;
        if (type === "File") {
          const warnungen = await verwendungenAbfragen([`File:${id}`], newName);
          if (warnungen.length) {
            const wahl = await verwendungsDialog({
              titel: `„${oldName}“ umbenennen in „${newName}“?`,
              hinweis: "Diese Wiki-Links zeigen auf den bisherigen Dateinamen:",
              warnungen,
              buttons: [
                { text: "Abbrechen", wert: null },
                { text: "Nur umbenennen", wert: "nur" },
                { text: "Links mitziehen", wert: "mitziehen", klasse: "btn-primary" },
              ],
            });
            if (wahl === null) { restore(); return; }
            mitziehen = wahl === "mitziehen";
          }
        }

        try {
          const body = new URLSearchParams({ type, id, name: newName });
          if (mitziehen) body.append("links_mitziehen", "1");
          const senden = () => fetch("/intern/ordner/umbenennen/", {
            method: "POST",
            headers: {
              "Content-Type": "application/x-www-form-urlencoded",
              "X-CSRFToken": getCsrfToken(),
            },
            body: body.toString(),
          });
          let res = await senden();
          let data = await res.json().catch(() => ({}));
          // Der Name ist in einem Ordner der Datei vergeben: fragen, ob sie dort
          // Fassung der vorhandenen wird — sonst bleibt alles, wie es war.
          if (res.status === 409 && data.konflikte) {
            const entscheidungen = await konflikteKlaeren("umbenennen", data.konflikte);
            if (entscheidungen === null || entscheidungen.some((e) => e.endsWith("=abbrechen"))) {
              restore();
              return;
            }
            entscheidungen.forEach((e) => body.append("entscheidung", e));
            res = await senden();
            data = await res.json().catch(() => ({}));
          }
          if (data.status === "abgebrochen") { restore(); return; }
          if (!res.ok) {
            alert(data.message || "Umbenennen fehlgeschlagen.");
            restore();
            return;
          }
          if (data.links_uebersprungen && data.links_uebersprungen.length) {
            alert("Diese Artikel durftest du nicht bearbeiten, ihre Links zeigen " +
                  "weiterhin auf den alten Namen:\n\n" +
                  data.links_uebersprungen.join("\n"));
          }
          finished = true;
          // Verschmolzen: die Zeile kann in einer anderen aufgegangen sein.
          if (data.verschmolzen) { refreshFolderTable(); return; }
          const newLink = link.cloneNode(false);
          newLink.textContent = data.name || newName;
          cell.innerHTML = "";
          cell.appendChild(newLink);
          tr.dataset.name = data.name || newName;
        } catch (err) {
          alert("Netzwerkfehler beim Umbenennen.");
          restore();
        }
      }

      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); commit(); }
        else if (e.key === "Escape") { e.preventDefault(); restore(); }
      });
      input.addEventListener("blur", () => { if (!finished) commit(); });
    }

    tbody.addEventListener("contextmenu", (e) => {
      const tr = rowFrom(e.target);
      if (!tr) return;
      e.preventDefault();
      openMenu(tr, e.clientX, e.clientY);
    });

    // Long-press for touch
    let touchTimer = null;
    let touchTr = null;
    let touchStart = null;
    tbody.addEventListener("touchstart", (e) => {
      const tr = rowFrom(e.target);
      if (!tr) return;
      touchTr = tr;
      const t = e.touches[0];
      touchStart = { x: t.clientX, y: t.clientY };
      touchTimer = setTimeout(() => {
        openMenu(tr, touchStart.x, touchStart.y);
        touchTimer = null;
      }, 500);
    }, { passive: true });
    function cancelTouch() {
      if (touchTimer) { clearTimeout(touchTimer); touchTimer = null; }
      touchTr = null;
    }
    tbody.addEventListener("touchmove", (e) => {
      if (!touchTimer || !touchStart) return;
      const t = e.touches[0];
      if (Math.abs(t.clientX - touchStart.x) > 8 || Math.abs(t.clientY - touchStart.y) > 8) {
        cancelTouch();
      }
    }, { passive: true });
    tbody.addEventListener("touchend", cancelTouch);
    tbody.addEventListener("touchcancel", cancelTouch);

    document.addEventListener("click", (e) => {
      if (menuEl && !menuEl.contains(e.target)) closeMenu();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeMenu();
    });
    window.addEventListener("scroll", closeMenu, true);
    window.addEventListener("resize", closeMenu);
  })();

  // ── Repertoire-Zeile: Rechtsklick-Download-Menü ──────────
  (function initRepertoireContextMenu() {
    const S = 'xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
    const SVG_PLAY  = `<svg ${S}><circle cx="12" cy="12" r="9"/><polygon points="10 8 18 12 10 16" fill="currentColor" stroke="none"/></svg>`;
    const SVG_DL    = `<svg ${S}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`;
    const SVG_PDF   = `<svg ${S}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="13" y2="17"/></svg>`;
    const SVG_NOTEN = `<svg ${S}><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>`;
    const jgLogoEl  = document.querySelector(".audio-btn-logo");
    const JG_ICON   = jgLogoEl
      ? `<img src="${jgLogoEl.src}" width="18" height="18" alt="" aria-hidden="true"/>`
      : SVG_NOTEN;

    const menu = document.createElement("div");
    menu.className = "dl-menu dl-context-menu";
    menu.setAttribute("role", "menu");
    document.body.appendChild(menu);

    function esc(s) {
      return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
    }

    function buildMenu(tr) {
      const titel       = tr.dataset.titel       || "";
      const komponist   = tr.dataset.komponist   || "";
      const liedId      = tr.dataset.liedId      || "";
      const originalUrl = tr.dataset.originalUrl || "";
      const aufnahmeUrl = tr.dataset.aufnahmeUrl || "";
      const pdfUrl      = tr.dataset.pdfUrl      || "";
      const notenUrl    = tr.dataset.notenUrl    || "";

      if (!originalUrl && !aufnahmeUrl && !pdfUrl && !notenUrl) return false;

      let h = `<div class="dl-menu-header">${esc(titel)}</div>`;

      // Show play section only when Audio column is hidden (buttons not already in row)
      const audioColumnHidden = !tr.querySelector(".audio-btn");
      if (audioColumnHidden && (originalUrl || aufnahmeUrl)) {
        h += '<div class="dl-group-label">Abspielen</div>';
        if (originalUrl) {
          h += `<a href="#" class="dl-item"
            data-ctx-url="${esc(originalUrl)}" data-ctx-id="${esc(liedId)}"
            data-ctx-kind="original" data-ctx-title="${esc(titel)}"
            data-ctx-composer="${esc(komponist)}">
            <span class="dl-item-icon dl-icon-audio">${SVG_PLAY}</span>
            <span class="dl-item-body">
              <span class="dl-item-title">Original abspielen</span>
              <span class="dl-item-sub">MP3</span>
            </span></a>`;
        }
        if (aufnahmeUrl) {
          h += `<a href="#" class="dl-item"
            data-ctx-url="${esc(aufnahmeUrl)}" data-ctx-id="r${esc(liedId)}"
            data-ctx-kind="jg" data-ctx-title="${esc(titel)}"
            data-ctx-composer="${esc(komponist)}">
            <span class="dl-item-icon dl-icon-jg-rec">${JG_ICON}</span>
            <span class="dl-item-body">
              <span class="dl-item-title">JG Aufnahme abspielen</span>
              <span class="dl-item-sub">MP3</span>
            </span></a>`;
        }
      }

      h += '<div class="dl-group-label">Herunterladen</div>';
      if (originalUrl) {
        h += `<a href="${esc(originalUrl)}" download class="dl-item">
          <span class="dl-item-icon dl-icon-audio">${SVG_DL}</span>
          <span class="dl-item-body">
            <span class="dl-item-title">Original</span>
            <span class="dl-item-sub">MP3</span>
          </span></a>`;
      }
      if (aufnahmeUrl) {
        h += `<a href="${esc(aufnahmeUrl)}" download class="dl-item">
          <span class="dl-item-icon dl-icon-jg-rec">${JG_ICON}</span>
          <span class="dl-item-body">
            <span class="dl-item-title">JG Aufnahme</span>
            <span class="dl-item-sub">MP3</span>
          </span></a>`;
      }
      if (pdfUrl) {
        h += `<a href="${esc(pdfUrl)}" download class="dl-item">
          <span class="dl-item-icon dl-icon-pdf">${SVG_PDF}</span>
          <span class="dl-item-body">
            <span class="dl-item-title">Notenblatt</span>
            <span class="dl-item-sub">PDF</span>
          </span></a>`;
      }
      if (notenUrl) {
        h += `<a href="${esc(notenUrl)}" download class="dl-item">
          <span class="dl-item-icon dl-icon-noten">${SVG_NOTEN}</span>
          <span class="dl-item-body">
            <span class="dl-item-title">Notensatz</span>
            <span class="dl-item-sub">Noten</span>
          </span></a>`;
      }

      menu.innerHTML = h;
      return true;
    }

    function triggerPlay(btn) {
      const tmp = document.createElement("button");
      tmp.className = "audio-btn audio-btn--" + btn.dataset.ctxKind;
      tmp.dataset.audioUrl = btn.dataset.ctxUrl;
      tmp.dataset.songId   = btn.dataset.ctxId;
      tmp.dataset.title    = btn.dataset.ctxTitle;
      tmp.dataset.type     = btn.dataset.ctxKind === "jg" ? "JG Aufnahme" : "Original";
      tmp.dataset.composer = btn.dataset.ctxComposer || "";
      tmp.style.cssText    = "position:fixed;opacity:0;pointer-events:none;top:-9999px;left:-9999px;";
      document.body.appendChild(tmp);
      tmp.click();
      document.body.removeChild(tmp);
    }

    function show(x, y) {
      const w = menu.offsetWidth, h = menu.offsetHeight;
      const vw = window.innerWidth, vh = window.innerHeight;
      menu.style.left = Math.min(x, Math.max(0, vw - w - 8)) + "px";
      menu.style.top  = Math.min(y, Math.max(0, vh - h - 8)) + "px";
      menu.classList.add("open");
    }

    function closeMenu() { menu.classList.remove("open"); }

    let suppressNextClose = false;

    document.addEventListener("contextmenu", function(e) {
      const tr = e.target.closest("tr[data-lied-id]");
      if (!tr) { closeMenu(); return; }
      closeMenu();
      if (!buildMenu(tr)) return;
      e.preventDefault();
      show(e.clientX, e.clientY);
      // Guard: some OS/browser combos fire click after contextmenu on interactive
      // elements (e.g. audio-btn). That click would immediately close the menu.
      suppressNextClose = true;
      setTimeout(function() { suppressNextClose = false; }, 300);
    });

    menu.addEventListener("click", function(e) {
      const playBtn = e.target.closest("[data-ctx-kind]");
      if (playBtn) {
        e.preventDefault();
        triggerPlay(playBtn);
      }
      closeMenu();
    });

    document.addEventListener("click", function(e) {
      if (suppressNextClose) return;
      if (!menu.contains(e.target)) closeMenu();
    });

    document.addEventListener("keydown", function(e) {
      if (e.key === "Escape") closeMenu();
    });

    window.addEventListener("scroll", closeMenu, true);
    window.addEventListener("resize", closeMenu);
  })();

  // Add event listener for save order button
  const saveOrderButton = document.getElementById("saveOrderButton");
  if (saveOrderButton) {
    saveOrderButton.addEventListener("click", function () {
      if (typeof window.saveOrder !== "undefined") {
        window.saveOrder();
        const btn = saveOrderButton;
        const orig = btn.textContent;
        btn.textContent = "Gespeichert";
        btn.disabled = true;
        setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 1500);
      }
    });
  }

});

// ── Wiki link autocomplete ([[Datei:...]] and [[Artikel-Links]]) ──
(function initFileAutocomplete() {
  const DEBOUNCE_MS = 300;
  const MIN_QUERY_LEN = 1;

  let dropdownEl = null;
  let currentResults = [];
  let selectedIndex = 0;
  let currentMatch = null;
  let debounceTimer = null;
  let activeTextarea = null;

  // Hidden mirror div for caret position calculation
  const mirror = document.createElement("div");
  mirror.style.cssText =
    "position:absolute;visibility:hidden;pointer-events:none;white-space:pre-wrap;word-wrap:break-word;overflow:hidden;";
  document.body.appendChild(mirror);

  function detectPattern(ta) {
    const pos = ta.selectionStart;
    const text = ta.value;
    const before = text.substring(0, pos);
    const openIdx = before.lastIndexOf("[[");
    if (openIdx === -1) return null;
    // No closing ]] between [[ and cursor
    if (before.substring(openIdx).indexOf("]]") !== -1) return null;
    const afterOpen = before.substring(openIdx + 2);
    // File reference: [[Datei:<query>]]
    const fileM = afterOpen.match(/^Datei:(.*)/i);
    if (fileM) {
      const query = fileM[1];
      if (query.length < MIN_QUERY_LEN) return null;
      return {
        kind: "datei",
        prefixStart: openIdx,
        queryStart: openIdx + 2 + 6, // after "[[Datei:"
        queryText: query,
      };
    }
    // Article link: [[<query> — bail on chars that would break the link
    if (/[[\]|\n]/.test(afterOpen)) return null;
    if (afterOpen.length < MIN_QUERY_LEN) return null;
    return {
      kind: "artikel",
      prefixStart: openIdx,
      queryStart: openIdx + 2,
      queryText: afterOpen,
    };
  }

  function getCaretPos(ta, charIndex) {
    const cs = getComputedStyle(ta);
    const props = [
      "font", "fontFamily", "fontSize", "fontWeight", "lineHeight",
      "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
      "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth",
      "boxSizing", "width", "letterSpacing",
    ];
    props.forEach((p) => (mirror.style[p] = cs[p]));
    // Handle border-box width
    if (cs.boxSizing === "border-box") {
      mirror.style.width = cs.width;
    } else {
      mirror.style.width = (
        parseFloat(cs.width) -
        parseFloat(cs.paddingLeft) -
        parseFloat(cs.paddingRight) -
        parseFloat(cs.borderLeftWidth) -
        parseFloat(cs.borderRightWidth)
      ) + "px";
    }
    mirror.textContent = ta.value.substring(0, charIndex);
    const span = document.createElement("span");
    span.textContent = "|";
    mirror.appendChild(span);
    return { left: span.offsetLeft, top: span.offsetTop, height: span.offsetHeight };
  }

  async function fetchResults(query) {
    try {
      const resp = await fetch("/intern/file-search/?q=" + encodeURIComponent(query));
      if (!resp.ok) return [];
      return resp.json();
    } catch {
      return [];
    }
  }

  async function fetchArticles(query) {
    try {
      const resp = await fetch("/intern/article-search/?q=" + encodeURIComponent(query));
      if (!resp.ok) return [];
      return resp.json();
    } catch {
      return [];
    }
  }

  function showDropdown(ta, results, match) {
    if (!dropdownEl) {
      dropdownEl = document.createElement("div");
      dropdownEl.className = "wiki-autocomplete";
      document.body.appendChild(dropdownEl);
    }
    dropdownEl.innerHTML = "";
    currentResults = results;
    currentMatch = match;
    selectedIndex = 0;

    results.forEach((item, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "wiki-autocomplete-item" + (i === 0 ? " selected" : "");
      btn.textContent =
        item.kind === "datei-prefix" ? "Datei: – Dateiverweis" : item.name;
      btn.addEventListener("mousedown", (e) => {
        e.preventDefault(); // prevent blur
        completeItem(ta, item);
        hideDropdown();
      });
      dropdownEl.appendChild(btn);
    });

    const caretPos = getCaretPos(ta, ta.selectionStart);
    const taRect = ta.getBoundingClientRect();
    let left = taRect.left + caretPos.left;
    let top = taRect.top + caretPos.top + caretPos.height + 4;
    // Clamp to viewport
    dropdownEl.classList.add("active");
    const ddRect = dropdownEl.getBoundingClientRect();
    if (left + ddRect.width > window.innerWidth - 8) {
      left = window.innerWidth - ddRect.width - 8;
    }
    if (top + ddRect.height > window.innerHeight - 8) {
      top = taRect.top + caretPos.top - ddRect.height - 4;
    }
    dropdownEl.style.left = Math.max(4, left) + "px";
    dropdownEl.style.top = Math.max(4, top) + "px";
  }

  function hideDropdown() {
    if (dropdownEl) {
      dropdownEl.classList.remove("active");
      dropdownEl.innerHTML = "";
    }
    currentResults = [];
    selectedIndex = -1;
    currentMatch = null;
  }

  function completeItem(ta, item) {
    const match = currentMatch;
    if (!match) return;
    const text = ta.value;
    let replacement;
    // Die Pille „Medienplayer" der Syntax-Hilfe hinterlegt hier ihren Zusatz
    // (wiki-einfuegen.js): der Verweis schließt dann mit |Titel]], und der
    // Titel wird markiert. Der Merker gilt nur für diesen einen Abschluss.
    const suffix = item.kind === "datei" ? ta.dataset.wikiSuffix || "" : "";
    if (item.kind === "datei-prefix") {
      // Complete just the "Datei:" prefix; the file search takes over as the
      // user keeps typing the filename.
      replacement = "[[Datei:";
    } else if (item.kind === "datei") {
      replacement = "[[Datei:" + item.name + suffix + "]]";
    } else {
      replacement = "[[" + item.name + "]]";
    }
    ta.value = text.substring(0, match.prefixStart) + replacement + text.substring(ta.selectionStart);
    const newPos = match.prefixStart + replacement.length;
    if (suffix) {
      delete ta.dataset.wikiSuffix;
      // Auswahl auf den Zusatz ohne sein führendes "|".
      const suffixStart = newPos - 2 - suffix.length + 1;
      ta.setSelectionRange(suffixStart, newPos - 2);
    } else {
      ta.setSelectionRange(newPos, newPos);
    }
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function updateSelection() {
    if (!dropdownEl) return;
    const items = dropdownEl.querySelectorAll(".wiki-autocomplete-item");
    items.forEach((el, i) => el.classList.toggle("selected", i === selectedIndex));
  }

  function onInput() {
    const ta = activeTextarea;
    if (!ta) return;
    clearTimeout(debounceTimer);
    const match = detectPattern(ta);
    if (!match) { hideDropdown(); return; }
    debounceTimer = setTimeout(async () => {
      let results;
      if (match.kind === "datei") {
        results = (await fetchResults(match.queryText)).map((r) => ({
          kind: "datei", name: r.name,
        }));
      } else {
        results = (await fetchArticles(match.queryText)).map((r) => ({
          kind: "artikel", name: r.name,
        }));
        // Offer the "Datei:" file-reference prefix when the query is a prefix
        // of it (e.g. typing "[[Dat" suggests "[[Datei:").
        if ("datei:".startsWith(match.queryText.toLowerCase())) {
          results.unshift({ kind: "datei-prefix", name: "Datei:" });
        }
      }
      const fresh = detectPattern(ta);
      if (!results.length || !fresh) { hideDropdown(); return; }
      showDropdown(ta, results, fresh);
    }, DEBOUNCE_MS);
  }

  function onKeydown(e) {
    if (!dropdownEl || !dropdownEl.classList.contains("active")) return;
    if (e.key === "Tab") {
      e.preventDefault();
      if (currentResults.length > 0) {
        completeItem(e.target, currentResults[0]);
      }
      hideDropdown();
    } else if (e.key === "Escape") {
      e.preventDefault();
      hideDropdown();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      selectedIndex = Math.min(selectedIndex + 1, currentResults.length - 1);
      updateSelection();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      selectedIndex = Math.max(selectedIndex - 1, 0);
      updateSelection();
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (selectedIndex >= 0 && selectedIndex < currentResults.length) {
        completeItem(e.target, currentResults[selectedIndex]);
      }
      hideDropdown();
    }
  }

  function setupTextarea(ta) {
    ta.addEventListener("input", () => { activeTextarea = ta; onInput(); });
    ta.addEventListener("keydown", onKeydown);
    ta.addEventListener("blur", () => { setTimeout(hideDropdown, 150); });
  }

  // Target: artikel editor textarea + forum textarea
  document.querySelectorAll(".wiki textarea").forEach(setupTextarea);
  const forumTa = document.getElementById("mitteilung-textarea");
  if (forumTa) setupTextarea(forumTa);

  document.addEventListener("click", (e) => {
    if (dropdownEl && !dropdownEl.contains(e.target)) hideDropdown();
  });
  window.addEventListener("scroll", hideDropdown, true);
  window.addEventListener("resize", hideDropdown);

  document.querySelectorAll(".wiki pre").forEach((pre) => {
    const btn = document.createElement("button");
    btn.className = "wiki-copy-btn";
    btn.title = "Kopieren";
    btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
    btn.addEventListener("click", () => {
      const code = pre.querySelector("code");
      navigator.clipboard.writeText((code || pre).textContent).then(() => {
        btn.classList.add("wiki-copy-btn--done");
        setTimeout(() => btn.classList.remove("wiki-copy-btn--done"), 1500);
      });
    });
    pre.appendChild(btn);
  });
})();

// Next-event banner: dismiss (per login session) + hide on that termin's detail page
(function initTerminBanner() {
  const KEY = "termin-banner-dismissed";

  function apply() {
    const banner = document.getElementById("termin-banner");
    if (!banner) return;
    const id = banner.dataset.terminId;
    if (!id) return;
    // Hide on the detail page of exactly this termin (avoids a duplicate widget)
    if (location.pathname === "/intern/termin/" + id + "/") {
      banner.remove();
      return;
    }
    // Dismissed for the current login session (anchored to `banner_login` =
    // request.user pk + last_login): reappears after the next login, when the
    // stored value no longer matches.
    const login = banner.dataset.login;
    if (login && localStorage.getItem(KEY) === login) {
      banner.remove();
      return;
    }
    // The banner is rendered with `hidden`; the inline script in _termin_banner.html
    // normally reveals it before paint. This is only a fallback.
    banner.hidden = false;
  }

  document.addEventListener("click", (e) => {
    const hit = e.target.closest(".termin-banner-dismiss, .termin-banner-main");
    if (!hit) return;
    const banner = hit.closest(".termin-banner");
    if (!banner) return;
    // Following the link to the termin counts as dismissing it, too.
    if (banner.dataset.login) localStorage.setItem(KEY, banner.dataset.login);
    if (hit.classList.contains("termin-banner-dismiss")) banner.remove();
  });

  document.addEventListener("DOMContentLoaded", apply);
  document.body.addEventListener("htmx:afterSwap", apply);
  apply();
})();
