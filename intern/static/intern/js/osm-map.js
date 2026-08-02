// Zentrale Karten-Hilfen. Wird einmal nach Leaflet in base.html geladen und
// deckt damit jede Karte der Seite ab.
//
// Zwei Aufgaben:
//   1. Der createTile-Patch — Leaflets Tile-<img> schickt keinen brauchbaren
//      Referer, den die OSM-Tileserver mit 403 quittieren. referrerPolicy
//      "origin" haengt den Seiten-Origin als Referer an.
//   2. window.CantorMap — Tile-Layer, Pin-Icons und die Ein-Marker-Karte der
//      Detailseiten, die frueher als Inline-Script in vier Templates stand.
//      Ausgeliefert wird sie vom Include `_leaflet_map.html`, das nur noch
//      einen Container mit data-Attributen rendert; `initAll()` greift beim
//      Laden jeden `[data-osm-map]` darin auf.
(function () {
  if (typeof L === "undefined" || !L.TileLayer) return;

  L.TileLayer.prototype.createTile = function (coords, done) {
    var tile = document.createElement("img");
    tile.referrerPolicy = "origin";
    L.DomEvent.on(tile, "load", L.bind(this._tileOnLoad, this, done, tile));
    L.DomEvent.on(tile, "error", L.bind(this._tileOnError, this, done, tile));
    if (this.options.crossOrigin || this.options.crossOrigin === "") {
      tile.crossOrigin =
        this.options.crossOrigin === true ? "" : this.options.crossOrigin;
    }
    tile.alt = "";
    tile.setAttribute("role", "presentation");
    tile.src = this.getTileUrl(coords);
    return tile;
  };

  var ATTRIBUTION =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

  // Pin-Farben und -Symbole der Uebersichtskarte; die Detailseiten greifen
  // ueber data-pin auf dieselben Definitionen zu.
  var PINS = {
    ort: {
      color: "#4b80c0",
      svg: '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" width="14" height="14"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>',
    },
    mitglied: {
      color: "var(--brand)",
      svg: '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" width="14" height="14"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
    },
  };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // Der OSM-Tile-Layer inklusive Attribution — nie direkt L.tileLayer rufen,
  // sonst faellt bei einem Serverwechsel eine Karte hinten runter.
  function tiles(map, opts) {
    var o = { attribution: ATTRIBUTION };
    for (var k in opts || {}) o[k] = opts[k];
    return L.tileLayer("/tiles/{z}/{x}/{y}.png", o).addTo(map);
  }

  function pin(name) {
    var p = PINS[name];
    if (!p) return null;
    return L.divIcon({
      className: "",
      html:
        '<div class="karte-pin" style="--pin-color:' + p.color + '">' + p.svg + "</div>",
      iconSize: [28, 36],
      iconAnchor: [14, 36],
      popupAnchor: [0, -38],
    });
  }

  // Django lokalisiert Dezimalzahlen, je nach Locale steht im data-Attribut
  // also "50,11" statt "50.11".
  function zahl(wert) {
    return parseFloat(String(wert == null ? "" : wert).replace(",", "."));
  }

  // Popup-Text kommt als Klartext mit Zeilenumbruechen aus dem Template und
  // wird hier — und nur hier — zu HTML.
  function popupHtml(text) {
    return text.split("\n").map(esc).join("<br>");
  }

  // Karte mit genau einem Marker, wie sie die Detailseiten brauchen.
  function init(el) {
    if (el._cantorMap) return el._cantorMap;
    var lat = zahl(el.dataset.lat);
    var lng = zahl(el.dataset.lng);
    if (isNaN(lat) || isNaN(lng)) {
      el.textContent = "Keine gültigen Koordinaten vorhanden.";
      return null;
    }
    var map = L.map(el).setView([lat, lng], parseInt(el.dataset.zoom, 10) || 15);
    tiles(map);
    var icon = pin(el.dataset.pin);
    var marker = L.marker([lat, lng], icon ? { icon: icon } : undefined).addTo(map);
    if (el.dataset.popup) marker.bindPopup(popupHtml(el.dataset.popup)).openPopup();
    el._cantorMap = map;
    return map;
  }

  function initAll(root) {
    var els = (root || document).querySelectorAll("[data-osm-map]");
    Array.prototype.forEach.call(els, init);
  }

  window.CantorMap = {
    tiles: tiles,
    pin: pin,
    esc: esc,
    init: init,
    initAll: initAll,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      initAll();
    });
  } else {
    initAll();
  }
})();
