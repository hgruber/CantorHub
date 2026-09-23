(function () {
  function updateWidget(form) {
    if (!form) return;
    var max = parseInt(form.dataset.max, 10) || 0;
    var boxes = form.querySelectorAll('input[type="checkbox"][name="option"]');
    var checked = 0;
    boxes.forEach(function (b) {
      if (b.checked) checked++;
    });
    if (max > 0) {
      boxes.forEach(function (b) {
        if (!b.hasAttribute("disabled") || b.dataset.maxLocked) {
          b.disabled = !b.checked && checked >= max;
          if (b.disabled) {
            b.dataset.maxLocked = "1";
          } else {
            delete b.dataset.maxLocked;
          }
        }
      });
    }
    var counter = form.querySelector(".abstimmung-counter");
    if (counter) counter.textContent = checked;
  }

  function refreshAll() {
    document.querySelectorAll(".abstimmung-form").forEach(updateWidget);
  }

  document.addEventListener("change", function (e) {
    var box = e.target;
    if (
      box.matches &&
      box.matches('.abstimmung-form input[type="checkbox"][name="option"]')
    ) {
      updateWidget(box.closest(".abstimmung-form"));
    }
  });

  document.addEventListener("DOMContentLoaded", refreshAll);
  document.addEventListener("htmx:afterSwap", refreshAll);

  function fmtCountdown(el) {
    var diff = new Date(el.dataset.deadline).getTime() - Date.now();
    if (isNaN(diff) || diff <= 0) {
      el.textContent = "abgelaufen";
      // If the timer ran out while the page was open, reload so the server
      // re-renders the poll as closed. The "live" flag guards against an
      // immediate reload loop from clock skew on an already-expired poll.
      if (el.dataset.live === "1" && !window.__abstimmungReloading) {
        window.__abstimmungReloading = true;
        window.location.reload();
      }
      return;
    }
    el.dataset.live = "1";
    var s = Math.floor(diff / 1000);
    var d = Math.floor(s / 86400);
    s -= d * 86400;
    var h = Math.floor(s / 3600);
    s -= h * 3600;
    var m = Math.floor(s / 60);
    s -= m * 60;
    el.textContent = d + "d " + h + "h " + m + "m " + s + "s";
  }

  function tickCountdowns() {
    document
      .querySelectorAll(".abstimmung-countdown[data-deadline]")
      .forEach(fmtCountdown);
  }

  setInterval(tickCountdowns, 1000);
  document.addEventListener("DOMContentLoaded", tickCountdowns);
  document.addEventListener("htmx:afterSwap", tickCountdowns);
})();

