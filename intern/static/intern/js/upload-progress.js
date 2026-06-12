(function () {
  "use strict";

  function uid() {
    return Math.random().toString(36).slice(2, 9);
  }

  var card, body, doneEl, totalEl;
  var collapseTimer = null, hideTimer = null;
  var errorCount = 0;

  function buildCard() {
    var appMain = document.getElementById("app-main");
    var folderName = appMain ? (appMain.dataset.uploadFolderName || "") : "";

    card = document.createElement("div");
    card.className = "upload-card";
    card.id = "upload-card";
    card.hidden = true;
    var titleText = folderName
      ? "Upload · " + folderName + " · <span id=\"uc-done\">0</span> von <span id=\"uc-total\">0</span>"
      : "Upload · <span id=\"uc-done\">0</span> von <span id=\"uc-total\">0</span>";
    card.innerHTML =
      '<div class="upload-card-header">' +
        '<span class="upload-card-title">' + titleText + '</span>' +
        '<button type="button" class="upload-card-toggle" aria-label="Minimieren">⌄</button>' +
        '<button type="button" class="upload-card-close" aria-label="Schließen">✕</button>' +
      '</div>' +
      '<div class="upload-card-body" id="uc-body"></div>';
    document.body.appendChild(card);

    doneEl  = card.querySelector("#uc-done");
    totalEl = card.querySelector("#uc-total");
    body    = card.querySelector("#uc-body");

    card.querySelector(".upload-card-toggle").addEventListener("click", function () {
      card.classList.toggle("upload-card--collapsed");
    });
    card.querySelector(".upload-card-close").addEventListener("click", function () {
      card.hidden = true;
      body.innerHTML = "";
    });
  }

  function resetTimers() {
    if (collapseTimer) { clearTimeout(collapseTimer); collapseTimer = null; }
    if (hideTimer)     { clearTimeout(hideTimer);     hideTimer = null; }
  }

  function hookDropzone(dz) {
    var total = 0, done = 0;

    dz.on("addedfile", function (file) {
      resetTimers();
      // Reopen if card was closed after a previous completed queue
      if (card.hidden) {
        card.hidden = false;
        card.classList.remove("upload-card--collapsed");
        body.innerHTML = "";
        total = 0;
        done  = 0;
        errorCount = 0;
      }

      file._ucId = uid();
      total++;
      totalEl.textContent = total;

      var row = document.createElement("div");
      row.className = "uc-row";
      row.id = "uc-row-" + file._ucId;

      var safeName = document.createTextNode(file.name);
      var nameSpan = document.createElement("span");
      nameSpan.className = "uc-name";
      nameSpan.title = file.name;
      nameSpan.appendChild(safeName);

      var barWrap = document.createElement("div");
      barWrap.className = "uc-bar-wrap";
      var bar = document.createElement("div");
      bar.className = "uc-bar";
      bar.style.width = "0%";
      barWrap.appendChild(bar);

      var status = document.createElement("span");
      status.className = "uc-status";

      row.appendChild(nameSpan);
      row.appendChild(barWrap);
      row.appendChild(status);
      body.appendChild(row);
    });

    dz.on("uploadprogress", function (file, progress) {
      if (!file._ucId) return;
      var row = document.getElementById("uc-row-" + file._ucId);
      if (!row) return;
      row.querySelector(".uc-bar").style.width = progress + "%";
    });

    dz.on("success", function (file, response) {
      if (!file._ucId) return;
      var row = document.getElementById("uc-row-" + file._ucId);
      if (!row) return;
      row.querySelector(".uc-bar").style.width = "100%";
      var status = row.querySelector(".uc-status");
      status.className = "uc-status ok";
      var overwritten = response && response.overwritten;
      status.textContent = overwritten ? "✓ Überschrieben" : "✓ Hochgeladen";
      done++;
      doneEl.textContent = done;
    });

    dz.on("error", function (file, message) {
      if (!file._ucId) return;
      var row = document.getElementById("uc-row-" + file._ucId);
      if (!row) return;
      var status = row.querySelector(".uc-status");
      status.className = "uc-status err";
      var msg = (message && typeof message === "object") ? (message.message || "Fehler") : (message || "Fehler");
      status.textContent = "✕ " + msg;
      errorCount++;
      done++;
      doneEl.textContent = done;
    });

    dz.on("queuecomplete", function () {
      if (errorCount > 0) return;
      collapseTimer = setTimeout(function () {
        card.classList.add("upload-card--collapsed");
        hideTimer = setTimeout(function () {
          card.hidden = true;
        }, 2500);
      }, 2500);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    buildCard();

    // appMainDz is set during DOMContentLoaded in intern.js; since both scripts
    // are defer-loaded in document order, intern.js runs first.
    if (window.appMainDz) {
      hookDropzone(window.appMainDz);
      return;
    }

    // Fallback: wait one tick in case script ordering changes
    setTimeout(function () {
      if (window.appMainDz) hookDropzone(window.appMainDz);
    }, 0);
  });
})();
