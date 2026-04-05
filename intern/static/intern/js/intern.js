// Hamburger-Toggle
const hamburger = document.getElementById("hamburger");
const sidebar = document.getElementById("sidebar");

if (hamburger && sidebar) {
  hamburger.addEventListener("click", () => {
    sidebar.classList.toggle("active");
  });
}

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
  // Table selection functionality
  const action = document.getElementById("Action");
  const headerCheckbox = document.querySelector(".select-all");
  const rowCheckboxes = document.querySelectorAll(
    ".table-container tbody input[type=checkbox]",
  );
  let anyPreviouslyChecked = false;

  function checkSelectionState() {
    const checkedCount = document.querySelectorAll(
      ".table-container tbody input[type=checkbox]:checked",
    ).length;
    const anyChecked = checkedCount > 0;
    // Reagiere nur bei Zustandswechsel
    if (anyChecked !== anyPreviouslyChecked) {
      if (anyChecked && action) {
        action.classList.add("open");
      } else if (action) {
        action.classList.remove("open");
      }
    }
    anyPreviouslyChecked = anyChecked;
  }

  // Einzelne Checkboxen
  if (rowCheckboxes) {
    rowCheckboxes.forEach((checkbox) => {
      checkbox.addEventListener("change", checkSelectionState);
    });
  }

  // Select-All
  if (headerCheckbox) {
    headerCheckbox.addEventListener("change", function () {
      if (rowCheckboxes) {
        rowCheckboxes.forEach((cb) => {
          cb.checked = this.checked;
        });
      }
      // EINMAL final prüfen
      checkSelectionState();
    });
  }

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
