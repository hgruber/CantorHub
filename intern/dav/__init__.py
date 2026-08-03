"""Gemeinsamer Unterbau der beiden read-only DAV-Dienste.

Hier steht, was das Adressbuch (:mod:`intern.carddav`) und der Kalender
(:mod:`intern.caldav`) wörtlich teilen — und nur das:

* :mod:`~intern.dav.xml` — WebDAV-XML: Multistatus bauen, PROPFIND- und
  REPORT-Rümpfe lesen.
* :mod:`~intern.dav.auth` — HTTP-Basic gegen das Portal-Passwort, samt
  Verifikations-Zwischenspeicher und IP-Drossel, pro Dienst parametrisiert.
* :mod:`~intern.dav.http` — die Antwortbausteine, die jede DAV-View braucht
  (207, OPTIONS, 405, Depth, ``current-user-privilege-set``).
* :mod:`~intern.dav.text` — Zeilenfaltung, TEXT-Escaping und die
  ETag-/CTag-Hashes. vCard 3.0 (RFC 6350 §3.2/§3.4) und iCalendar
  (RFC 5545 §3.1/§3.3.11) falten und escapen identisch, also gibt es das
  einmal.

Was *ein* Dienst allein braucht, gehört nicht hierher: die Serialisierung, die
Datenauswahl und die Views bleiben in seinem eigenen Paket.

Alle Module hier sind frei von Datenbankzugriff (Ausnahme:
:mod:`~intern.dav.auth` liest den ``User`` zur Anmeldung) und damit mit
``SimpleTestCase`` prüfbar — die Testbarkeitsregel des Projekts, denn eine
Testdatenbank würde die Migration ``0003_import`` und mit ihr den
MySQL-Altbestand anfassen.
"""
