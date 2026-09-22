# Änderungen

Ein Abschnitt je Auslieferung. Was noch kein Tag hat, sammelt sich unter
„Unveröffentlicht"; zur Freigabe wird diese Überschrift auf die Version umbenannt, committet und
erst dann getaggt. Das Bare-Repo nimmt ein Versions-Tag ohne gefüllten Abschnitt nicht an —
siehe `update.sh` und `README.md`.

Vorabversionen (`v1.0.0-rc3`) brauchen keinen eigenen Abschnitt: für sie genügt „Unveröffentlicht"
oder der Abschnitt ihrer Endfassung. Verlangt wird er für Endfassungen. Einen eigenen bekommen
dürfen sie trotzdem — er bleibt dann unter der Endfassung stehen.

## Unveröffentlicht

- Foren: die Trennlinie „Neu seit Deinem letzten Besuch" erschien nach dem vorigen Fix gar
  nicht mehr, wenn der älteste ungelesene Beitrag hinter den ersten 25 lag — auch dann nicht,
  wenn das Scrollen die Grenze nachgeladen hatte. Die erste nachgeladene Seite, die den
  ältesten Ungelesenen enthält, zeichnet sie jetzt unter ihm; solange noch ältere Ungelesene
  unterhalb liegen, bleibt sie weg. Der Lesestand läuft dafür über die Sentinel-Kette als
  `bis_id`-Parameter mit (`forum_more` rechnet mit demselben `trenner_id`/
  `hat_aeltere_ungelesene`-Paar nach)
- Foren: die Trennlinie „Neu seit Deinem letzten Besuch" erschien auch, wenn der älteste
  ungelesene Beitrag älter als die 25 neuesten war — sie saß dann nach der 25.-neuesten
  Nachricht, und die beim Scrollen nachgeladenen, ebenfalls ungelesenen Beiträge erschienen
  unter ihr. Sie bleibt jetzt ganz weg, wenn unterhalb des Fensters noch Ungelesene liegen
  (`hat_aeltere_ungelesene`, eine `exists()`-Abfrage), wie in `docs/forum.md` vorgesehen
- Migration: ein Lauf mit `MIGRATE=1` gegen MySQL verwarf die Datenbank, ließ `media/` aber
  stehen. Weil filer jeder Datei beim Import einen frischen UUID-Pfad gibt, überschrieb der
  nächste Import nichts, sondern legte den gesamten Bestand daneben — das Volume wuchs bei
  jeder Migration um den vollen Datenbestand (allein `public/` sind 2,5 GB), und die Blobs des
  vorherigen Laufs waren anschließend von keiner Zeile mehr auffindbar. `start.sh` räumt
  `media/` jetzt für beide Datenbanken ab, nicht nur im SQLite-Zweig
- Neues Kommando `cleanup_verwaiste_blobs`: meldet Dateien unter `MEDIA_ROOT`, zu denen es
  keine Datenbankzeile mehr gibt, und löscht sie auf ausdrückliches `--loeschen`. Für die
  Volumes gedacht, auf denen sich das oben beschriebene Wachstum bereits angesammelt hat.
  Es ist **kein** Ersatz für `filer_check --delete-orphans`, sondern dessen sichere Fassung:
  es kennt die `DateiVersion`-Blobs, die bewusst ohne `filer.File`-Zeile liegen, und ebenso
  die Vorschauen, die neben ihrem Blob statt unter der Thumbnail-`base_dir` landen

## v1.0.0-rc2 — 2026-09-21

- Foren: der Trenner „Neu seit Deinem letzten Besuch" stand bei Nachrichten aus derselben
  Sekunde an der falschen Stelle, wodurch die Zahl der sichtbar neuen Beiträge um eins vom
  Badge abwich — mal einer zu viel, mal einer zu wenig. Die Liste sortierte nach dem Zeitpunkt,
  der nur sekundengenau gespeichert wird; Lesemarker, Trenner, Nachladen und der
  Fünf-Sekunden-Poll rechnen dagegen alle mit der laufenden Nummer. Jetzt tut es die Anzeige
  auch. Nebenbei behoben: fiel ein solcher Gleichstand genau auf die Grenze der ersten 25
  Nachrichten, wurde eine Nachricht beim Hochscrollen übersprungen und war gar nicht mehr zu
  sehen
