// Hilfe-Dialog zu einer Berechtigung (_rechte_hilfe_dialog.html): Klick auf ein
// Element mit data-rechte-hilfe zeigt, wo das Recht wirkt und wer es hat.
(function () {
    'use strict';

    var dialog = document.getElementById('perm-hilfe');
    var datenEl = document.getElementById('perm-hilfe-data');
    if (!dialog || !datenEl) return;
    var permHilfe = JSON.parse(datenEl.textContent);

    function chipListe(namen) {
        if (!namen.length) {
            var leer = document.createElement('div');
            leer.className = 'perm-hilfe-leer';
            leer.textContent = 'Niemand';
            return leer;
        }
        var chips = document.createElement('div');
        chips.className = 'member-chips';
        namen.forEach(function (name) {
            var span = document.createElement('span');
            span.className = 'member-chip';
            span.textContent = name;
            chips.appendChild(span);
        });
        return chips;
    }

    function zeige(perm) {
        var daten = permHilfe[perm];
        if (!daten) return;
        document.getElementById('perm-hilfe-titel').textContent = daten.titel;
        document.getElementById('perm-hilfe-kurz').textContent = daten.beschreibung;

        var liste = document.getElementById('perm-hilfe-stellen');
        liste.innerHTML = '';
        daten.stellen.forEach(function (stelle) {
            var li = document.createElement('li');
            var ort = document.createElement('span');
            ort.className = 'perm-hilfe-ort';
            ort.textContent = stelle.ort + ': ';
            var text = document.createElement('span');
            text.className = 'perm-hilfe-text';
            text.textContent = stelle.text;
            li.appendChild(ort);
            li.appendChild(text);
            if (stelle.mit) {
                var mit = document.createElement('span');
                mit.className = 'perm-hilfe-mit';
                mit.textContent = 'Nur zusammen mit dem Recht „' + stelle.mit + '“.';
                li.appendChild(mit);
            }
            liste.appendChild(li);
        });

        var titel = document.getElementById('perm-hilfe-inhaber-titel');
        var inhaber = document.getElementById('perm-hilfe-inhaber');
        var hinweis = document.getElementById('perm-hilfe-hinweis');
        inhaber.innerHTML = '';
        if (daten.quellen) {
            // Eigenes Profil: nur, worüber man das Recht selbst hat
            titel.textContent = 'Du hast dieses Recht über';
            inhaber.appendChild(chipListe(daten.quellen));
            hinweis.hidden = true;
        } else {
            titel.textContent = 'Wer dieses Recht hat';
            hinweis.hidden = false;
            if (!daten.inhaber.length) inhaber.appendChild(chipListe([]));
            daten.inhaber.forEach(function (quelle) {
                var block = document.createElement('div');
                block.className = 'perm-hilfe-quelle';
                var name = document.createElement('div');
                name.className = 'perm-hilfe-quelle-name';
                name.textContent = quelle.quelle;
                block.appendChild(name);
                block.appendChild(chipListe(quelle.namen));
                inhaber.appendChild(block);
            });
        }
        dialog.showModal();
        dialog.scrollTop = 0;
    }

    document.querySelectorAll('[data-rechte-hilfe]').forEach(function (el) {
        el.addEventListener('click', function () { zeige(el.dataset.rechteHilfe); });
        if (el.tagName !== 'BUTTON') {
            el.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    zeige(el.dataset.rechteHilfe);
                }
            });
        }
    });
    dialog.querySelector('.dialog-close').addEventListener('click', function () {
        dialog.close();
    });
    // Klick auf den abgedunkelten Hintergrund schließt ebenfalls. Der Innenabstand
    // gehört auch zum <dialog>, deshalb entscheidet das Rechteck, nicht e.target.
    dialog.addEventListener('click', function (e) {
        if (e.target !== dialog) return;
        var r = dialog.getBoundingClientRect();
        if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) {
            dialog.close();
        }
    });
})();
