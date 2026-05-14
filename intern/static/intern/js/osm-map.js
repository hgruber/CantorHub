// Leaflet's default tile <img> elements send no usable Referer, which OSM's
// volunteer tile servers reject with 403. Forcing referrerPolicy to "origin"
// makes the browser attach the site origin as Referer. Loaded once after
// Leaflet in base.html; patches every map on the site.
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
})();
