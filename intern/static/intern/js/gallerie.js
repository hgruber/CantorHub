/**
 * gallerie.js — Lightbox for the CantorHub image gallery.
 *
 * Vanilla JS, no dependencies. Load with the `defer` attribute.
 * Reads image data from data-* attributes on each .gallery-cell button
 * and drives the lightbox markup already present in the DOM.
 */

(function () {
  'use strict';

  // -------------------------------------------------------------------------
  // Guard: nothing to do when the page has no gallery cells
  // -------------------------------------------------------------------------

  const cells = Array.from(document.querySelectorAll('.gallery-cell'));
  if (cells.length === 0) return;

  // -------------------------------------------------------------------------
  // Build item list from data attributes
  // -------------------------------------------------------------------------

  const items = cells.map(el => ({
    url:         el.dataset.url,
    name:        el.dataset.name        || '',
    description: el.dataset.description || '',
    owner:       el.dataset.owner       || '',
  }));

  let current     = 0;
  let lastFocused = null; // cell that opened the lightbox — restored on close

  // -------------------------------------------------------------------------
  // DOM references — bail early if the lightbox markup is absent
  // -------------------------------------------------------------------------

  const backdrop  = document.getElementById('lb-backdrop');
  const closeBtn  = document.getElementById('lb-close');
  const prevBtn   = document.getElementById('lb-prev');
  const nextBtn   = document.getElementById('lb-next');
  const stage     = document.getElementById('lb-stage');
  const img       = document.getElementById('lb-img');
  const counter   = document.getElementById('lb-counter');
  const nameEl    = document.getElementById('lb-name');
  const descEl    = document.getElementById('lb-description');
  const ownerEl   = document.getElementById('lb-owner');
  const ownerText = document.getElementById('lb-owner-text');

  if (!backdrop || !img) return;

  // -------------------------------------------------------------------------
  // Core: show(index)
  // Updates image, counter, and caption with a brief cross-fade.
  // -------------------------------------------------------------------------

  function show(index) {
    // Wrap around in both directions
    current = ((index % items.length) + items.length) % items.length;
    const item = items[current];

    // Fade out current image
    img.classList.add('lb-fading');

    setTimeout(() => {
      // Swap content
      img.src = item.url;
      img.alt = item.name;

      counter.textContent   = `${current + 1} / ${items.length}`;
      nameEl.textContent    = item.name;
      descEl.textContent    = item.description;
      ownerText.textContent = item.owner;
      ownerEl.classList.toggle('lb-owner--hidden', item.owner === '');

      // Fade back in on the next paint so the browser registers the class removal
      requestAnimationFrame(() => {
        img.classList.remove('lb-fading');
      });
    }, 150); // slightly under the 180 ms CSS transition — imperceptible gap

    // Preload neighbouring images in the background
    preload((current + 1) % items.length);
    preload((current - 1 + items.length) % items.length);
  }

  // -------------------------------------------------------------------------
  // Core: open(index) / close()
  // -------------------------------------------------------------------------

  function open(index) {
    lastFocused = document.activeElement;
    show(index);
    backdrop.classList.add('lb-open');
    backdrop.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    // Move focus into the lightbox for keyboard users
    closeBtn.focus();
  }

  function close() {
    backdrop.classList.remove('lb-open');
    backdrop.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    // Return focus to the cell that triggered the lightbox
    if (lastFocused && typeof lastFocused.focus === 'function') {
      lastFocused.focus();
    }
  }

  // -------------------------------------------------------------------------
  // Helper: preload a single image silently
  // -------------------------------------------------------------------------

  function preload(index) {
    if (items[index]) {
      (new Image()).src = items[index].url;
    }
  }

  // -------------------------------------------------------------------------
  // Grid: open lightbox when a thumbnail is clicked
  // -------------------------------------------------------------------------

  cells.forEach(cell => {
    cell.addEventListener('click', () => {
      open(parseInt(cell.dataset.index, 10));
    });
  });

  // -------------------------------------------------------------------------
  // Lightbox controls
  // -------------------------------------------------------------------------

  closeBtn.addEventListener('click', close);

  prevBtn.addEventListener('click', () => show(current - 1));
  nextBtn.addEventListener('click', () => show(current + 1));

  // Clicking the dark backdrop or the empty stage area closes the lightbox;
  // clicking the image itself does not (event target is the <img> element).
  backdrop.addEventListener('click', e => {
    if (e.target === backdrop || e.target === stage) {
      close();
    }
  });

  // -------------------------------------------------------------------------
  // Keyboard navigation (only active while lightbox is open)
  // -------------------------------------------------------------------------

  document.addEventListener('keydown', e => {
    if (!backdrop.classList.contains('lb-open')) return;

    switch (e.key) {
      case 'Escape':
        e.preventDefault();
        close();
        break;
      case 'ArrowLeft':
        e.preventDefault();
        show(current - 1);
        break;
      case 'ArrowRight':
        e.preventDefault();
        show(current + 1);
        break;
    }
  });

  // -------------------------------------------------------------------------
  // Touch swipe: swipe left → next image, swipe right → previous image
  // -------------------------------------------------------------------------

  let touchStartX = null;

  backdrop.addEventListener('touchstart', e => {
    touchStartX = e.changedTouches[0].clientX;
  }, { passive: true });

  backdrop.addEventListener('touchend', e => {
    if (touchStartX === null) return;
    const delta = e.changedTouches[0].clientX - touchStartX;
    touchStartX = null;

    if (Math.abs(delta) < 50) return; // too short — treat as tap, not swipe
    if (delta < 0) {
      show(current + 1); // swipe left  → next
    } else {
      show(current - 1); // swipe right → prev
    }
  }, { passive: true });

})();
