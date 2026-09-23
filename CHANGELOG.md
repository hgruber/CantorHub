# Änderungen

Alle nennenswerten Änderungen an diesem Projekt stehen in dieser Datei, die jüngste oben.

Das Format folgt [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), die Auslieferungen
folgen [semantischer Versionierung](https://semver.org/lang/de/). Ein Eintrag sagt in höchstens
drei Sätzen, *was* sich ändert — wie es dazu kam, steht im Commit. Wie eine Auslieferung
freigegeben wird (Sammelabschnitt umbenennen, committen, taggen), steht in `README.md`.

## v1.0.0-rc4 — 2026-09-23

### Hinzugefügt

- Änderungen: die Versionszeile in der Seitenleiste führt auf die neue Seite `/intern/changelog/`,
  die `CHANGELOG.md` zeigt — je Auslieferung eine Karte mit Kennung und Datum, die laufende Version
  mit Markenkante und der Pille „Deine Version". Ältere Auslieferungen lädt ein Sentinel zu zweien
  nach (`views/_pagination.py`). Gelesen wird die Datei von `intern/auslieferungen.py`, einem
  eigenen Zerleger ohne Markdown-Abhängigkeit im Abbild.
- Terminseite: `Termin.extern` bekommt eine eigene Karte „Extern"; sie fehlt, solange das Feld leer
  ist. Termin bearbeiten bekommt eine Kachel „Extern" mit dem Ankündigungstext (mehrzeilig, HTML
  erlaubt) — aus dem Kalender-Offcanvas bleibt das Feld draußen.
- Terminliste: zwei schmale Spalten zwischen Datum und Termin — ein Mikrofon für Termine mit
  Ankündigungstext und, bei „Repertoire", eine Pille mit der Zahl der Lieder im Ablauf. Die Zahl
  kommt als Annotation mit der Liste, das Datum bricht nicht mehr um. Dieselbe Marke trägt im
  Kalender der Termin-Chip, dort nur am ersten Tag eines mehrtägigen Termins.

### Geändert

- Mitgliedskarte: die Seite ist kein umrandeter Kasten mehr, sondern folgt dem Muster der übrigen
  Detailseiten — Seitenkopf mit Porträt und Namen, die Abschnitte als Karten in zwei Spalten. Die
  vier Kopfzeilen „Vorname: / Nachname: / Stimme: / Gruppen:" sind entfallen, die Stimme steht als
  Wort neben den Gruppen-Marken, und die Liedlisten laufen über die volle Breite.
- Die Stimme ist der Akzent der Seite, jetzt ohne Kasten: eine 4 px breite Kante am linken
  Seitenrand und ein 3-px-Ring um das Porträt. Das `(S)` neben dem Namen ist eine Pille in der
  Stimmenfarbe und sitzt **neben** dem Titel statt darin — der Titel kürzt lange Namen mit einer
  Ellipsis ab und fraß genau das `(S)`.
- Startseite: unter „Konzerte" stehen jetzt die Termine mit einem **Ankündigungstext**
  (`Termin.extern`), und der Text wird mit ausgegeben (Adresse, Einlass, Eintritt, Links). **Zum
  Ausrollen:** ein Auftritt ohne Eintrag fehlt auf der Startseite — für einen Auftritt ohne Text
  genügt ein Leerzeichen, er wird dann ohne Ankündigungsblock gelistet.
- Die Erinnerungsmails der Auftritts-Mailingliste hängen am Ankündigungstext (`Termin.extern`)
  statt an „Repertoire": erinnert wird, was öffentlich angekündigt ist. „Repertoire" steuert
  jetzt nur noch die Karte „Lieder" auf der Terminseite. **Zum Ausrollen:** ein Auftritt mit
  „Repertoire", aber ohne Ankündigungstext wird nicht mehr erinnert — er braucht einen Text.
