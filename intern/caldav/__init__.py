"""Read-only CalDAV-Server: die Termine des Chors als Gerätekalender.

Das Gegenstück zu :mod:`intern.carddav` — gleiche Bauart, gleiche Anmeldung
(HTTP-Basic mit dem Portal-Passwort), gleiche Regel: geschrieben werden kann
nichts.

Zwei Sammlungen:

* **Termine** — jeder ``Termin`` als ``VEVENT``, mit Ort, Koordinaten und
  Rückverweis ins Portal.
* **Geburtstage** — jährlich wiederkehrend, nur von aktiven Mitgliedern, die das
  Feld nicht verborgen haben. Abschaltbar über ``CALDAV_GEBURTSTAGE``.

Umfang (RFC 4791 CalDAV, RFC 6764 Discovery, RFC 5545 iCalendar):

* ``OPTIONS`` auf jede Ressource, ``PROPFIND`` Depth 0/1, ``GET`` auf eine
  ``.ics``, ``REPORT calendar-multiget`` und ``calendar-query``.
* ``PUT``/``DELETE``/``MKCOL``/``PROPPATCH``/``LOCK`` antworten 405.

Bewusst **nicht** implementiert:

* ``REPORT sync-collection`` (RFC 6578) — dieselbe Begründung wie beim
  Adressbuch: es bräuchte ein Sync-Journal, das auch Löschungen nachhält.
  Deshalb steht es weder in ``supported-report-set``, noch wird ``D:sync-token``
  beantwortet.
* ``VTODO`` und ``VJOURNAL``. Ein ``calendar-query``, der danach fragt, bekommt
  eine leere Antwort statt ersatzweise Termine.
* Scheduling (RFC 6638), Free/Busy, ``VALARM``. Erinnerungen setzt jeder auf
  seinem Gerät selbst.
* ``Termin.wiederholung``. Das Feld wird — wie im ICS-Feed und in der
  Monatsansicht — ignoriert; wiederkehrend ist einzig der Geburtstag.

Der Inhalt ist für **jedes** Mitglied gleich: es gibt keine Terminrechte im
Portal, und die eigene Zu-/Absage steht bewusst nicht im ``VEVENT``. Sie machte
jeden ETag kontobezogen und damit den ganzen Abgleich teurer, als der Nutzen
rechtfertigt.

Modulschnitt wie beim Adressbuch (Testbarkeitsregel des Projekts): alles, was
Datenbank oder Konfiguration anfasst, steckt in :mod:`~intern.caldav.daten`;
:mod:`~intern.caldav.ical` ist rein und mit ``SimpleTestCase`` prüfbar. Der
gemeinsame Unterbau — XML, Anmeldung, Antwortbausteine — liegt in
:mod:`intern.dav`.
"""
