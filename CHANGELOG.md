# Änderungen

Ein Abschnitt je Auslieferung. Was noch kein Tag hat, sammelt sich unter
„Unveröffentlicht"; zur Freigabe wird diese Überschrift auf die Version umbenannt, committet und
erst dann getaggt. Das Bare-Repo nimmt ein Versions-Tag ohne gefüllten Abschnitt nicht an —
siehe `update.sh` und `README.md`.

Vorabversionen (`v1.0.0-rc3`) brauchen keinen eigenen Abschnitt: für sie genügt „Unveröffentlicht"
oder der Abschnitt ihrer Endfassung. Verlangt wird er für Endfassungen. Einen eigenen bekommen
dürfen sie trotzdem — er bleibt dann unter der Endfassung stehen.

## Unveröffentlicht

- Mitgliedskarte: die Seite ist kein umrandeter Kasten mehr, sondern folgt dem Muster der übrigen
  Detailseiten — Seitenkopf mit Porträt und Namen, die Abschnitte als Karten in zwei Spalten. Die
  Karte war länger als der Rollbereich: ihre Ober- und Unterkante waren nie gleichzeitig im Bild,
  und ihr Abstand von 20 px lag *im* Rollbereich, verschwand also beim ersten Scrollen — beides
  zusammen las sich als kaputt. Zweispaltig ist die Seite rund ein Viertel kürzer (gemessen 1256
  auf 909 px); die Landkarte bekommt dabei die 250 px Mindesthöhe ihrer eigenen Karte statt der
  übergebenen 400. Die vier Kopfzeilen „Vorname: / Nachname: / Stimme: / Gruppen:" sind entfallen:
  der Name stand dort doppelt, er ist jetzt die Überschrift des Kopfes, die Stimme steht als Wort
  neben den Gruppen-Marken im Untertitel. Die Liedlisten „Dirigent bei" und „Solist bei" laufen
  über die volle Breite — 92 Lieder brauchen in einer halben Spalte die doppelte Höhe und ziehen
  im Raster die Nachbarkarte auf 825 px mit vier Zeilen Inhalt.
