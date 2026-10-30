/* Medien-Karten der Lieder (titel.html, titel_edit.html).

   Beide Karten haben eine Ablagefläche, die einzige ihrer Seite: jede Datei
   landet unter ihrem Namen im Lied-Ordner, ohne Rolle (`lied_id`, siehe
   upload()). Die Detailseite lädt danach neu, die Bearbeiten-Seite hängt die
   Datei an die Karte an — das Formular daneben bleibt stehen.

   Die Bearbeiten-Seite vergibt dazu die Rollen: Chip auf eine Datei ziehen,
   Chip antippen und dann die Datei antippen (für Touch), Datei antippen und
   dann eine freie Rolle antippen, × löst, Zurückziehen in die freie Ablage
   löst ebenfalls. Eine Rolle hängt je Lied an genau einer Datei, und eine
   Datei trägt höchstens eine Rolle — eine neue macht ihre bisherige frei. Das
   entscheidet der Server, das DOM zieht nach. Dazu je Datei Umbenennen
   (inline, Enter/Verlassen speichert, Esc bricht ab) und Löschen (nach
   Rückfrage im <dialog> außerhalb des Formulars). Nichts davon schickt das
   Liedformular ab, in dem die Karte steckt.

   Das Skript arbeitet beim Laden und nicht erst in DOMContentLoaded:
   upload-progress.js hängt sich in seinem eigenen DOMContentLoaded an
   window.internUploadZonen und würde eine später angelegte Zone verpassen. */
