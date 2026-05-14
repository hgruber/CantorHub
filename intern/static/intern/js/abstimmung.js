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
