// Verhalten der Listenseiten: Nachladen beim Scrollen, „Neuer Ordner" im
// Ordnerbrowser, das Zusammenfassen gleicher Stimmen und der Klick auf ein Bild.
//
// Frueher stand das alles als <script> in table.html und ging mit **jeder**
// Listenseite neu ueber die Leitung — rund 9 KB je Aufruf. Hier wird es einmal
// geladen und liegt danach im Zwischenspeicher des Browsers (/static/ mit
// Jahresfrist). Jeder Teil prueft selbst, ob es auf dieser Seite etwas zu tun
// gibt, deshalb schadet das Laden auf Seiten ohne Tabelle nicht.
//
// Die beiden Adressen, die frueher aus der Vorlage kamen, stehen jetzt als
// data-Attribute an zwei leeren Elementen (#ordner-anlegen, #galerie-link) —
// dasselbe Muster wie bei notify.js.

    (function () {
      var sentinel = document.getElementById('table-sentinel');
      var tableView = sentinel && sentinel.closest('.table-view');
      var container = tableView && tableView.querySelector('.table-container');
      var tbody = container && container.querySelector('table tbody');
      if (!sentinel || !container || !tbody) return;
      // The sentinel must live inside the scrollable .table-container so it can
      // actually scroll into view — .table-view itself has overflow: hidden.
      container.appendChild(sentinel);
      var loading = false, done = false;
      function buildUrl(offset) {
        var p = new URLSearchParams(window.location.search);
        p.set('offset', offset);
        return window.location.pathname + '?' + p.toString();
      }
      function loadMore() {
        if (loading || done) return;
        var offset = parseInt(sentinel.dataset.nextOffset, 10);
        loading = true;
        sentinel.classList.add('loading');
        fetch(buildUrl(offset), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
          .then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
          })
          .then(function (data) {
            tbody.insertAdjacentHTML('beforeend', data.html);
            if (data.has_more) {
              sentinel.dataset.nextOffset = data.next_offset;
            } else {
              done = true;
              observer.disconnect();
              sentinel.remove();
            }
          })
          .catch(function (e) { console.error('Infinite scroll error:', e); })
          .finally(function () {
            loading = false;
            if (!done) sentinel.classList.remove('loading');
          });
      }
      var observer = new IntersectionObserver(function (entries) {
        if (entries[0].isIntersecting) loadMore();
      }, { root: container, rootMargin: '200px' });
      observer.observe(sentinel);
    })();

    (function() {
        var anker = document.getElementById('ordner-anlegen');
        if (!anker) return;
        var createUrl = anker.dataset.url;
        var container = document.querySelector('.table-container');
        if (!container) return;
        var tbody = container.querySelector('table tbody');
        if (!tbody) return;

        var nfRow = document.createElement('tr');
        nfRow.id = 'new-folder-row';
        nfRow.className = 'nf-row';
        nfRow.style.display = 'none';
        nfRow.innerHTML =
            '<td></td>' +
            '<td style="width:15px"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></td>' +
            '<td><div class="nf-name-cell">' +
            '<input type="text" id="nf-input" class="nf-input" placeholder="Ordnername" autocomplete="off">' +
            '<button type="button" class="nf-btn nf-confirm" title="Erstellen"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></button>' +
            '<button type="button" class="nf-btn nf-cancel" title="Abbrechen"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>' +
            '</div></td>' +
            '<td colspan="5"></td>';
        tbody.appendChild(nfRow);

        var nfInput = document.getElementById('nf-input');
        var nfConfirm = nfRow.querySelector('.nf-confirm');
        var nfCancel = nfRow.querySelector('.nf-cancel');

        window.showNewFolderRow = function() {
            nfRow.style.display = '';
            nfInput.value = '';
            nfInput.classList.remove('nf-error');
            nfInput.focus();
        };

        function hideRow() {
            nfRow.style.display = 'none';
            nfInput.value = '';
            nfInput.classList.remove('nf-error');
        }

        function submitFolder() {
            var name = nfInput.value.trim();
            if (!name) { nfInput.classList.add('nf-error'); nfInput.focus(); return; }
            var csrf = document.querySelector('[name=csrfmiddlewaretoken]');
            if (!csrf) return;
            nfInput.disabled = true;
            nfConfirm.disabled = true;
            fetch(createUrl, {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'name=' + encodeURIComponent(name) + '&csrfmiddlewaretoken=' + encodeURIComponent(csrf.value),
            })
            .then(function(r) {
                return r.json().catch(function() { return {}; }).then(function(data) {
                    if (!r.ok) throw new Error(data.error || '');
                    return data;
                });
            })
            .then(function(data) {
                if (data.html) nfRow.insertAdjacentHTML('beforebegin', data.html);
                nfInput.value = '';
                nfInput.classList.remove('nf-error');
                nfInput.focus();
            })
            .catch(function(e) {
                nfInput.classList.add('nf-error');
                // Die Meldung des Servers (etwa: Name schon vergeben) am Feld zeigen.
                if (e.message) {
                    nfInput.disabled = false;
                    nfInput.setCustomValidity(e.message);
                    nfInput.reportValidity();
                }
            })
            .finally(function() { nfInput.disabled = false; nfConfirm.disabled = false; });
        }

        nfConfirm.addEventListener('click', submitFolder);
        nfCancel.addEventListener('click', hideRow);
        nfInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') { e.preventDefault(); submitFolder(); }
            else if (e.key === 'Escape') hideRow();
            else { nfInput.classList.remove('nf-error'); nfInput.setCustomValidity(''); }
        });
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && nfRow.style.display !== 'none') hideRow();
        });
    })();

    (function () {
        'use strict';
        var params = new URLSearchParams(window.location.search);
        var sort = params.get('sort');
        if (sort !== 'stimme' && sort !== '-stimme') return;

        var table = document.querySelector('table.mitglied-table');
        if (!table) return;

        var headers = Array.from(table.querySelectorAll('thead th'));
        var stimmeIdx = headers.findIndex(function (th) {
            return th.textContent.trim() === 'Stimme';
        });
        if (stimmeIdx < 0) return;

        var tbody = table.querySelector('tbody');

        function clearMerge() {
            tbody.querySelectorAll('.stimme-merged-inner').forEach(function (inner) {
                var td = inner.parentElement;
                if (td) td.textContent = inner.textContent;
            });
            tbody.querySelectorAll('[data-stimme-hidden]').forEach(function (td) {
                td.style.display = '';
                td.removeAttribute('data-stimme-hidden');
            });
            tbody.querySelectorAll('.stimme-merged-cell').forEach(function (td) {
                td.removeAttribute('rowspan');
                td.classList.remove('stimme-merged-cell');
            });
            tbody.querySelectorAll('.stimme-group-start').forEach(function (tr) {
                tr.classList.remove('stimme-group-start');
            });
        }

        function flush(group) {
            group.firstRow.classList.add('stimme-group-start');
            if (group.cells.length > 1) {
                var first = group.cells[0];
                first.rowSpan = group.cells.length;
                first.classList.add('stimme-merged-cell');
                var inner = document.createElement('span');
                inner.className = 'stimme-merged-inner';
                inner.textContent = first.textContent;
                first.textContent = '';
                first.appendChild(inner);
                for (var i = 1; i < group.cells.length; i++) {
                    group.cells[i].style.display = 'none';
                    group.cells[i].setAttribute('data-stimme-hidden', '1');
                }
            }
        }

        function applyMerge() {
            clearMerge();
            var rows = Array.from(tbody.querySelectorAll('tr'));
            var current = null;
            rows.forEach(function (row) {
                var cells = Array.from(row.querySelectorAll('td'));
                var stimmeCell = cells[stimmeIdx];
                if (!stimmeCell) return;
                var val = stimmeCell.textContent.trim();
                if (current && current.val === val) {
                    current.cells.push(stimmeCell);
                } else {
                    if (current) flush(current);
                    current = { val: val, firstRow: row, cells: [stimmeCell] };
                }
            });
            if (current) flush(current);
        }

        applyMerge();

        new MutationObserver(function (mutations) {
            if (mutations.some(function (m) { return m.addedNodes.length; })) {
                applyMerge();
            }
        }).observe(tbody, { childList: true });
    }());

(function () {
  var anker = document.getElementById('galerie-link');
  if (!anker) return;
  var galleryUrl = anker.dataset.url;
  document.addEventListener("click", function (e) {
    var tr = e.target.closest("tr[data-type='File']");
    if (!tr) return;
    if (!(tr.dataset.mime || "").startsWith("image/")) return;
    if (e.target.closest("a, button, input, select, textarea, label")) return;
    e.stopImmediatePropagation();
    window.location.href = galleryUrl + "?bild=" + tr.dataset.id;
  }, true);
}());