(function () {
  "use strict";

  function csrf() {
    const feld = document.querySelector("[name=csrfmiddlewaretoken]");
    if (feld && feld.value) return feld.value;
    const treffer = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return treffer ? decodeURIComponent(treffer[1]) : "";
  }

  function maxMb() {
    const main = document.getElementById("app-main");
    return parseInt(main && main.dataset.uploadMaxMb, 10) || 50;
  }

  // ── Ablagefläche: ein Lied, ein Ziel ──
  // `erfolg` läuft je Datei, `fertig(alleDa)` erst, wenn alle angekommen sind.
  function ablage(flaeche, liedId, { erfolg, fertig } = {}) {
    if (typeof Dropzone === "undefined") return;
    const dz = new Dropzone(flaeche, {
      url: "/intern/upload/",
      paramName: "file",
      maxFilesize: maxMb(),
      clickable: true,
      previewsContainer: false,
      headers: { "X-CSRFToken": csrf() },
      init: function () {
        this.on("sending", (datei, xhr, formData) => formData.append("lied_id", liedId));
        if (erfolg) this.on("success", erfolg);
        this.on("queuecomplete", () => {
          const alleDa = this.files.every((f) => f.status === Dropzone.SUCCESS);
          this.files.slice().forEach((f) => this.removeFile(f));
          if (fertig) fertig(alleDa);
        });
      },
    });
    // Die Fortschrittskarte (upload-progress.js) hängt sich an jede Zone hier.
    window.internUploadZonen = window.internUploadZonen || [];
    window.internUploadZonen.push(dz);

    // Enter/Leertaste öffnen dieselbe Auswahl wie der Klick; Dropzone legt
    // dafür ein verstecktes Dateifeld an.
    flaeche.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      if (dz.hiddenFileInput) dz.hiddenFileInput.click();
    });
  }

  // ── Bearbeiten-Seite: Ablage + Rollenvergabe ──
  function initRollenKarte(karte) {
    const dateien = karte.querySelector("[data-medien-dateien]");
    const freie = karte.querySelector("[data-freie-rollen]");
    const status = karte.querySelector(".medien-status");
    const vorlage = document.getElementById("medien-datei-vorlage");
    const daten = document.getElementById("medien-rollen");
    if (!dateien || !freie || !status || !vorlage || !daten) return;

    const rollen = JSON.parse(daten.textContent || "[]");
    const labels = new Map(rollen.map((r) => [r.key, r.label]));
    const rolleUrl = karte.dataset.rolleUrl;
    const dateiUrl = karte.dataset.dateiUrl;
    const dialog = document.getElementById("medien-loeschen-dialog");
    const liedId = karte.dataset.liedId;

    let gewaehlteRolle = null; // Rolle, die auf eine Datei wartet
    let gewaehlteDatei = null; // Datei, die auf eine freie Rolle wartet
    let zieht = null;          // { rolle, dateiId } während eines Drags
    let busy = false;

    const label = (key) => labels.get(key) || key;

    function meldung(text, istFehler) {
      status.textContent = text || "";
      status.classList.toggle("is-fehler", !!istFehler);
    }

    function zeileFuer(dateiId) {
      return dateien.querySelector('.medien-datei[data-datei-id="' + dateiId + '"]');
    }

    function nameVon(zeile) {
      const nameEl = zeile && zeile.querySelector(".medien-datei-name");
      return nameEl ? nameEl.textContent : "";
    }

    // Der Dateiname steht an mehreren Stellen: sichtbar, als title und in den
    // aria-labels der Knöpfe der Zeile.
    function nameSetzen(zeile, name) {
      const nameEl = zeile.querySelector(".medien-datei-name");
      if (nameEl) {
        nameEl.textContent = name;
        nameEl.title = name;
      }
      const link = zeile.querySelector("a");
      if (link) {
        link.title = name + " öffnen";
        link.setAttribute("aria-label", name + " öffnen");
      }
      const umbenennen = zeile.querySelector(".medien-datei-umbenennen");
      if (umbenennen) umbenennen.setAttribute("aria-label", name + " umbenennen");
      const loeschen = zeile.querySelector(".medien-datei-loeschen");
      if (loeschen) loeschen.setAttribute("aria-label", name + " löschen");
      zeile.querySelectorAll(".medien-chip-x").forEach((x) => {
        const wrap = x.closest(".medien-chip-wrap");
        x.setAttribute("aria-label", "Rolle " + label(wrap.dataset.rolle) + " von " + name + " lösen");
      });
    }

    function chipBauen(key, mitX, dateiName) {
      const wrap = document.createElement("span");
      wrap.className = "medien-chip-wrap";
      wrap.dataset.rolle = key;
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "medien-chip";
      chip.draggable = true;
      chip.dataset.rolle = key;
      chip.textContent = label(key);
      chip.title = "Rolle „" + label(key) + "“ — antippen oder auf eine Datei ziehen";
      wrap.appendChild(chip);
      if (mitX) {
        const x = document.createElement("button");
        x.type = "button";
        x.className = "medien-chip-x";
        x.textContent = "×";
        x.setAttribute(
          "aria-label",
          "Rolle " + label(key) + (dateiName ? " von " + dateiName : "") + " lösen"
        );
        wrap.appendChild(x);
      }
      return wrap;
    }

    // Jede Zeile ohne Chip trägt den Knopf „Rolle zuweisen“; er ist auch der
    // Tastaturweg, eine gewählte Rolle an eine Datei zu geben.
    function platzhalterNeu() {
      dateien.querySelectorAll(".medien-datei").forEach((zeile) => {
        const slot = zeile.querySelector("[data-slot]");
        if (!slot) return;
        const hatChip = !!slot.querySelector(".medien-chip");
        const leer = slot.querySelector(".medien-slot-leer");
        if (hatChip && leer) leer.remove();
        if (!hatChip && !leer) {
          const knopf = document.createElement("button");
          knopf.type = "button";
          knopf.className = "medien-slot-leer";
          knopf.textContent = "Rolle zuweisen";
          slot.appendChild(knopf);
        }
      });
    }

    // Die freie Ablage ist abgeleitet, nicht gespeichert: alle Rollen, die an
    // keiner Datei hängen. Damit kann sie nicht aus dem Tritt geraten.
    function freieNeu() {
      const leer = freie.querySelector(".medien-freie-leer");
      freie.querySelectorAll(".medien-chip-wrap").forEach((el) => el.remove());
      const vergeben = new Set(
        Array.from(dateien.querySelectorAll(".medien-chip"), (c) => c.dataset.rolle)
      );
      const offen = rollen.filter((r) => !vergeben.has(r.key));
      offen.forEach((r) => freie.insertBefore(chipBauen(r.key, false), leer));
      if (leer) leer.hidden = offen.length > 0;
    }

    function auswahlLoeschen(mitMeldung) {
      gewaehlteRolle = null;
      gewaehlteDatei = null;
      dateien.classList.remove("is-waehlend");
      freie.classList.remove("is-waehlend");
      karte.querySelectorAll(".medien-chip.is-gewaehlt").forEach((chip) => {
        chip.classList.remove("is-gewaehlt");
        chip.setAttribute("aria-pressed", "false");
      });
      karte.querySelectorAll(".medien-datei.is-gewaehlt").forEach((zeile) => {
        zeile.classList.remove("is-gewaehlt");
      });
      if (mitMeldung !== false) meldung("");
    }

    // Gibt die Rollen zurück, die die Zieldatei dabei abgibt (sie werden frei).
    function rolleSetzen(dateiId, key, fokus) {
      const zeile = zeileFuer(dateiId);
      const abgegeben = [];
      // Eine Datei trägt höchstens eine Rolle: ihre bisherigen werden frei.
      if (zeile) {
        zeile.querySelectorAll(".medien-chip-wrap").forEach((wrap) => {
          if (wrap.dataset.rolle !== key) abgegeben.push(wrap.dataset.rolle);
          wrap.remove();
        });
      }
      // Eine Rolle hängt je Lied nur an einer Datei: auch dort entfernen.
      karte.querySelectorAll('.medien-chip[data-rolle="' + key + '"]').forEach((chip) => {
        chip.closest(".medien-chip-wrap").remove();
      });
      if (zeile) {
        const slot = zeile.querySelector("[data-slot]");
        if (slot) slot.appendChild(chipBauen(key, true, nameVon(zeile)));
      }
      platzhalterNeu();
      freieNeu();
      if (fokus && zeile) {
        const chip = zeile.querySelector(".medien-chip");
        if (chip) chip.focus();
      }
      return abgegeben;
    }

    function rolleLoesen(dateiId, key, fokus) {
      const zeile = zeileFuer(dateiId);
      if (zeile) {
        zeile.querySelectorAll('.medien-chip[data-rolle="' + key + '"]').forEach((chip) => {
          chip.closest(".medien-chip-wrap").remove();
        });
      }
      platzhalterNeu();
      freieNeu();
      if (fokus && zeile) {
        const leer = zeile.querySelector(".medien-slot-leer");
        if (leer) leer.focus();
      }
    }

    // Ein POST an den Server; wirft mit dessen Meldung, wenn er ablehnt.
    async function senden(url, felder, fehlertext) {
      const antwort = await fetch(url, {
        method: "POST",
        headers: {
          "X-CSRFToken": csrf(),
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: new URLSearchParams(felder),
      });
      let daten = {};
      try {
        daten = await antwort.json();
      } catch (e) {
        /* keine JSON-Antwort */
      }
      if (!antwort.ok || daten.status !== "success") {
        throw new Error(daten.message || fehlertext);
      }
      return daten;
    }

    // Nur eine Anfrage zugleich. Wer danach kommt (Umbenennen beim Verlassen
    // des Felds, Löschen nach der Rückfrage), wartet, statt verloren zu gehen.
    async function frei() {
      while (busy) await new Promise((weiter) => setTimeout(weiter, 50));
    }

    // „A“ / „A“ und „B“ — für die Meldung, welche Rollen frei wurden.
    function aufzaehlen(keys) {
      const namen = keys.map((k) => "„" + label(k) + "“");
      return namen.length > 1
        ? namen.slice(0, -1).join(", ") + " und " + namen[namen.length - 1]
        : namen[0];
    }

    // Der Server entscheidet: Antwort abwarten, dann das DOM nachziehen. Ohne
    // Erfolg bleibt alles, wie es war — kein Rückschritt nötig.
    async function speichern(dateiId, rolle, entfernteRolle, fokus) {
      if (busy) return false;
      busy = true;
      karte.setAttribute("aria-busy", "true");
      try {
        await senden(
          rolleUrl,
          { datei: dateiId, rolle: rolle || "" },
          "Die Rolle ließ sich nicht speichern."
        );
        if (rolle) {
          const frei = rolleSetzen(dateiId, rolle, fokus);
          let text = "Rolle „" + label(rolle) + "“ zugewiesen";
          if (frei.length) {
            text += " — " + aufzaehlen(frei) + (frei.length > 1 ? " sind" : " ist") + " wieder frei";
          }
          meldung(text + ".");
        } else {
          rolleLoesen(dateiId, entfernteRolle, fokus);
          meldung("Rolle „" + label(entfernteRolle) + "“ gelöst.");
        }
        return true;
      } catch (fehler) {
        meldung(fehler.message || "Die Rolle ließ sich nicht speichern.", true);
        return false;
      } finally {
        busy = false;
        karte.removeAttribute("aria-busy");
        auswahlLoeschen(false);
      }
    }

    function waehlen(chip) {
      // Datei zuerst gewählt: diese Rolle gehört dorthin.
      if (gewaehlteDatei) {
        speichern(gewaehlteDatei, chip.dataset.rolle, null, true);
        return;
      }
      const key = chip.dataset.rolle;
      if (gewaehlteRolle === key) {
        auswahlLoeschen();
        return;
      }
      auswahlLoeschen(false);
      gewaehlteRolle = key;
      chip.classList.add("is-gewaehlt");
      chip.setAttribute("aria-pressed", "true");
      dateien.classList.add("is-waehlend");
      meldung("Rolle „" + label(key) + "“ gewählt — jetzt eine Datei antippen.");
    }

    function dateiWaehlen(zeile) {
      if (gewaehlteRolle) {
        if (zeile.querySelector('.medien-chip[data-rolle="' + gewaehlteRolle + '"]')) {
          meldung("Diese Rolle hängt schon an dieser Datei.");
          auswahlLoeschen(false);
          return;
        }
        speichern(zeile.dataset.dateiId, gewaehlteRolle, null, true);
        return;
      }
      const id = zeile.dataset.dateiId;
      if (gewaehlteDatei === id) {
        auswahlLoeschen();
        return;
      }
      auswahlLoeschen(false);
      gewaehlteDatei = id;
      zeile.classList.add("is-gewaehlt");
      freie.classList.add("is-waehlend");
      const nameEl = zeile.querySelector(".medien-datei-name");
      meldung(
        "Datei „" + (nameEl ? nameEl.textContent : "") + "“ gewählt — jetzt eine freie Rolle antippen."
      );
    }

    function zielVon(el) {
      const ziel = el && el.closest ? el.closest(".medien-datei, .medien-freie-rollen") : null;
      return ziel && karte.contains(ziel) ? ziel : null;
    }

    function markiere(ziel) {
      karte.querySelectorAll(".is-ueber").forEach((el) => {
        if (el !== ziel) el.classList.remove("is-ueber");
      });
      if (ziel) ziel.classList.add("is-ueber");
    }

    // ── Umbenennen: der Name wird an Ort und Stelle zum Textfeld ──
    function umbenennenStarten(zeile) {
      const nameEl = zeile.querySelector(".medien-datei-name");
      if (!nameEl || zeile.classList.contains("is-umbenennen")) return;
      auswahlLoeschen();
      const alt = nameEl.textContent;
      const knopf = zeile.querySelector(".medien-datei-umbenennen");
      const feld = document.createElement("input");
      feld.type = "text";
      feld.className = "medien-datei-eingabe";
      feld.value = alt;
      feld.setAttribute("aria-label", "Neuer Name für " + alt);
      feld.spellcheck = false;
      zeile.classList.add("is-umbenennen");
      nameEl.hidden = true;
      nameEl.after(feld);
      feld.focus();
      // Vorausgewählt ist der Name ohne Endung — die bleibt meist, wie sie ist.
      const punkt = alt.lastIndexOf(".");
      feld.setSelectionRange(0, punkt > 0 ? punkt : alt.length);

      let fertig = false;
      function beenden(fokusZurueck) {
        fertig = true;
        feld.remove();
        nameEl.hidden = false;
        zeile.classList.remove("is-umbenennen");
        zeile.removeAttribute("aria-busy");
        if (fokusZurueck && knopf) knopf.focus();
      }

      async function uebernehmen(fokusZurueck) {
        if (fertig) return;
        const neu = feld.value.trim();
        if (!neu || neu === alt) {
          beenden(fokusZurueck);
          return;
        }
        fertig = true;
        feld.readOnly = true;
        zeile.setAttribute("aria-busy", "true");
        await frei();
        busy = true;
        try {
          const daten = await senden(
            dateiUrl,
            { datei: zeile.dataset.dateiId, aktion: "umbenennen", name: neu },
            "Die Datei ließ sich nicht umbenennen."
          );
          nameSetzen(zeile, daten.name || neu);
          meldung("Umbenannt in „" + (daten.name || neu) + "“.");
        } catch (fehler) {
          meldung(fehler.message || "Die Datei ließ sich nicht umbenennen.", true);
        } finally {
          busy = false;
          beenden(fokusZurueck);
        }
      }

      feld.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          // Enter schickte sonst das Liedformular ab, in dem die Karte steckt.
          e.preventDefault();
          uebernehmen(true);
        } else if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          beenden(true);
        }
      });
      feld.addEventListener("blur", () => uebernehmen(false));
    }

    // ── Löschen: Rückfrage im <dialog>, dann der Server ──
    function bestaetigen(name, rollenKeys) {
      // Ohne den Dialog (fremde Seite, altes Template) lieber gar nicht löschen.
      if (!dialog || typeof dialog.showModal !== "function") return Promise.resolve(false);
      dialog.querySelector("[data-frage]").textContent =
        "Möchtest du „" + name + "“ wirklich löschen?";
      const warnung = dialog.querySelector("[data-warnung]");
      warnung.hidden = !rollenKeys.length;
      warnung.textContent = rollenKeys.length
        ? (rollenKeys.length > 1 ? "Die Rollen " : "Die Rolle ") + aufzaehlen(rollenKeys) +
          (rollenKeys.length > 1 ? " werden" : " wird") + " dabei frei."
        : "";
      dialog.returnValue = "";
      dialog.showModal();
      return new Promise((fertig) => {
        dialog.addEventListener("close", () => fertig(dialog.returnValue === "loeschen"), {
          once: true,
        });
      });
    }

    async function loeschen(zeile) {
      auswahlLoeschen();
      const name = nameVon(zeile);
      const rollenKeys = Array.from(
        zeile.querySelectorAll(".medien-chip"),
        (c) => c.dataset.rolle
      );
      if (!(await bestaetigen(name, rollenKeys))) return;
      await frei();
      busy = true;
      zeile.setAttribute("aria-busy", "true");
      try {
        await senden(
          dateiUrl,
          { datei: zeile.dataset.dateiId, aktion: "loeschen" },
          "Die Datei ließ sich nicht löschen."
        );
        // Der Fokus geht an die Nachbarzeile, sonst an die Ablage.
        const nachbar = zeile.nextElementSibling || zeile.previousElementSibling;
        zeile.remove();
        if (!dateien.querySelector(".medien-datei")) {
          const hinweis = document.createElement("p");
          hinweis.className = "medien-leer";
          hinweis.dataset.medienLeer = "";
          hinweis.textContent = "Noch keine Dateien im Lied-Ordner.";
          dateien.appendChild(hinweis);
        }
        platzhalterNeu();
        freieNeu();
        const ziel =
          (nachbar && nachbar.querySelector(".medien-datei-loeschen")) ||
          karte.querySelector("[data-medien-ablage='karte']");
        if (ziel) ziel.focus();
        meldung("„" + name + "“ gelöscht.");
      } catch (fehler) {
        zeile.removeAttribute("aria-busy");
        meldung(fehler.message || "Die Datei ließ sich nicht löschen.", true);
      } finally {
        busy = false;
      }
    }

    // ── Klick und Tastatur ──
    karte.addEventListener("click", async (e) => {
      if (e.target.closest("a")) return; // „Öffnen“ bleibt ein Link
      if (e.target.closest(".medien-datei-eingabe")) return; // Klick ins Textfeld
      // Ein Klick direkt nach dem Umbenennen-Feld trifft auf dessen laufende
      // Anfrage (Blur): er wartet, statt verloren zu gehen.
      await frei();
      const umbenennen = e.target.closest(".medien-datei-umbenennen");
      if (umbenennen) {
        umbenennenStarten(umbenennen.closest(".medien-datei"));
        return;
      }
      const loeschKnopf = e.target.closest(".medien-datei-loeschen");
      if (loeschKnopf) {
        loeschen(loeschKnopf.closest(".medien-datei"));
        return;
      }
      const x = e.target.closest(".medien-chip-x");
      if (x) {
        const wrap = x.closest(".medien-chip-wrap");
        const zeile = x.closest(".medien-datei");
        if (wrap && zeile) speichern(zeile.dataset.dateiId, "", wrap.dataset.rolle, true);
        return;
      }
      const chip = e.target.closest(".medien-chip");
      if (chip) {
        waehlen(chip);
        return;
      }
      const leer = e.target.closest(".medien-slot-leer");
      if (leer) {
        const zeile = zielVon(leer);
        if (zeile) dateiWaehlen(zeile);
        return;
      }
      const ziel = zielVon(e.target);
      if (ziel && ziel.classList.contains("medien-datei")) dateiWaehlen(ziel);
    });

    // ── Ziehen ──
    karte.addEventListener("dragstart", (e) => {
      const chip = e.target.closest(".medien-chip");
      if (!chip) return;
      const zeile = chip.closest(".medien-datei");
      zieht = { rolle: chip.dataset.rolle, dateiId: zeile ? zeile.dataset.dateiId : null };
      e.dataTransfer.effectAllowed = "move";
      try {
        e.dataTransfer.setData("text/plain", chip.dataset.rolle);
      } catch (err) {
        /* Safari mag das setData nicht immer */
      }
      const wrap = chip.closest(".medien-chip-wrap");
      if (wrap) wrap.classList.add("is-zieht");
      auswahlLoeschen(false);
    });

    karte.addEventListener("dragend", () => {
      zieht = null;
      karte.querySelectorAll(".is-zieht").forEach((el) => el.classList.remove("is-zieht"));
      markiere(null);
    });

    karte.addEventListener("dragover", (e) => {
      if (!zieht) return;
      const ziel = zielVon(e.target);
      if (!ziel) return;
      // Eine Zeile im Umbenennen ist kein Ziel — und das Textfeld nähme den
      // Chip sonst als Text an.
      if (ziel.classList.contains("is-umbenennen")) {
        e.preventDefault();
        e.dataTransfer.dropEffect = "none";
        markiere(null);
        return;
      }
      if (ziel.classList.contains("medien-datei") && ziel.dataset.dateiId === zieht.dateiId) {
        markiere(null);
        return;
      }
      if (ziel.classList.contains("medien-freie-rollen") && !zieht.dateiId) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      markiere(ziel);
    });

    karte.addEventListener("dragleave", (e) => {
      if (!zieht) return;
      const ziel = zielVon(e.target);
      if (ziel && !ziel.contains(e.relatedTarget)) ziel.classList.remove("is-ueber");
      if (!karte.contains(e.relatedTarget)) markiere(null);
    });

    karte.addEventListener("drop", (e) => {
      if (!zieht) return;
      const ziel = zielVon(e.target);
      if (!ziel) return;
      e.preventDefault();
      e.stopPropagation();
      if (ziel.classList.contains("is-umbenennen")) return;
      const rolle = zieht.rolle;
      const dateiId = zieht.dateiId;
      zieht = null;
      markiere(null);
      karte.querySelectorAll(".is-zieht").forEach((el) => el.classList.remove("is-zieht"));
      if (ziel.classList.contains("medien-freie-rollen")) {
        if (dateiId) speichern(dateiId, "", rolle, false);
        return;
      }
      if (ziel.dataset.dateiId === dateiId) return;
      if (ziel.querySelector('.medien-chip[data-rolle="' + rolle + '"]')) return;
      speichern(ziel.dataset.dateiId, rolle, null, false);
    });

    // ── Neue Datei aus der Ablage: an die Karte hängen, ohne Neuladen ──
    function zeileAnhaengen(antwort) {
      if (!antwort || antwort.status !== "success") return;
      const hinweis = dateien.querySelector("[data-medien-leer]");
      if (hinweis) hinweis.remove();

      const vorhanden = zeileFuer(antwort.id);
      if (vorhanden) {
        vorhanden.classList.remove("is-neu");
        void vorhanden.offsetWidth; // Neustart der Animation
        vorhanden.classList.add("is-neu");
        meldung(
          antwort.overwritten
            ? "„" + antwort.name + "“ als neue Fassung abgelegt."
            : antwort.meldung || "Die Datei liegt bereits im Lied-Ordner."
        );
        return;
      }

      const zeile = vorlage.content.firstElementChild.cloneNode(true);
      zeile.dataset.dateiId = antwort.id;
      nameSetzen(zeile, antwort.name);
      const link = zeile.querySelector("a");
      if (link) link.href = antwort.url;
      dateien.appendChild(zeile);
      platzhalterNeu();
      freieNeu();
      zeile.classList.add("is-neu");
      if (antwort.identisch) {
        meldung(antwort.meldung || "Bereits vorhanden — nicht abgelegt.", true);
      } else {
        meldung("„" + antwort.name + "“ abgelegt — jetzt eine Rolle zuweisen.");
      }
    }

    platzhalterNeu();
    freieNeu();
    const flaeche = karte.querySelector("[data-medien-ablage='karte']");
    if (flaeche) ablage(flaeche, liedId, { erfolg: (datei, antwort) => zeileAnhaengen(antwort) });
  }

  const ablageSeite = document.querySelector("[data-medien-ablage='seite']");
  if (ablageSeite) {
    ablage(ablageSeite, ablageSeite.dataset.liedId, {
      // Nach einem Fehler bleibt die Seite stehen, damit die Karte ihn zeigt.
      fertig: (alleDa) => { if (alleDa) window.location.reload(); },
    });
  }

  const karte = document.getElementById("medien-karte");
  if (karte) initRollenKarte(karte);
})();