- Forenliste: die Zahl ungelesener Nachrichten steht jetzt als Badge in der Spalte „Anzahl",
  vor der Gesamtzahl, die dafür gedämpft gesetzt ist. Bisher hing sie hinter dem Themennamen
  und wanderte je nach dessen Länge über die Zeile, weit weg von der Zahl, auf die sie sich
  bezieht. Die fett gesetzte Zeile, der Punkt am Menüeintrag „Forum" und der Trenner „Neu seit
  Deinem letzten Besuch" bleiben unverändert
- Mitgliederliste: die Stimme steht jetzt in einem kräftigen Farbbalken am linken Zeilenrand
  statt in einem blassen Flächen-Tint — die Zeilen sind wieder neutral und haben ihre
  Zebrastreifen zurück. Sopran bis Bass bekommen eine eigene Palette mit klar getrennten
  Farbtönen und nach Tonhöhe abnehmender Helligkeit, Chorleiter und Musiker einen neutralen
  Ton; dieselben Farben tragen auch die Stimm-Kennzeichen auf der Aufgabenseite
- Konfigurationsseite: ein Banner über den Gruppen zählt, wie viele Pflicht-Einstellungen noch
  leer sind, und nennt die Schlüssel, zu denen es gar keine Zeile gibt. Nach einer frischen
  Installation sind das die fünf, die der Betreiber liefern muss: `VEREINS_URL`, `VEREINSNAME`,
  `VEREINSNAME_KURZ`, `HOMEPAGE_UEBER_UNS`, `HOMEPAGE_AUFNAHME`. Getrennt davon, in neutralem
  Grau statt als Warnung, nennt derselbe Banner Dienste, die mangels Schlüssel nicht laufen —
  E-Mail-Versand und XMPP-Brücke. Das ist kein Fehler und kann so gewollt sein, aber ohne
  Mailversand gibt es weder Aktivierung noch Passwort-Zurücksetzen, Rückbestätigung oder
  Auftritts-Erinnerung; das sollte man nicht erst im Betrieb merken
- Rundmail an Mitglieder: ohne konfigurierten SMTP-Server ist der Senden-Knopf ausgegraut und
  nennt im Tooltip den Grund, statt eine Mail zu melden, die nur im Log landet. Die Seite selbst
  bleibt erreichbar, Text und Anhänge lassen sich weiter vorbereiten
- Auftritts-Erinnerungen: die Warnung über fehlende Mailkonfiguration erscheint nur noch, wenn
  wirklich eine Erinnerung fällig ist — kein Dauerrauschen im Log mehr
- Changelog-Pflicht: das Bare-Repo weist ein Versions-Tag ab, dessen Commit keinen gefüllten
  `CHANGELOG.md`-Abschnitt für genau diese Version trägt (`update.sh`); Vorabversionen dürfen sich
  auf „Unveröffentlicht" oder den Abschnitt ihrer Endfassung stützen
- `:latest` folgt einer Vorabversion nur, solange noch keine Endfassung getaggt ist — der Schalter
  `LATEST_FUER_VORAB` im `post-receive`-Hook entfällt

## v1.0.0-rc1 — 2026-09-20

- Erste Auslieferung als Podman-Abbild: der Code steckt im Abbild, veränderlich bleibt allein
  `/data`; ein `git pull` auf dem Server gibt es nicht mehr
- Eine einzige Datenbankvariable (`DATABASE_URL`), die Version kommt aus dem Git-Tag
- `post-receive`-Hook auf dem Server: ein Versions-Tag baut das Abbild, ein Push auf `master`
  ändert am Betrieb nichts
- Mitgliederverwaltung mit Neuaufnahme, Rückbestätigung und Austritt, Feld-für-Feld-Privatsphäre
- Termine mit Zusagen, Aufstellung und Terminbanner; Titelliste mit Konzertprogrammen
- Foren, an XMPP-Räume gebrückt, mit Reaktionen und Ungelesen-Markern je Mitglied
- Versioniertes Wiki, Dateiarchiv mit Ordnerrechten und Versionsverlauf, öffentliche Homepage
- CardDAV-Adressbuch und CalDAV-Kalender für das Telefon (beide vorerst abgeschaltet)
- Öffentliche Auftritts-Mailingliste mit Double-Opt-in
- Hell/Dunkel-Umschaltung und Schriftgrößenregler in der Seitenleiste
- Fremde CDNs entfernt, Kartenkacheln nur über den eigenen Proxy
- Listenseiten deutlich beschleunigt: Abfragen je Zeile beseitigt, Zwischenspeicher über die
  Tabellenausgabe, Sitzungsfrist nur noch alle fünf Minuten verlängert