- Datumsangaben nennen den kurzen Wochentag und den Monat als Zahl („Mi, 24.09.2026 19:30" statt
  „24. September 19:30") — betroffen sind alle Ausgaben über `replacements.format_datetime`. Die
  Verzweigungen für „heute" (nur Uhrzeit) und „gestern" bleiben wie sie waren.
- Terminliste: die Spalte „Du" ist entfallen; statt ihrer pulsiert bei offener Antwort das eigene
  Kästchen der Aufstellung und mit ihm der Terminname. Beides gilt nur für kommende Termine ohne
  eigene Antwort, und wer Bewegung reduziert haben will, bekommt die Rahmen stehend statt blinkend.
- Der Neuaufbau aus dem Altsystem startet mit den Gründerinnen und Gründern als einzigen aktiven
  Konten (Eintrittsdatum 17.06.2026); jeder andere Zugang kommt ohne Eintrittsdatum und deaktiviert
  an und wird einzeln über die Mitgliederverwaltung freigeschaltet. Die Deaktivierung läuft dabei
  nach dem Avatar-Import, der `is_active` prüft.
- Die Altdaten bringen eigenes HTML mit; beim Anzeigen werden Zeilenumbrüche zu `<br>`,
  `style`-Angaben entfernt und Überschriften zu `<strong>` (55 der 74 Zeilen beginnen mit `<h1>`).
  Der gespeicherte Wert bleibt unberührt — eine Anzeigeregel, keine Sanitisierung.
- Diese Datei folgt jetzt Keep a Changelog: je Auslieferung eine Gruppe nach Art der Änderung, je
  Eintrag höchstens drei Sätze. Die Überschriften bleiben wie sie waren, der `update`-Hook
  vergleicht das zweite Feld der Zeile mit dem Tagnamen.
- Die Karten der Änderungsseite sind auf 1280 px gedeckelt und bleiben linksbündig.

### Behoben

- Chorleiter und Musiker: der senkrecht beschriftete Gruppenstreifen der Mitgliederliste und die
  neutrale Topbar-Pille stehen jetzt in `--t3`, weil `--t4` auf seiner Tintfläche nur 2,2:1
  erreichte. Balken und Kartenkante bleiben bei `--t4`: ein Strich darf leise sein, ein Buchstabe
  nicht.
- Die Markenfarbe als Schrift auf einer Karte ist ein eigener Token (`--brand-text`): im dunklen
  Thema stand sie dort bei 2,7:1. Vier Stellen, die sich dafür ein hartkodiertes Rosa gegeben
  hatten, folgen jetzt ebenfalls der Markenfarbe.

## v1.0.0-rc3 — 2026-09-22

### Hinzugefügt

- Neues Kommando `cleanup_verwaiste_blobs`: es meldet Dateien unter `MEDIA_ROOT`, zu denen es keine
  Datenbankzeile mehr gibt, und löscht sie auf ausdrückliches `--loeschen`. Es kennt die
  `DateiVersion`-Blobs, die bewusst ohne `filer.File`-Zeile liegen, und die Vorschauen neben ihrem
  Blob — deshalb ist es kein Ersatz für `filer_check --delete-orphans`, sondern dessen sichere
  Fassung.
- `UniqueConstraint(person, termin)` auf `Zusage`: zwei Antworten desselben Mitglieds für denselben
  Termin sind jetzt unmöglich. Am Bestand ändert das nichts (2873 Zusagen, keine Doppelung).
- `UniqueConstraint(person, abstimmung, option)` auf `Abstimmung` — bewusst nicht ohne `option`,
  denn eine Abstimmung darf mehrere Kreuze zulassen (`max_stimmen`) — dazu ein Index für das
  Abstimmungsfilter.
- `RegisterKonsistenzTest`: Änderungsprotokoll, Feldbeschriftungen und Dateikarten werden gegen die
  Modelle geprüft, und die Karten zusätzlich aus der Quelle gelesen, damit doppelte Schlüssel nicht
  lautlos verschwinden.

### Geändert

- `Zusage.option` ist ein `choices`-Feld geworden, der Wertebereich liegt in `intern/zusage.py`.
  Dieselben vier Antworten standen vorher an fünf Stellen, zwei Kopien waren schon auseinandergelaufen;
  die Beschriftungen bleiben wortgleich, weil `str(Zusage)` als Schnappschuss im Änderungsprotokoll
  liegt.
- Repertoire: die Suche der Titelliste greift jetzt über Titel, Komponist und Bearbeiter
  (ODER-verknüpft, `RepertoireFilter.filter_suche`). Parameter, Beschriftung und Formular bleiben
  unverändert, bestehende Links und der gemerkte Tabellenzustand greifen weiter; die
  Wiedergabelisten des Mini-Players folgen derselben Suche.
- Indizes: `db_index=True` neben `unique=True` und auf Fremdschlüsseln war wirkungslos und ist
  entfernt, `ChangeLog` hat jetzt einen Index auf `timestamp` statt zweien auf `user`. `Termin.datum`
  ist neu indiziert — danach filtern und sortieren Terminliste, Kalender, CalDAV und
  Erinnerungsversand.
- Aufräumen ohne Wirkung nach außen: die Avatar-Helfer und die Listen der verbergbaren
  Mitgliedsfelder liegen in `intern/avatare.py` und `intern/mitglied_felder.py`, und
  `ChangeLog.timestamp` benutzt `timezone.now` wie der Rest des Projekts.
- Startseite: das Foto ist freigelegt (der Hero liegt ohne Schleier, die Navigation trägt ein
  Milchglas, der Anrisstext ist entfallen), das Kontaktband ist markenrosé, der Fuß hell auf Creme.
  Gold ist als zweite Farbe dazugekommen, die Copyright-Zeile steht bei 5,2:1, und eine
  konfigurierte `BRAND_FARBE` wirkt jetzt auch hier (`_brand_boot.html` fehlte).

### Behoben

- Passwort zurücksetzen: ohne SMTP-Server nahm die Seite eine Anfrage an, die nur ins Log schrieb —
  die Erfolgsmeldung behauptete das Gegenteil. Der Knopf ist jetzt sichtbar gesperrt (Grund als
  Tooltip und als Satz darunter), ein POST wird gar nicht mehr angenommen.
- Foren: die Trennlinie „Neu seit Deinem letzten Besuch" erschien gar nicht mehr, wenn der älteste
  ungelesene Beitrag hinter den ersten 25 lag — auch nachgeladen nicht. Die erste nachgeladene
  Seite, die ihn enthält, zeichnet sie unter ihm; der Lesestand läuft dafür als `bis_id` durch die
  Sentinel-Kette.
- Foren: dieselbe Trennlinie saß auch falsch, wenn der älteste ungelesene Beitrag älter als die 25
  neuesten war — nachgeladene Ungelesene erschienen unter ihr. Sie bleibt jetzt weg, solange
  unterhalb des Fensters noch Ungelesene liegen (`hat_aeltere_ungelesene`, eine `exists()`-Abfrage).
- Änderungsprotokoll: `FIELD_LABELS` nannte den Schlüssel `gruppe` zweimal — „Signatur" und
  „Gruppe" —, und der spätere Eintrag verdrängte den früheren lautlos. Ein modellgenauer Eintrag
  wird jetzt zuerst befragt.
- Migration: ein Lauf mit `MIGRATE=1` gegen MySQL verwarf die Datenbank, ließ `media/` aber stehen —
  der nächste Import legte den ganzen Bestand daneben (filer vergibt je Datei einen frischen
  UUID-Pfad), das Volume wuchs bei jeder Migration um alles. `start.sh` räumt `media/` jetzt für
  beide Datenbanken ab, nicht nur im SQLite-Zweig.
- `Mitteilung.formatiert()` scheiterte an einer leeren Nachricht (die Spalte erlaubt `null`, Altdaten
  und XMPP-Bot); fehlender Text gilt jetzt als leerer Text. Die Spalte auf `NOT NULL` zu ziehen
  bräche `makemigrations` im `Dockerfile` und in `start.sh` („Migrations: never create `0004+`").
- `Konzert.lied` löschte beim entfernten Lied den ganzen Programmpunkt mit (`CASCADE`, obwohl das
  Feld `null` erlaubt); jetzt `SET_NULL` wie bei den übrigen nullbaren Verweisen. Ein gelöschtes
  Lied verliert seinen Platz im Ablauf, nicht den Programmpunkt.

### Entfernt

- Die `Konzert`- und `Lied`-Hilfsmethoden sowie `intern/fuzzy.py`. Der Titelvergleich hatte keinen
  Aufrufer mehr, und `fuzzy.py` ließ sich nicht einmal importieren — seine Abhängigkeit `rapidfuzz`
  stand nie in `requirements.txt`.

## v1.0.0-rc2 — 2026-09-21

### Hinzugefügt

- Changelog-Pflicht: das Bare-Repo weist ein Versions-Tag ab, dessen Commit keinen gefüllten
  `CHANGELOG.md`-Abschnitt für genau diese Version trägt (`update.sh`). Vorabversionen dürfen sich
  auf „Unveröffentlicht" oder den Abschnitt ihrer Endfassung stützen.

### Geändert

- Forenliste: die Zahl ungelesener Nachrichten steht als Badge in der Spalte „Anzahl", vor der
  gedämpften Gesamtzahl — vorher hing sie hinter dem Themennamen und wanderte mit dessen Länge über
  die Zeile. Fett gesetzte Zeile, Punkt am Menüeintrag und Trenner bleiben unverändert.
- Mitgliederliste: die Stimme steht als kräftiger Farbbalken am linken Zeilenrand statt in einem
  blassen Flächen-Tint, die Zeilen sind wieder neutral mit Zebrastreifen. Sopran bis Bass bekommen
  klar getrennte Farbtöne mit nach Tonhöhe abnehmender Helligkeit, Chorleiter und Musiker einen
  neutralen; dieselben Farben tragen die Stimm-Kennzeichen auf der Aufgabenseite.
- Konfigurationsseite: ein Banner zählt die noch leeren Pflicht-Einstellungen und nennt die
  Schlüssel ohne Zeile; nach einer frischen Installation sind das `VEREINS_URL`, `VEREINSNAME`,
  `VEREINSNAME_KURZ`, `HOMEPAGE_UEBER_UNS` und `HOMEPAGE_AUFNAHME`. Getrennt davon und in neutralem
  Grau nennt er Dienste, die mangels Schlüssel nicht laufen — ohne Mailversand gibt es weder
  Aktivierung noch Passwort-Zurücksetzen, Rückbestätigung oder Auftritts-Erinnerung.
- Rundmail an Mitglieder: ohne konfigurierten SMTP-Server ist der Senden-Knopf ausgegraut und nennt
  im Tooltip den Grund; die Seite bleibt erreichbar, Text und Anhänge lassen sich vorbereiten.
- Auftritts-Erinnerungen: die Warnung über fehlende Mailkonfiguration erscheint nur noch, wenn
  wirklich eine Erinnerung fällig ist.
- `:latest` folgt einer Vorabversion nur, solange noch keine Endfassung getaggt ist; der Schalter
  `LATEST_FUER_VORAB` im `post-receive`-Hook entfällt.

### Behoben

- Foren: der Trenner „Neu seit Deinem letzten Besuch" stand bei Nachrichten aus derselben Sekunde an
  der falschen Stelle, die Zahl der neuen Beiträge wich um eins vom Badge ab. Die Liste sortiert
  jetzt wie Lesemarker, Trenner, Nachladen und Poll nach der laufenden Nummer statt nach dem
  sekundengenauen Zeitpunkt. Nebenbei behoben: an der Grenze der ersten 25 Nachrichten wurde eine
  Nachricht beim Hochscrollen übersprungen.

## v1.0.0-rc1 — 2026-09-20

### Hinzugefügt

- Mitgliederverwaltung mit Neuaufnahme, Rückbestätigung und Austritt, Feld für Feld privat.
- Termine mit Zusagen, Aufstellung und Terminbanner; Titelliste mit Konzertprogrammen.
- Foren, an XMPP-Räume gebrückt, mit Reaktionen und Ungelesen-Markern je Mitglied.
- Versioniertes Wiki, Dateiarchiv mit Ordnerrechten und Versionsverlauf, öffentliche Homepage.
- CardDAV-Adressbuch und CalDAV-Kalender für das Telefon (beide vorerst abgeschaltet).
- Öffentliche Auftritts-Mailingliste mit Double-Opt-in.
- Hell/Dunkel-Umschaltung und Schriftgrößenregler in der Seitenleiste.

### Geändert

- Erste Auslieferung als Podman-Abbild: der Code steckt im Abbild, veränderlich bleibt allein
  `/data`; ein `git pull` auf dem Server gibt es nicht mehr. Die Version kommt aus dem Git-Tag,
  eine einzige Variable (`DATABASE_URL`) konfiguriert die Datenbank.
- `post-receive`-Hook auf dem Server: ein Versions-Tag baut das Abbild, ein Push auf `master`
  ändert am Betrieb nichts.
- Fremde CDNs entfernt, Kartenkacheln nur noch über den eigenen Proxy.
- Listenseiten deutlich beschleunigt: Abfragen je Zeile beseitigt, Zwischenspeicher über die
  Tabellenausgabe, Sitzungsfrist nur noch alle fünf Minuten verlängert.
