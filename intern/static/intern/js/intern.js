// Hamburger-Toggle
const hamburger = document.getElementById("hamburger");
const sidebar = document.getElementById("sidebar");

if (hamburger && sidebar) {
  hamburger.addEventListener("click", () => {
    sidebar.classList.toggle("active");
  });
}

// Filter offcanvas functionality
function toggle(offcanvas) {
  const filter = document.getElementById(offcanvas);
  if (filter && filter.classList.contains("open")) {
    filter.classList.remove("open");
  } else if (filter) {
    filter.classList.add("open");
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
    maxFilesize: 25000000,
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
  const tbody = document.querySelector(".table-container table tbody");
  if (tbody) {
    const sortable = new Sortable(tbody, {
      animation: 150,
      ghostClass: "blue-background-class",
      disabled: true, // startet deaktiviert
      onEnd: function (evt) {
        const order = [...evt.to.children].map((row) => row.dataset.id);

        fetch("{% url 'update-order' %}", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": "{{ csrf_token }}",
          },
          body: JSON.stringify({ order: order }),
        });
      },
    });

    function toggleSort() {
      const isDisabled = sortable.option("disabled");
      sortable.option("disabled", !isDisabled);
    }

    // Make toggleSort globally accessible
    window.toggleSort = toggleSort;
  }

  // Audio play/pause functionality
  let currentAudio = null;
  let currentAudioElement = null;

  document.addEventListener("click", function (e) {
    if (e.target.classList.contains("audio-button")) {
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
});
