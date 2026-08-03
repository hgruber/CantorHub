"""Read-only CardDAV-Server: das Mitgliederverzeichnis als Geräte-Adressbuch.

Verteilt die Kontaktdaten der aktiven Mitglieder — inklusive Profilfoto — an
Android (DAVx⁵) und iOS. Angemeldet wird sich per HTTP-Basic mit dem normalen
Portal-Passwort; geschrieben werden kann nichts.

Umfang (RFC 6352 CardDAV, RFC 6764 Discovery, RFC 6350 vCard):

* ``OPTIONS`` auf jede Ressource, ``PROPFIND`` Depth 0/1, ``GET`` auf eine
  ``.vcf``, ``REPORT addressbook-multiget`` und ``addressbook-query``.
* ``PUT``/``DELETE``/``MKCOL``/``PROPPATCH``/``LOCK`` antworten 405.

Bewusst **nicht** implementiert:

* ``REPORT sync-collection`` (RFC 6578). Es bräuchte ein Sync-Journal, das auch
  Löschungen nachhält — der mit Abstand teuerste Teil einer CardDAV-Implementierung
  und für rund achtzig Kontakte sinnlos. DAVx⁵ fällt laut Handbuch auf PROPFIND
  zurück, iOS auf ``getctag``. Deshalb wird ``sync-collection`` auch nicht in
  ``supported-report-set`` genannt und ``D:sync-token`` als 404 gemeldet: einen
  Report anzubieten und dann nicht zu liefern ist schlimmer als ihn wegzulassen.
* Die Filterauswertung in ``addressbook-query``. Der Report wird beantwortet,
  ``<C:filter>`` aber ignoriert und immer alles geliefert. Bei einem read-only
  Dienst ist Über-Lieferung folgenlos, und Clients benutzen den Report ohnehin
  vor allem als „gib mir alle ETags".

Modulschnitt — er folgt der Testbarkeitsregel des Projekts (vgl.
``mailingliste.lese_abmelde_token`` vs. ``read_abmelde_token``): alles, was die
Datenbank oder den Dateispeicher anfasst, steckt in :mod:`~intern.carddav.daten`.
:mod:`~intern.carddav.vcard` ist rein und damit vollständig mit
``SimpleTestCase`` prüfbar.

Was sich Adressbuch und Kalender teilen — WebDAV-XML, HTTP-Basic, die
Antwortbausteine und die Zeilenfaltung —, steht in :mod:`intern.dav`. Dieses
Paket enthält nur noch, was das Adressbuch allein ausmacht.
"""