- Die Stimme bleibt der Akzent der Seite, nur ohne Kasten: als 4 px breite Kante am linken
  Seitenrand (im dunklen Thema auf 55 % gedämpft — dieselbe Regel wie der Zeilenbalken der
  Mitgliederliste, und sie läuft hier von Oberkante bis Unterkante) und als 3-px-Ring um das
  Porträt. Auf beiden steht kein Text, sie dürfen deshalb den Vollton tragen. Eine Volltonfläche
  mit Text bleibt verboten: weiß auf Sopran 3,2:1, auf Alt 4,2:1; dunkle Schrift auf Tenor 4,4:1,
  auf Bass 2,8:1. Ohne Stimme („N") bleibt die Kante unsichtbar statt grau.
- Das `(S)` neben dem Namen ist eine Pille in derselben Stimmenfarbe geworden. Sie sitzt jetzt
  **neben** dem Titel statt darin, wo sie bisher stand: der Titel kürzt lange Namen mit einer
  Ellipsis ab und fraß dabei genau das `(S)`. Die Pille trägt den Ton als Fläche und den
  Buchstaben in der Kartenfarbe — eine kartenfarbene Pille wäre in der Topbar unsichtbar, weil
  diese in beiden Themen dieselbe Farbe hat wie die Karte; das Kontrastverhältnis ist
  richtungsunabhängig, es gilt getauscht unverändert (hell 4,7 bis 9,8:1, dunkel 7,4 bis 10,2:1).
  Mitglieder ohne Stimme bekommen keine Pille — kein Ton, kein Marker, genau wie die Liste solche
  Zeilen ohne Stimmenfarbe lässt —, Chorleiter und Musiker eine neutrale.
- Korrektur bei den Rollen: der senkrecht beschriftete Gruppenstreifen, den die Liste beim
  Sortieren nach Stimme für Chorleiter und Musiker aufzieht, beschriftete sich in `--t4` und
  erreichte auf seiner Tintfläche nur 2,2:1. Dieselbe Variable speist jetzt auch die neutrale
  Topbar-Pille; beide stehen in `--t3` (4,8:1 hell, 6,8:1 dunkel gegen Weiß, rund 4,2:1 auf der
  Tintfläche). Der Balken und die Kartenkante bleiben bei `--t4`: ein Strich darf leise sein, ein
  Buchstabe nicht.
- Startseite: unter „Konzerte" standen alle Termine mit „Repertoire" — jetzt stehen dort die mit
  einem **Ankündigungstext** (`Termin.extern`), und der Text wird mit ausgegeben (Adresse, Einlass,
  Eintritt, Links). Die Spalte stammt aus dem alten PHP-Portal und wurde dort für genau das
  gefüllt (74 Zeilen, in der laufenden Saison keine einzige); sie war im neuen Portal nie gelesen
  worden. **Zum Ausrollen:** ein Auftritt ohne Eintrag fehlt auf der Startseite. Für einen
  Auftritt ohne Text genügt ein Leerzeichen — er wird dann gelistet, aber ohne Ankündigungsblock;
  die drei Auftritte der laufenden Saison (1320, 1321, 1324) bekommen das beim Neuaufbau aus dem
  Altsystem automatisch, in einer gewachsenen Datenbank wird es einmalig über die Kachel
  nachgetragen.
- Terminseite: `Termin.extern` bekommt eine eigene Karte „Extern". Sie fehlt, solange das Feld
  leer ist — die Bedingung ist das Ergebnis der Auszeichnung, damit ein reiner Leerwert keinen
  leeren Kasten erzeugt, während die Auswahl der Startseite denselben Termin listet.
- Termin bearbeiten: neue Kachel „Extern" mit dem Ankündigungstext (mehrzeilig, HTML erlaubt). Der
  Hilfetext am Feld erklärt, wann die Karte erscheint und dass der Text über die Startseite
  entscheidet; Änderungen stehen im Änderungsprotokoll. Aus dem Kalender-Offcanvas bleibt das Feld
  draußen — ein fünfzeiliges Textfeld wäre dort unbedienbar.
- Die Altdaten bringen eigenes HTML mit; beim Anzeigen werden Zeilenumbrüche zu `<br>`,
  `style`-Angaben entfernt (drei Zeilen, darunter ein hellblauer Link mit 1,5:1 Kontrast auf dem
  Cremeband) und Überschriften zu `<strong>` (55 der 74 Zeilen beginnen mit `<h1>`). Der
  gespeicherte Wert bleibt unberührt; das ist keine Sanitisierung, sondern eine Anzeigeregel für
  Inhalte, die nur mit der Berechtigung „Termine ändern" geschrieben werden können.
- Die Erinnerungsmails der Auftritts-Mailingliste hängen weiterhin an „Repertoire" — die beiden
  Mengen sind jetzt unabhängig. Wer beides zusammen haben will, setzt beide Zeichen.
- Der Neuaufbau aus dem Altsystem startet jetzt mit den Gründerinnen und Gründern als einzigen
  aktiven Konten: sie tragen den 17.06.2026 als Eintrittsdatum, jeder andere Zugang kommt ohne
  Eintrittsdatum und deaktiviert an. Das bisher übernommene `aktiv_seit` taugt nicht als
  Eintritt — es war uneinheitlich, teils leer und meinte die Anmeldung im alten Portal, nicht den
  Vereinseintritt. Die übrigen Mitglieder werden einzeln über die Mitgliederverwaltung
  freigeschaltet; dabei setzt das Portal das Eintrittsdatum auf diesen Tag und verschickt die
  Willkommensmail (`date_joined = NULL` ist sein Merker für „nie aktiviert"). Bis dahin bleibt die
  Zeile „Mitglied seit" auf ihrer Karte leer. Die Reihenfolge im Import ist dabei nicht
  beliebig: die Deaktivierung läuft nach dem Avatar-Import, der `is_active` prüft und den
  übrigen sonst das Ersatzbild statt ihres Fotos gegeben hätte.
- Datumsangaben nennen jetzt den kurzen Wochentag und den Monat als Zahl („Mi, 24.09.2026 19:30"
  statt „24. September 19:30"). Für eine Probe ist der Wochentag die Information, nach der man
  sucht; den Monatsnamen trägt der Termin-Banner seit jeher als Zahl (`D, d.m.`), die übrigen
  Seiten ziehen nach. Betroffen sind alle Ausgaben über `replacements.format_datetime` — neben der
  Terminliste also auch Datei-, Artikel- und Protokolllisten sowie die Termin-Detailseite; die
  Verzweigungen für „heute" (nur Uhrzeit) und „gestern" bleiben wie sie waren.
- Terminliste: die Spalte „Du" ist entfallen. Sie trug die eigene Zu-/Absage als Wort, und im
  Zustand „offen" bereits einen blinkenden Rahmen — das Signal sitzt jetzt dort, wo man es sucht:
  das eigene Kästchen der Aufstellung pulsiert, und mit ihm der Terminname selbst (nicht die
  ganze Zeile — gemeint ist der Termin, nicht seine Datums- und Aufstellungszellen). Der Rahmen
  liegt außerhalb des Textes (`outline`), damit der Name in der Fluchtlinie der übrigen Termine
  bleibt. Beide
  Rahmen laufen in **einer** Animation und damit im Gleichtakt; die Ruhephase bleibt sichtbar,
  das Kästchen also weiter als „meins" erkennbar. Beides gilt nur für kommende Termine ohne
  eigene Antwort: zu einem vergangenen Termin ist eine offene Zusage gegenstandslos, und Termine
  ohne Anwesenheitsabfrage haben gar keine Aufstellung. Wer Bewegung reduziert haben will,
  bekommt die Rahmen stehend statt blinkend.

## v1.0.0-rc3 — 2026-09-22

- Passwort zurücksetzen: ohne SMTP-Server (`EMAIL_HOST`) nahm die Seite eine Anfrage an, die
  nichts bewirkte. `send_config_mail` schreibt die Nachricht dann nur ins Log, also erreichte
  kein Link die Mitglieder — die neutrale Erfolgsmeldung („Anfrage erhalten") behauptete das
  Gegenteil, und wer sein Passwort vergessen hatte, wartete auf eine Mail, die nie kam. Die Seite
  sperrt den Knopf jetzt sichtbar: ausgegraut, mit dem Grund als Tooltip am umschließenden `<span>`
  (Chrome zeigt auf deaktivierten Bedienelementen keinen) und als Satz darunter für Geräte ohne
  Hover. Ein POST wird gar nicht mehr angenommen, und statt der Erfolgsmeldung steht dort, dass
  der E-Mail-Versand nicht eingerichtet ist und man sich an den Vorstand wendet.
- Startseite: die Einstiegsseite soff am Seitenende in Schwarz ab — der Hero lag unter zwei
  kalten Schleiern (zusammen bis 0,9 Deckung), die Kontaktsektion auf `#17151a`, der Fuß auf
  dem noch dunkleren, hartkodierten `#100e12`. Das Foto trug den Auftritt damit nur noch in
  der Mitte; wer die Seite aufrief, sah zuerst eine Trauerfläche. Der Hero liegt jetzt ganz
  ohne Schleier: über dem Bild steht nur noch, was seine eigene Fläche mitbringt. Die
  Navigation trägt ein Milchglas (0,75 Weiß, 10 px Weichzeichner) — sie kreuzt links die dunkle
  Decke und rechts das helle Gewölbe mit Giebelbrett und Orgelpfeifen, und keine Schriftfarbe
  trägt über beiden: Weiß stand auf den hellen Partien bei 4,41:1 (das war der Grund, den
  Kopfschleier von 0,55/0,46 auf 0,66/0,56 zu heben), dunkle Tinte fällt über der Decke auf
  1,6:1. Hinter dem Glas ist der Grund hell und ruhig, dunkle Schrift trägt dort in beiden
  Fällen, und die Fläche wandert mit der Navigation mit, statt ein Band über die ganze
  Bildbreite zu legen; im `is-solid`-Zustand schaltet sie sich ab. Die Textzone unter der
  Wortmarke ist entfallen, ebenso der Anrisstext (der erste Satz aus `HOMEPAGE_UEBER_UNS`),
  der sie nötig machte — der Hero trägt nur noch die Wortmarke und die beiden Buttons. Die
  Wortmarke ist ein Logotyp und nach WCAG 1.4.3 von der Kontrastanforderung ausgenommen; ihr
  Schlagschatten ist Schmuck und kein Schutz. Der Ghost-Button ist die einzige verbliebene
  Fläche auf dem Bild: über dem hellen Holzboden wäre ein weißer Rand ohne Füllung nicht zu
  sehen, deshalb trägt er ein eigenes dunkles Glas (42 %), während der Primary seine
  Markenfüllung behält

  Die Messung, die den früheren Schleierstufen zugrunde lag, ist mit ihnen entfallen — es gibt
  keine Deckung mehr zu lösen. Ihre Befunde bleiben für den Fall notiert, dass wieder Text auf
  das Bild kommt: am gerenderten Bild gemessen hielten die Navigationslinks 5,8:1 (und 4,41:1
  mit der ersten Stufe), der Anrisstext 6,9:1, der Ghost-Button 9,7:1; hinter dem Textblock
  liegen weiße Roben, der helle Holzboden und die helle Wand, die 4,5:1 verlangen. Die
  Alternative „Text ganz vom Foto nehmen" ist damit zweimal gegangen worden: der Anrisstext ist
  entfallen, und der Kopf hat seinen Schutz vom Bild in eine eigene Fläche verlegt. Eine
  Zellkarte des Fotos zeigt, warum das der einzige Weg war — es gibt dort keine Stelle, an der
  Text ohne Schutz lesbar wäre: die einzige dunkle Zone ist 120 px breit, und im Textband sind
  nur 12–41 % der Pixel hell, dunkle Schrift bräuchte also 55 % Aufhellung

  Das Kontaktband ist markenrosé mit weißer Schrift (`--band`: `--brand` um 10 % abgedunkelt,
  denn auf reinem `--brand` trägt Weiß nur 4,89:1 und dann dürfte kein Zeichen mehr transparent
  sein), der Fuß ist hell auf warmem Creme mit der schwarzen Wortmarke. Dazu eine zweite Farbe:
  Gold, wie die Schals im Foto, an zwei Stellen (Oberkante der Karte „Wir suchen Sängerinnen
  und Sänger", Augenbraue und Link im Kontaktband — die dritte, die Zierlinie unter dem
  Hero-Label, ist mit dem Label entfallen). Nebenbefund aus derselben Ecke: `--brand-dark`,
  `--brand-soft` und zwei Rosé-Tints standen hier als Literale, und die Startseite lud
  `_brand_boot.html` gar nicht — eine konfigurierte `BRAND_FARBE` blieb auf der öffentlichen
  Seite wirkungslos und wirkt jetzt. Die Copyright-Zeile stand mit 3,4:1 unter WCAG AA und
  steht jetzt bei 5,2:1
- Repertoire: die Suche der Titelliste war an die Spalte `titel` gebunden und fand weder
  Komponist noch Bearbeiter, obwohl beide am Modell stehen und als Spalten angeboten werden.
  Sie greift jetzt über alle drei (ODER-verknüpft, `RepertoireFilter.filter_suche`). Parameter
  (`titel`), Beschriftung („Suche") und Formular bleiben unverändert — bestehende Links und der
  gemerkte Tabellenzustand greifen weiter. Die Wiedergabelisten des Mini-Players folgen
  derselben Suche, weil sie denselben Filter benutzen
- Datenmodell: `Zusage` konnte zwei Antworten desselben Mitglieds für denselben Termin
  nebeneinander halten. Sichtbar wurde das an einem aufgeblähten Zähler und an zwei
  `update_or_create`-Aufrufen, die bei einem Duplikat mit `MultipleObjectsReturned`
  abgebrochen wären; fünf weitere Stellen sicherten sich mit `order_by("-id").first()` ab.
  Ein `UniqueConstraint(person, termin)` schließt die Lücke. Am Bestand ändert er nichts —
  geprüft vor dem Setzen: 2873 Zusagen, keine einzige Doppelung. Der Import aus dem
  Altsystem legt Zusagen künftig unverändert an; die Datenquelle ist ebenfalls dublettenfrei.
  `views/termine.py` kann seine Behelfe behalten, sie schaden nun aber nicht mehr
- Datenmodell: `Abstimmung` schrieb beim Abstimmen erst alle Stimmen weg und legte dann die
  neuen an, ohne Transaktion. Zwei gleichzeitige Klicks konnten dieselbe Stimme doppelt
  eintragen, was die Auswertung mitzählte. `UniqueConstraint(person, abstimmung, option)`
  verbietet genau das — bewusst nicht `(person, abstimmung)`, denn eine Abstimmung darf
  mehrere Kreuze zulassen (`max_stimmen`). Dazu ein Index für das Abstimmungsfilter
- Foren: `Mitteilung.formatiert()` schickt den Nachrichtentext durch die Wiki-Ersetzung
  und wäre an einer leeren Nachricht gescheitert — die Spalte erlaubt `null` (Altdaten,
  Nachrichten aus dem XMPP-Bot). Sie behandelt fehlenden Text jetzt als leeren Text. Die
  Spalte auf `NOT NULL` zu ziehen wäre der sauberere Schnitt, ließe aber `makemigrations`
  interaktiv nachfragen; genau dieser Aufruf läuft im `Dockerfile` und in `start.sh` ohne
  Eingabe und bräche den Bau ab — siehe „Migrations: never create `0004+`" in `CLAUDE.md`
- Datenmodell: `Konzert.lied` löschte bei einem entfernten Lied den ganzen Programmpunkt mit
  (`CASCADE`, obwohl das Feld `null` erlaubt). Jetzt `SET_NULL` wie bei allen übrigen
  nullbaren Verweisen — ein gelöschtes Lied verliert seinen Platz im Ablauf, nicht den
  Programmpunkt. `on_delete` erzeugt kein DDL, die Änderung wirkt sofort
- `Zusage.option` ist ein `choices`-Feld geworden, und der Wertebereich liegt jetzt in
  `intern/zusage.py`. Dieselben vier Antworten samt Beschriftung standen vorher an fünf
  Stellen, und zwei Kopien waren schon auseinandergelaufen (Änderungsprotokoll,
  Aufstellung, Tabellenspalte, Statusfilter). Beschriftungen sind wortgleich geblieben:
  `str(Zusage)` liegt als Schnappschuss im Änderungsprotokoll, eine Änderung schriebe die
  Anzeige vergangener Einträge um
- Änderungsprotokoll: `FIELD_LABELS` nannte den Schlüssel `gruppe` zweimal — einmal als
  „Signatur" der Benachrichtigungsseite, einmal als „Gruppe" der Berechtigungsseite. Im
  Dict-Literal verdrängt der spätere Eintrag den früheren lautlos, die E-Mail-Seite zeigte
  also „Gruppe". Ein modellgenauer Eintrag wird jetzt zuerst befragt
- Das Änderungsprotokoll, die Feldbeschriftungen und die Dateikarten werden gegen die
  Modelle geprüft (`RegisterKonsistenzTest`). Ihre Feldnamen sind Zeichenketten: wurde ein
  Feld umbenannt und die Karte nicht, verstummte das Protokoll für dieses Feld, ohne dass
  etwas auffiel. Der Test liest die Karten außerdem aus der Quelle und findet doppelte
  Schlüssel, die der Import verschweigt
- Indizes: `db_index=True` neben `unique=True` (`Mitteilung.xmpp_stanza_id`) und auf einem
  Fremdschlüssel (`Reaktion.mitteilung`) war wirkungslos — es gab dort nie zwei Indizes.
  `ChangeLog` hatte dagegen zwei Indizes auf `user` und keinen auf `timestamp`, obwohl die
  Liste danach sortiert; das ist getauscht. `Termin.datum` ist jetzt indiziert — danach
  filtern und sortieren Terminliste, Kalender, CalDAV und Erinnerungsversand
- `Konzert`- und `Lied`-Hilfsmethoden sowie `intern/fuzzy.py` entfernt. Der Titelvergleich
  hatte keinen Aufrufer mehr, und `fuzzy.py` ließ sich nicht einmal importieren: seine
  Abhängigkeit `rapidfuzz` stand nie in `requirements.txt`
- Aufräumen ohne Wirkung nach außen: die Avatar-Helfer und die beiden Listen der
  verbergbaren Mitgliedsfelder liegen jetzt in `intern/avatare.py` und
  `intern/mitglied_felder.py` statt in `models.py`; `ChangeLog.timestamp` benutzt
  `timezone.now` wie der Rest des Projekts statt `datetime.now`
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
