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

  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
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

  apply(current());

  btn.addEventListener("click", () => {
    apply(current() === "dark" ? "light" : "dark");
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
        });
        this.on("queuecomplete", function () {
          if (window.location.pathname.startsWith("/intern/ordner/")) {
            refreshFolderTable();
          } else if (appMain.dataset.uploadLiedId) {
            window.location.reload();
          }
        });
      },
    });

    let dragCounter = 0;
    appMain.addEventListener("dragenter", (e) => {
      if (!e.dataTransfer || !e.dataTransfer.types.includes("Files")) return;
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
      const csrfTokenElement = document.querySelector(
        "[name=csrfmiddlewaretoken]",
      );
      const csrfToken = csrfTokenElement ? csrfTokenElement.value : "";

      fetch("/intern/update-order/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
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

    // ── Media Session (lock screen / OS media controls) ──────
    const HAS_MS = "mediaSession" in navigator;
    const ARTWORK = [
      { src: "/static/intern/images/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/static/intern/images/icon-512.png", sizes: "512x512", type: "image/png" },
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
    function show() {
      player.classList.add("open");
      player.setAttribute("aria-hidden", "false");
    }
    function hide() {
      player.classList.remove("open");
      player.setAttribute("aria-hidden", "true");
    }
    function stop() {
      if (audio) { try { audio.pause(); } catch (_) {} audio = null; }
      setBtnPlaying(activeBtn, false);
      activeBtn = null;
      queue = [];
      queueIndex = -1;
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
      audio = new Audio(item.url);
      audio.addEventListener("loadedmetadata", () => {
        totalEl.textContent = fmt(audio.duration);
      });
      audio.addEventListener("timeupdate", () => {
        currentEl.textContent = fmt(audio.currentTime);
        if (audio.duration) {
          bar.style.width = (audio.currentTime / audio.duration * 100) + "%";
        }
      });
      audio.addEventListener("ended", onEnded);
      audio.addEventListener("error", () => {
        console.error("Error playing audio:", item.url);
        onEnded();
      });
      audio.addEventListener("play",  () => msState("playing"));
      audio.addEventListener("pause", () => msState("paused"));
      msMetadata(item);
      audio.play().catch((err) => console.error("Audio play() rejected:", err));
      setMainIcon(true);
      show();
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
    function playQueue(items, shuffle) {
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
      queueIndex = 0;
      loadTrack(queue[0], advance);
    }
    window.startPlaylist = function (shuffle) {
      const dataEl = document.getElementById("playlist-data");
      let items = [];
      if (dataEl) {
        try { items = JSON.parse(dataEl.textContent); } catch (_) { items = []; }
      }
      playQueue(items, shuffle);
    };
    window.startPlaylistType = function (type, shuffle) {
      const dataEl = document.getElementById("playlists-data");
      let playlists = {};
      if (dataEl) {
        try { playlists = JSON.parse(dataEl.textContent); } catch (_) {}
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

  // File actions: delete / move / copy / zip
  window.fileAction = function (action) {
    const formId = action === "delete" ? "delete-form"
                 : action === "move"   ? "move-form"
                 : action === "copy"   ? "copy-form"
                 : action === "zip"    ? "zip-form"
                 :                       null;
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
      if (!confirm(`${items.length} Element(e) wirklich löschen?`)) return;
    } else if (action !== "zip") {
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
          e.stopPropagation();
          document.getElementById("app-main")?.classList.remove("drag-active");
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
      Promise.all(promises).then(() => refreshFolderTable());
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

  // ── Row context menu (right-click / long-press) ─────────
  (function initRowContextMenu() {
    const tbody = document.querySelector(".table-container tbody");
    if (!tbody) return;
    const actionPanel = document.getElementById("Action");
    if (!actionPanel || !actionPanel.dataset.canWrite) return; // only on folder views
    const canWrite = actionPanel.dataset.canWrite === "true";
    const canDelete = actionPanel.dataset.canDelete === "true";

    function csrfToken() {
      const el = document.querySelector("[name=csrfmiddlewaretoken]");
      return el ? el.value : "";
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

    function openMenu(tr, x, y) {
      closeMenu();
      const id = tr.dataset.id;
      const type = tr.dataset.type;
      const name = tr.dataset.name || "";
      const isZip = type === "File" && name.toLowerCase().endsWith(".zip");

      menuEl = document.createElement("div");
      menuEl.className = "context-menu";
      const above = [];
      const below = [];

      if (canWrite) {
        above.push({ label: "Umbenennen", action: () => startInlineRename(tr, type, id, name) });
      }
      if (type === "Folder") {
        above.push({ label: "Als ZIP herunterladen", action: () => {
          window.location.href = "/intern/ordner/" + id + "/zip/";
        }});
      }
      if (canWrite) {
        above.push({ label: "Verschieben nach…", action: () => {
          const cb = tr.querySelector('input[type="checkbox"][name="select"]');
          if (cb && !cb.checked) { cb.checked = true; updateSelectionState(); }
          toggle("Action");
        }});
        above.push({ label: "Kopieren nach…", action: () => {
          const cb = tr.querySelector('input[type="checkbox"][name="select"]');
          if (cb && !cb.checked) { cb.checked = true; updateSelectionState(); }
          toggle("Action");
        }});
        if (isZip) {
          above.push({ label: "Entpacken", action: () => submitUnzip(id) });
        }
      }
      if (canDelete) {
        below.push({ label: "Löschen", danger: true, action: () => submitDelete(type, id, name) });
      }

      const allItems = above.length && below.length
        ? [...above, { sep: true }, ...below]
        : [...above, ...below];

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
        b.textContent = it.label;
        b.addEventListener("click", () => { closeMenu(); it.action(); });
        menuEl.appendChild(b);
      }

      if (!menuEl.children.length) return;
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
      tok.type = "hidden"; tok.name = "csrfmiddlewaretoken"; tok.value = csrfToken();
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
      function restore() {
        if (finished) return;
        finished = true;
        cell.innerHTML = originalHTML;
      }

      async function commit() {
        if (finished) return;
        const newName = input.value.trim();
        if (!newName || newName === oldName) { restore(); return; }
        try {
          const res = await fetch("/intern/ordner/umbenennen/", {
            method: "POST",
            headers: {
              "Content-Type": "application/x-www-form-urlencoded",
              "X-CSRFToken": csrfToken(),
            },
            body: new URLSearchParams({ type, id, name: newName }).toString(),
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            alert(data.message || "Umbenennen fehlgeschlagen.");
            restore();
            return;
          }
          finished = true;
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

      if (originalUrl || aufnahmeUrl) {
        h += '<div class="dl-group-label">Abspielen</div>';
        if (originalUrl) {
          h += `<button type="button" class="dl-item"
            data-ctx-url="${esc(originalUrl)}" data-ctx-id="${esc(liedId)}"
            data-ctx-kind="original" data-ctx-title="${esc(titel)}"
            data-ctx-composer="${esc(komponist)}">
            <span class="dl-item-icon dl-icon-audio">${SVG_PLAY}</span>
            <span class="dl-item-body">
              <span class="dl-item-title">Original abspielen</span>
              <span class="dl-item-sub">MP3</span>
            </span></button>`;
        }
        if (aufnahmeUrl) {
          h += `<button type="button" class="dl-item"
            data-ctx-url="${esc(aufnahmeUrl)}" data-ctx-id="r${esc(liedId)}"
            data-ctx-kind="jg" data-ctx-title="${esc(titel)}"
            data-ctx-composer="${esc(komponist)}">
            <span class="dl-item-icon dl-icon-jg-rec">${JG_ICON}</span>
            <span class="dl-item-body">
              <span class="dl-item-title">JG Aufnahme abspielen</span>
              <span class="dl-item-sub">MP3</span>
            </span></button>`;
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

    document.addEventListener("contextmenu", function(e) {
      const tr = e.target.closest("tr[data-lied-id]");
      if (!tr) { closeMenu(); return; }
      closeMenu();
      if (!buildMenu(tr)) return;
      e.preventDefault();
      show(e.clientX, e.clientY);
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
    if (item.kind === "datei-prefix") {
      // Complete just the "Datei:" prefix; the file search takes over as the
      // user keeps typing the filename.
      replacement = "[[Datei:";
    } else if (item.kind === "datei") {
      replacement = "[[Datei:" + item.name + "]]";
    } else {
      replacement = "[[" + item.name + "]]";
    }
    ta.value = text.substring(0, match.prefixStart) + replacement + text.substring(ta.selectionStart);
    const newPos = match.prefixStart + replacement.length;
    ta.setSelectionRange(newPos, newPos);
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