// ── {abstimmung:...} editor helper (article editor) ───────
// Helps users write the poll directive: a one-click snippet when they start
// typing "{abstimm", Tab navigation between fields, and a live hint naming
// the field the caret is in. Pure editing aid — markup is still parsed by
// replacements.py unchanged.
(function initAbstimmungAssist() {
  var PREFIX = "{abstimmung:";

  // Das Ende ist Pflicht (replacements.py). Das Gerüst bringt deshalb ein
  // Datum mit, das schon passen könnte — in zwei Wochen —, statt eines
  // Platzhalters, den die Feldnavigation nicht als Datum erkennen würde.
  function skelett() {
    var d = new Date(Date.now() + 14 * 86400000);
    var tag = String(d.getDate()).padStart(2, "0");
    var monat = String(d.getMonth() + 1).padStart(2, "0");
    return (
      "{abstimmung:Titel:1:" +
      tag + "." + monat + "." + d.getFullYear() +
      ":Option A;Option B}"
    );
  }

  // Die Syntax-Hilfe fügt dasselbe Gerüst ein (wiki-einfuegen.js) — die
  // Datumsrechnung steht deshalb nur hier.
  window.abstimmungGeruest = skelett;

  // Hidden mirror div for caret pixel position (same technique as the
  // [[Datei:]] autocomplete in intern.js).
  var mirror = document.createElement("div");
  mirror.style.cssText =
    "position:absolute;visibility:hidden;pointer-events:none;white-space:pre-wrap;word-wrap:break-word;overflow:hidden;";
  document.body.appendChild(mirror);

  function getCaretPos(ta, charIndex) {
    var cs = getComputedStyle(ta);
    [
      "font", "fontFamily", "fontSize", "fontWeight", "lineHeight",
      "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
      "borderTopWidth", "borderRightWidth", "borderBottomWidth",
      "borderLeftWidth", "boxSizing", "letterSpacing",
    ].forEach(function (p) {
      mirror.style[p] = cs[p];
    });
    if (cs.boxSizing === "border-box") {
      mirror.style.width = cs.width;
    } else {
      mirror.style.width =
        parseFloat(cs.width) -
        parseFloat(cs.paddingLeft) -
        parseFloat(cs.paddingRight) -
        parseFloat(cs.borderLeftWidth) -
        parseFloat(cs.borderRightWidth) +
        "px";
    }
    mirror.textContent = ta.value.substring(0, charIndex);
    var span = document.createElement("span");
    span.textContent = "|";
    mirror.appendChild(span);
    return { left: span.offsetLeft, top: span.offsetTop, height: span.offsetHeight };
  }

  // Parses the {abstimmung:...} directive on the caret's line. Returns the
  // directive bounds, the selectable field ranges, and which field the caret
  // is currently in — or null when the caret is not inside such a directive.
  function parseDirectiveAtCaret(ta) {
    var text = ta.value;
    var pos = ta.selectionStart;
    var lineStart = text.lastIndexOf("\n", pos - 1) + 1;
    var lineEndNl = text.indexOf("\n", pos);
    var lineEnd = lineEndNl === -1 ? text.length : lineEndNl;
    var line = text.substring(lineStart, lineEnd);
    var pfx = line.match(/^\{abstimmung:/i);
    if (!pfx) return null;
    var prefixLen = pfx[0].length;
    var closeIdx = line.indexOf("}", prefixLen);
    var contentEndRel = closeIdx === -1 ? line.length : closeIdx;
    // Caret must sit within the directive, not past the closing brace.
    if (pos > lineStart + contentEndRel) return null;
    var contentStart = lineStart + prefixLen;
    var content = line.substring(prefixLen, contentEndRel);

    function abs(rel) {
      return contentStart + rel;
    }

    // Split content into ":"-separated segments.
    var colonSegs = [];
    var segStart = 0;
    for (var i = 0; i <= content.length; i++) {
      if (i === content.length || content[i] === ":") {
        colonSegs.push({
          start: segStart,
          end: i,
          text: content.substring(segStart, i),
        });
        segStart = i + 1;
      }
    }

    var fields = [];
    if (colonSegs[0]) {
      fields.push({ start: abs(colonSegs[0].start), end: abs(colonSegs[0].end), kind: "title" });
    }
    if (colonSegs[1]) {
      fields.push({ start: abs(colonSegs[1].start), end: abs(colonSegs[1].end), kind: "max" });
    }
    var optIdx = 2;
    if (colonSegs[2] && /^\s*\d{1,2}\.\d{1,2}\.\d{4}\s*$/.test(colonSegs[2].text)) {
      fields.push({ start: abs(colonSegs[2].start), end: abs(colonSegs[2].end), kind: "deadline" });
      optIdx = 3;
    }
    if (colonSegs[optIdx]) {
      // The options block runs from the start of its first colon segment to
      // the end of the content; split it on ";".
      var optBlockStart = colonSegs[optIdx].start;
      var optBlock = content.substring(optBlockStart);
      var s = optBlockStart;
      for (var j = 0; j <= optBlock.length; j++) {
        if (j === optBlock.length || optBlock[j] === ";") {
          fields.push({ start: abs(s), end: abs(optBlockStart + j), kind: "option" });
          s = optBlockStart + j + 1;
        }
      }
    }

    var current = -1;
    for (var k = 0; k < fields.length; k++) {
      if (pos >= fields[k].start && pos <= fields[k].end) {
        current = k;
        break;
      }
    }
    if (current === -1) current = 0;

    return {
      directiveStart: lineStart,
      directiveEnd: lineStart + (closeIdx === -1 ? line.length : closeIdx + 1),
      fields: fields,
      current: current,
    };
  }

  function fieldHint(parsed) {
    var f = parsed.fields[parsed.current];
    if (!f || f.kind === "title") {
      return "<strong>Titel</strong> — Name der Abstimmung, keine Doppelpunkte";
    }
    if (f.kind === "max") {
      return "<strong>Max. Stimmen</strong> pro Person — Zahl (0 = unbegrenzt)";
    }
    if (f.kind === "deadline") {
      return "<strong>Ende</strong> — Pflicht, Datum im Format TT.MM.JJJJ";
    }
    var hasDeadline = parsed.fields.some(function (x) {
      return x.kind === "deadline";
    });
    var firstOption =
      parsed.fields.filter(function (x) {
        return x.kind === "option";
      })[0] === f;
    if (firstOption && !hasDeadline) {
      return (
        "<strong>Hier fehlt das Ende</strong> — erst das Datum " +
        "<strong>TT.MM.JJJJ:</strong>, dann die Optionen mit " +
        "<strong>;</strong> trennen, mit <strong>}</strong> abschließen"
      );
    }
    return "<strong>Option</strong> — mehrere mit <strong>;</strong> trennen, mit <strong>}</strong> abschließen";
  }

  // Detects when the caret-to-line-start text is a partial "{abstimmung"
  // prefix (>= 3 chars, no ":" yet) — the trigger for the snippet dropdown.
  function detectSnippetPrefix(ta) {
    var text = ta.value;
    var pos = ta.selectionStart;
    var lineStart = text.lastIndexOf("\n", pos - 1) + 1;
    var before = text.substring(lineStart, pos);
    if (!/^\{[a-zA-Z]{2,10}$/.test(before)) return null;
    if ("{abstimmung".indexOf(before.toLowerCase()) !== 0) return null;
    return { start: lineStart, end: pos };
  }

  var dropdownEl = null;
  var hintEl = null;
  var dropdownActive = false;

  function placeNearCaret(el, ta) {
    var caret = getCaretPos(ta, ta.selectionStart);
    var taRect = ta.getBoundingClientRect();
    var left = taRect.left + caret.left;
    var top = taRect.top + caret.top + caret.height + 4;
    el.classList.add("active");
    var rect = el.getBoundingClientRect();
    if (left + rect.width > window.innerWidth - 8) {
      left = window.innerWidth - rect.width - 8;
    }
    if (top + rect.height > window.innerHeight - 8) {
      top = taRect.top + caret.top - rect.height - 4;
    }
    el.style.left = Math.max(4, left) + "px";
    el.style.top = Math.max(4, top) + "px";
  }

  function showDropdown(ta) {
    if (!dropdownEl) {
      dropdownEl = document.createElement("div");
      dropdownEl.className = "wiki-autocomplete";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "wiki-autocomplete-item selected";
      btn.textContent = "Abstimmung einfügen";
      btn.addEventListener("mousedown", function (e) {
        e.preventDefault(); // keep textarea focus
        acceptSnippet(ta);
      });
      dropdownEl.appendChild(btn);
      document.body.appendChild(dropdownEl);
    }
    dropdownActive = true;
    placeNearCaret(dropdownEl, ta);
  }

  function hideDropdown() {
    dropdownActive = false;
    if (dropdownEl) dropdownEl.classList.remove("active");
  }

  function showHint(ta, html) {
    if (!hintEl) {
      hintEl = document.createElement("div");
      hintEl.className = "wiki-hint";
      document.body.appendChild(hintEl);
    }
    hintEl.innerHTML = html;
    placeNearCaret(hintEl, ta);
  }

  function hideHint() {
    if (hintEl) hintEl.classList.remove("active");
  }

  function acceptSnippet(ta) {
    var snip = detectSnippetPrefix(ta);
    hideDropdown();
    if (!snip) return;
    var text = ta.value;
    ta.value = text.substring(0, snip.start) + skelett() + text.substring(snip.end);
    var titleStart = snip.start + PREFIX.length;
    ta.focus();
    ta.setSelectionRange(titleStart, titleStart + "Titel".length);
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    updateHint(ta);
  }

  function updateHint(ta) {
    if (dropdownActive) {
      hideHint();
      return;
    }
    var parsed = parseDirectiveAtCaret(ta);
    if (!parsed) {
      hideHint();
      return;
    }
    showHint(ta, fieldHint(parsed));
  }

  function onInput(e) {
    var ta = e.target;
    if (detectSnippetPrefix(ta)) {
      showDropdown(ta);
    } else {
      hideDropdown();
    }
    updateHint(ta);
  }

  function onKeydown(e) {
    var ta = e.target;
    if (dropdownActive) {
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        acceptSnippet(ta);
      } else if (e.key === "Escape") {
        e.preventDefault();
        hideDropdown();
      }
      return;
    }
    if (e.key === "Tab") {
      var parsed = parseDirectiveAtCaret(ta);
      if (!parsed || !parsed.fields.length) return; // let Tab behave normally
      e.preventDefault();
      var next = parsed.current + (e.shiftKey ? -1 : 1);
      if (next < 0) next = 0;
      if (next >= parsed.fields.length) {
        ta.setSelectionRange(parsed.directiveEnd, parsed.directiveEnd);
        hideHint();
        return;
      }
      var f = parsed.fields[next];
      ta.setSelectionRange(f.start, f.end);
      updateHint(ta);
    } else if (e.key === "Escape") {
      hideHint();
    }
  }

  function setupTextarea(ta) {
    ta.addEventListener("input", onInput);
    ta.addEventListener("keydown", onKeydown);
    ta.addEventListener("keyup", function (e) {
      updateHint(e.target);
    });
    ta.addEventListener("click", function (e) {
      updateHint(e.target);
    });
    ta.addEventListener("blur", function () {
      setTimeout(function () {
        hideDropdown();
        hideHint();
      }, 150);
    });
  }

  // Article editor only (the .wiki container holds the editor textarea).
  document.querySelectorAll(".wiki textarea").forEach(setupTextarea);

  window.addEventListener(
    "scroll",
    function () {
      hideDropdown();
      hideHint();
    },
    true
  );
  window.addEventListener("resize", function () {
    hideDropdown();
    hideHint();
  });
})();
