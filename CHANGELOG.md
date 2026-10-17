# Änderungen

Alle nennenswerten Änderungen an diesem Projekt stehen in dieser Datei, die jüngste oben.

Das Format folgt [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), die Auslieferungen
folgen [semantischer Versionierung](https://semver.org/lang/de/). Ein Eintrag sagt in höchstens
drei Sätzen, *was* sich ändert — wie es dazu kam, steht im Commit. Wie eine Auslieferung
freigegeben wird (Sammelabschnitt umbenennen, committen, taggen), steht in `README.md`.

## Unveröffentlicht

### Hinzugefügt

- Die Seitenleiste hat unter „Einstellungen“ einen Eintrag „Hilfe“, der zur Übersicht der
  Hilfe-Artikel führt.

### Geändert

- Abbilder entstehen bei jedem Versions-Tag auf GitHub und liegen als `ghcr.io/hgruber/cantorhub`
  für amd64 und arm64 (Raspberry Pi) in der Registry; vor der Veröffentlichung laufen die Tests im
  Abbild. Der Server zieht neue Fassungen mit `podman pull`, der Bau per `post-receive` auf dem
  Server entfällt.
- Ein neues Bot-Passwort setzt das Portal beim Speichern der Konfiguration auch in ejabberd; beim
  Eintragen erklärt ein Hinweis das. Der Chat-Bot meldet sich nach geänderten Zugangsdaten binnen
  etwa anderthalb Minuten neu an, wartet nach Anmeldefehlern, statt aufzugeben, und startet auch,
  wenn XMPP erst nach dem Containerstart eingerichtet wird.
- Einen geänderten SMTP-Zugang prüfen Konfigurationsseite und Ersteinrichtung vor dem Speichern
  durch eine Anmeldung am Server; scheitert sie, bleibt alles beim Alten und die Seite nennt den
  Grund. STARTTLS und SSL zugleich lehnt die Konfigurationsseite ab, weil damit jeder Versand
  scheiterte.

### Behoben

- Dialoge wie der Ort auf der Karte sind im dunklen Design lesbar; sie blieben weiß, während die
  Schrift hell wurde.

### Sicherheit

- Django auf 6.0.8 und Pillow auf 12.3.0 angehoben; beide Versionen schließen bekannte Lücken,
  unter anderem beim Datei-Upload und beim Öffnen präparierter Bilddateien.

## v1.0.9 — 2026-10-16

### Hinzugefügt

- Neuer Hilfe-Artikel „Hilfe:Betrieb und Kosten“ für den Vorstand: was ein eigener Server
  braucht und drei durchgerechnete Wege (zu Hause, kleiner Mietserver, Mietserver mit Reserve)
  für bis zu 100 Personen. Bestehende Installationen holen ihn mit `manage.py hilfe_anlegen` nach.
- Hilfe: Jede Seite „Hilfe:…“ verlinkt oben und unten die vorherige und die folgende Seite sowie
  die Übersicht.
- `manage.py hilfe_anlegen --force` bringt vorhandene Hilfe-Artikel und -Bilder auf den
  mitgelieferten Stand, als neue Version bzw. Fassung; die bisherigen bleiben in der Geschichte.

### Geändert

- Artikel: Die Fußzeile zeigt den Vereinsnamen ohne angehängtes Ausrufezeichen.
- Hilfe: „Erste Schritte“ beginnt nach der Anmeldung; wie man ein neues Passwort anfordert,
  steht jetzt unter „Mein Profil“, ebenso genauer, wann das Kästchen gegen die Übertragung ins
  Telefon-Adressbuch erscheint.
- Hilfe: Bei Rückfragen verweisen die Artikel aufs Forum statt auf den Vorstand. Für Ordnerrechte
  und das Freischalten von Diensten nennen sie wie die Seite „Passwort zurücksetzen“ den Webmaster
  bzw. einen Administrator.
- Ersteinrichtung: Die Startseite „Aktuell“ darf nur noch der Webmaster bearbeiten; die Gruppen
  „Kassenprüfer“, „Gründer“, „kein Bild“ und „DSGVO“ werden nicht mehr vorab angelegt.
- Startseite: Fehlt `/data/startseite` beim Containerstart, legt `start.sh` dort eine Kopie der
  mitgelieferten Demo-Seite an, deren Dateien man direkt mit eigenen überschreibt. Ein
  vorhandener Ordner bleibt unberührt.
- Konfiguration: Pflichtfelder tragen hinter ihrem Schlüssel einen Stern.

## v1.0.8 — 2026-10-15

### Hinzugefügt

- Hilfe: Eine neue Installation bringt Hilfe-Artikel für Einsteiger mit — Übersicht „Hilfe“,
  erste Schritte, Profil, Termine, Forum, Repertoire, Mitglieder, Dateien, Artikel schreiben und
  bebilderte Anleitungen für Termine, Kalender-Abo, Kontakte und Chat (Conversations, Monal) auf
  dem Telefon. Bestehende Installationen holen sie mit `manage.py hilfe_anlegen` nach, ohne
  Vorhandenes zu überschreiben.
- Artikel: Platzhalter wie `{VEREINS_URL}`, `{CALDAV_URL}`, `{BENUTZERNAME}` oder
  `{XMPP_ADRESSE}` zeigen beim Lesen den passenden Wert der Installation bzw. des Lesers; die
  Liste steht in „Hilfe:Wiki“. Links dürfen auch auf `webcal://` zeigen.
- Ersteinrichtung: Neutrale Ersatzbilder für Mitglieder ohne Foto und den Chat-Bot sowie
  sichtbare Spalten für Mitgliederliste und Repertoire.

### Geändert

- Startseite: Die mitgelieferte Startseite ist eine neutrale Vorlage ohne Foto, mit dem CantorHub-Logo und
  Texten aus der Konfiguration und dunkler Darstellung nach Systemeinstellung. Administratoren
  sehen darauf einen Hinweis, wie sie Texte einstellen oder eine eigene Seite hinterlegen.
- Portal: Das mitgelieferte Logo ist das blaue CantorHub-Siegel; ein eigenes Logo unter
  `/data/startseite/statisch/logo.svg` ersetzt es auf Login, Sidebar, Fehlerseiten und als
  Favicon.
- Konfiguration: Die vorgegebene Akzentfarbe (`BRAND_FARBE`) für neue Installationen ist ein
  Blau (`#2b6cb0`); bestehende Installationen behalten ihren Wert.
- Termine und Mitgliederliste: Die Hinweiskästen „Termine aufs Telefon“, „Kalender abonnieren“
  und „Kontakte aufs Telefon“ sind entfallen; ihre Anleitungen stehen jetzt in der Hilfe.
- Portal: Mail-Logo, PDF-Briefkopf, App-Symbole und das Web-App-Manifest kommen aus der
  Konfiguration und aus `/data/startseite/statisch/brand/`; mitgeliefert wird das CantorHub-Siegel.
- Konfiguration: Neue Installationen starten mit neutralen Vorgaben (Name „CantorHub“,
  `example.org`-Absender, Kartenmitte Deutschland); die Angaben zu Hoster und
  Datenschutzbehörde sind leer und werden in der Konfiguration angemahnt. Die eigene Aufnahme
  eines Titels heißt nach `FILE_PREFIX` („<Präfix> Aufnahme“).

### Entfernt

- Startseite: Chorfotos, Wortmarken und `main.css` sind nicht mehr Teil des Images; die eigene
  Seite einer Installation bringt sie unter `/data/startseite/` mit.
- Portal: Die Chor-PNGs (Mail-Logo, Briefkopf, App-Symbole) und das statische `manifest.json`
  sind nicht mehr Teil des Images.

### Behoben

- Artikel: Fett und kursiv (`'''…'''`, `''…''`) werden wieder dargestellt, auch mehrfach in
  einer Zeile; nummerierte Listen mit Hervorhebungen zerfallen nicht mehr.
- Artikel: Kästen (`@`) und graue Hinweise (`%`) stehen an ihrer Stelle im Text und zeigen
  Links und Hervorhebungen.
- Termin: Anwesenheiten lassen sich auf Telefon und Tablet verschieben — durch Antippen oder
  nach kurzem Halten durch Ziehen.
- Mitgliedsprofil: Leere Angaben erscheinen nicht mehr als „None“, ein fehlendes Profilbild
  zeigt ein Symbol statt eines kaputten Bildes.
- Ersteinrichtung: Auf SQLite bricht sie nicht mehr mit „database is locked“ ab.

## v1.0.7 — 2026-10-14

### Hinzugefügt

- Forenliste: Die Spalte „Bild“ zeigt das Forenbild als rundes Icon vor dem Thema. Sie ist
  standardmäßig ausgeblendet und lässt sich über die Spaltenwahl einschalten.
- Forum bearbeiten: Der Seitenkopf zeigt das Forenbild statt des allgemeinen Symbols.
- Forum: Die Kopfzeile zeigt vor dem Thema das Forenbild statt der Sprechblase.
- Startseite: Eine eigene Startseite unter `/data/startseite/` ersetzt die mitgelieferte Datei
  für Datei; Bilder und CSS daraus erscheinen unter `/startseite/`. Änderungen wirken ohne
  Neustart.

### Geändert

- Container: Das Portal ist nach dem Start erreichbar, ohne auf den XMPP-Abgleich zu warten; der
  läuft samt Bot im Hintergrund.
- Container: XMPP-Bot und Versand der Auftrittserinnerungen starten nach einem Absturz nach
  30 Sekunden neu.

### Behoben

- Termin- und Ortsseite: Die Karte zeigt den Ort wieder mit Marker, jetzt mit dem Orts-Pin der
  Übersichtskarte; vorher fehlte das Markerbild im Container.
- Forum: Beiträge, die geschrieben werden, während der XMPP-Bot neu startet, erreichen den
  XMPP-Raum nachträglich, statt verloren zu gehen.
- Forum: Reaktionen, die in einem XMPP-Client im Forenraum gesetzt werden, kommen im Forum an,
  auch auf Beiträge, die aus dem Portal weitergeleitet wurden.

## v1.0.6 — 2026-10-13

### Hinzugefügt

- Ersteinrichtung: Startet das Abbild auf einer leeren Datenbank, führt jeder Seitenaufruf auf
  „/einrichtung/“; wer sie zuerst abschließt, wird Administrator. Dort entstehen das erste Konto,
  die aus dem Aufruf vorbelegte Portaladresse, der Absender und auf Wunsch der SMTP-Zugang, dazu
  Gruppen, Standardordner und das Vorstand-Recht.
- Container: `podman run --rm -p 8000:8000 cantorhub` startet ohne Volume und ohne
  Datenbankangabe eine Demo, die beim Beenden verschwindet. nginx reicht dafür den Host samt Port an Django
  weiter.
- Ersteinrichtung: Sie legt die Startseite „Aktuell“ an und auf Wunsch Beispieldaten — einige
  Volkslieder, wöchentliche Proben, ein Konzert mit Ablauf und das Forum „Allgemeines“.
- Konfiguration: Erinnerungsmail der Auftritts-Liste und Startseitentexte haben Mustertexte, die
  eine neue Installation vorbelegen.

### Geändert

- Seitenleiste: Die Version steht für alle unten in der Leiste. Als Link auf die Änderungsseite
  erscheint sie mit dem Recht „Mitglieder › Berechtigungen“ oder „Dateien › Berechtigungen“; beide
  geben jetzt auch die Seite selbst frei.

### Entfernt

- Der einmalige Import aus dem Altportal ist ausgebaut; seine Migration bleibt als leerer
  Platzhalter in der Kette.

### Behoben

- CardDAV/CalDAV: DAVx⁵ ab Version 4.5 lässt sich wieder einrichten; es scheiterte an den
  komprimierten Antworten des Portals („Gzip file name not supported“).

## v1.0.5 — 2026-10-13

### Hinzugefügt

- Termine: Ein Termin kann Dateien tragen; sie stehen auf der Terminseite in der Karte „Dateien“.
  Wer Termine bearbeiten darf, legt sie dort direkt ab und kann sie wieder vom Termin lösen.
  Abgelegt wird in „Backstage/Termin-Anhänge“, mit dem Termindatum vorn im Dateinamen.

### Geändert

- Dateien: Die Standardordner („Backstage“ mit seinen Unterordnern, „Verein“, „Vorstand“,
  „Mitgliedsanträge“) lassen sich im Portal nicht mehr umbenennen, verschieben oder löschen.
- Dateien: Webmaster können Dateien und Ordner nach „Backstage“ verschieben, kopieren und
  verknüpfen.
- Hochladen: Eine Ablagefläche gibt es nur noch, wo die Datei einen Zielordner hat; auf oberster
  Ebene laden nur Webmaster hoch. Das Profil hat nur noch die Fläche des Profilbilds.
- Hochladen: Profilbild, Forenbild und Titel-Dateien liegen sofort in ihrem Ordner; ersetzt wird
  die bisherige Datei erst mit „Speichern“.
- Hochladen: Die Ablagefläche eines Felds lässt sich antippen und nimmt auch ein zweites Bild an;
  Profil- und Forenbild öffnen auf dem Handy Galerie oder Kamera. Das Hochladen-Symbol erscheint
  überall dort, wo eine Ablagefläche ist.
- Betrieb: Änderungen am Datenbankschema kommen als Migrationen mit dem Abbild und werden beim
  Start des Containers angewendet. Der Migrationspfad `MIGRATE=1` ist entfernt.
- Datenschutzerklärung: Unter „Verantwortliche“ stehen alle Mitglieder der Gruppe „Vorstand“,
  auch solche ohne Portalzugang.
- Repertoire: Das Feld „Konzert“ im Filter zeigt ohne Auswahl „Alle Titel“ statt „Alle Termine“.

### Behoben

- CalDAV: der Kalender übernimmt auf den Geräten die Portalfarbe `BRAND_FARBE`. Die Farbe stand
  bisher in einem XML-Namensraum, den kein Client liest.
- Profil: Ein Profilbild landet immer in „Backstage/Profilbilder“, schon beim Hochladen. Fehlte
  der Ordner, lag es bisher im Wurzelordner; jetzt legt das Portal ihn neu an.
- Mail: Antwortet der Mailserver nicht, bricht der Versand nach 10 Sekunden mit einem Fehler ab.
  Bisher hing die Seite, bis sie mit einem Serverfehler abbrach.

## v1.0.4 — 2026-10-11

### Geändert

- Repertoire: Eine hochgeladene Datei wird abgelehnt, wenn ihr Dateityp nicht ins Repertoire
  gehört oder sich keinem Titel zuordnen lässt — auf der Liste muss der Dateiname einem Titel
  entsprechen. Bisher landete sie ohne Zuordnung in „Backstage/Repertoire“.
- Dateien: „Backstage“ und seine Unterordner stehen in keiner Zielauswahl mehr, weder im
  Ordnerbrowser noch im Datei-Menü eines Artikels; Verschieben, Referenz und Kopieren dorthin
  lehnt der Server ab, auch per Drag & Drop.
- Migration vom Altportal: Den Artikel „Aktuell“ dürfen nur Webmaster, Vorstand und
  KonzertOrga bearbeiten; lesen dürfen ihn weiterhin alle.
- Artikel: Eingebettete Medien haben nur noch eine Steuerung. Ein Video spielt in seiner
  Leiste im Text, ohne dass unten der Player aufgeht; eine Audiodatei erscheint wie jede andere
  Datei mit Noten-Symbol, Dateiname und Download-Knopf, ein Klick aufs Symbol öffnet den Player
  unten.

## v1.0.3 — 2026-10-11

### Geändert

- Migration vom Altportal: Sie legt zusätzlich den Ordner „Organisation Chor/Audio & Video
  Mitschnitte“ an, lässt die Foren „Sopran“ und „Tenor“ aktiv und ersetzt das archivierte
  „Chorgespräch“ (jetzt „Chorgespräch alt“) durch ein neues. Die Foren bekommen dabei ihre
  Kategorien A–D.
- Ordnerrechte: Eine Einschränkung auf Lesen, Schreiben oder Löschen gilt auch für alle
  Unterordner ohne eigene Einschränkung und wirkt dort sofort, wenn sie geändert wird. Eine
  eigene Einschränkung im Unterordner ersetzt die geerbte; im Rechte-Editor heißt die Option
  ohne Einschränkung jetzt „Wie im übergeordneten Ordner“.

### Behoben

- Ordnerrechte: Wer nur das Schreiben oder nur das Löschen auf Gruppen einschränkte, sperrte den
  Ordner für alle zum Lesen. Dateien auf der obersten Ebene konnte jeder löschen, und in einen
  Ordner, den man nicht sehen darf, ließ sich trotzdem hochladen.

## v1.0.2 — 2026-10-11

### Hinzugefügt

- Foren: Ein Forum kann beim Anlegen oder Bearbeiten eine Kategorie bekommen. Die Forenliste
  zeigt sie als erste, sortierbare Spalte, sobald eines der angezeigten Foren eine hat.
  Sind alle Kategorien höchstens drei Zeichen lang, heißt die Spalte „Kat“; aufsteigend
  sortiert stehen Foren ohne Kategorie am Ende.
- Forenliste: Die angezeigten Spalten lassen sich wie in Mitgliederliste und Repertoire je
  Mitglied auswählen.

### Geändert

- Anmeldeseite: Der Vereinsname steht in der Begrüßung in einer eigenen Zeile und wird nicht
  mehr umbrochen.
- Auftritts-Mailingliste: Statt von „Erinnerungen“ ist auf Startseite, Anmeldeseiten, in den
  E-Mails, im Betreff und in der Datenschutzerklärung von „Informationen“ die Rede. Unverändert
  gebliebene Konfigurationstexte werden beim nächsten Start angepasst.
- Forenliste: Die Spalte „Zugriff“ heißt jetzt „Letzter Beitrag“.
- Startseite: Der Link zur Auftritts-Mailingliste steht nur noch unter „Konzerte“; die Karte
  „Auftritts-Informationen“ im Kontaktbereich entfällt.
- Passwort zurücksetzen: Die E-Mail spricht vom „Benutzernamen“ statt vom „Benutzer“; ein
  unverändert gebliebener Konfigurationstext wird beim nächsten Start angepasst.
- Datenschutzerklärung: Neben den aktiven Mitgliedern sind jetzt auch der Chorleiter und
  die Bandmitglieder als Personen mit Portalzugang genannt, die Profile einsehen und Adressbuch
  und Kalender abgleichen können.
- Datenbestätigung: Die Satzung wird nicht mehr abgefragt, und Mail und Formular sagen jetzt,
  dass man sich nach der Bestätigung im Mitgliederportal anmelden kann; eine unverändert
  gebliebene Aufforderungsmail wird beim nächsten Start angepasst. Auch Fehlerseiten und Hinweise sprechen vom „Mitgliederportal“
  statt vom „internen Bereich“.
- Terminliste: Auch ein Termin mit der eigenen Antwort „Eventuell“ blinkt jetzt, genau wie
  einer ohne Antwort — der Terminname und das eigene Kästchen der Aufstellung.

## v1.0.1 — 2026-10-11

### Hinzugefügt

- Artikel: Hochladen gibt es in der Ansicht nur mit Schreibrecht. Eine hochgeladene Datei kommt
  als `[[Datei:…]]` an den Anfang des Artikels, in der Ansicht als neue Version, im Editor nur
  ins Textfeld.
- Artikel: Ein Klick auf ein eingebettetes Vorschaubild öffnet ein Menü zum Herunterladen und
  Anzeigen, mit Schreibrecht außerdem zum Sprung in den Ordner, zum Anlegen einer Referenz und
  zum Löschen der Datei samt Verweis.
- Mitgliederliste: Der Filter besteht aus beliebig vielen Bedingungen, jede mit eigenem
  „und"/„oder" und mit „ist in"/„ist nicht in" — damit ist etwa „in Gruppe A und in Gruppe B und
  nicht in Gruppe C" möglich, und eine Verneinung schließt die Person aus, nicht bloß eine ihrer
  Zugehörigkeiten. Die Titelleiste zeigt die Kette als Satz, mit dem Verknüpfungswort zwischen den
  Chips und Klammern, wo das „und" stärker bindet. Ein gemerkter Filter aus der Zeit davor wird
  weiterhin gelesen.
- Mitgliederliste: Jedes Kriterium der Liste ist filterbar — Name, Stimme, E-Mail, XMPP,
  Geburtstag, letzte Anmeldung, Eintritt, Anschrift, Telefon, Fax, Zugang, Gruppen sowie Zusage.
  Textfelder kennen „enthält", „enthält nicht", „beginnt mit", „endet mit" und „ist"; die Zusage
  wird über Termin und Antwort bestimmt. Die Titelleiste zeigt jede Bedingung als Satz („ist in
  Gruppe Vorstand", „hat geantwortet zu Konzert am 06.06.27").
- Mitgliederliste: Was ein Mitglied verbergen kann (E-Mail, Telefon, Anschrift, Geburtstag) und
  der Zugangsschalter sind nur mit „Mitglieder bearbeiten" filterbar. Der Filter greift, bevor die
  Tabelle verborgene Angaben ausblendet — ein Kriterium darauf hätte den Wert über die
  Trefferzahl verraten.
- Gruppen: Ein Klick auf eine Berechtigung öffnet eine Hilfe, die alle Stellen im Portal
  beschreibt, an denen das Recht wirkt, und nennt, wo ein zweites Recht nötig ist. Darunter stehen
  die Personen mit diesem Recht, nach der Gruppe, über die sie es haben, direkt oder als Admin.
- Profil: Die Karte „Meine Rechte“ im eigenen Profil listet die eigenen Rechte. Ein Klick öffnet
  dieselbe Hilfe wie auf der Gruppen-Seite, statt aller Inhaber steht dort, worüber man das Recht hat.

### Geändert

- Seitenleiste: Der Schalter „Benachrichtigungen“ unter Einstellungen entfällt; alle Mitglieder
  bekommen die Benachrichtigungen jetzt immer.
- Anmeldung: Das Feld heißt „Benutzername“ statt „Username“.
- Rundmail an Mitglieder: Unter der Signatur der Gruppe steht jetzt „Gesendet von" mit dem Namen
  der Person, die die E-Mail abgeschickt hat. Das Formular zeigt die Zeile schon vor dem Versand.
- Repertoire: Der Filter ist derselbe Baukasten wie in der Mitgliederliste — beliebig viele
  Bedingungen mit „und"/„oder", etwa „Hymne und A cappella und nicht Aufnahme"; das Konzert bleibt
  ein festes Feld darunter, die Ablauf-Ansicht filtert nicht mehr. Ein gemerkter Filter aus der
  Zeit davor wird weiterhin gelesen.
- Filter: Ja/Nein-Kriterien ohne Wert (etwa Hymne, Aufnahme, Zugang) stehen als feste Schalter
  mit drei Stellungen (ausschließen, egal, einschließen) unter den Bedingungen und gelten für alle.
  Tempo, Tonart und Zusage tragen den Schalter neben ihrem Wert, Mehrfachauswahlen wählen „ist in"
  oder „ist nicht in"; Feld- und Operatorauswahl stehen kompakt in einer Zeile.
- Seitenleiste: Unter „Einstellungen“ heißt „Profil bearbeiten“ jetzt „Mein Profil“ und öffnet das
  eigene Profil; der Stift rechts daneben führt direkt zur Bearbeitung.
- Konfiguration: Die Karten stehen linksbündig wie auf den übrigen Seiten, statt auf breiten
  Bildschirmen mittig zu stehen.
- Dateien: Ein Ordner enthält jeden Namen nur einmal. Landet eine Datei auf einem vergebenen
  Namen, wird sie Fassung der vorhandenen: beim Hochladen und Kopieren ohne Rückfrage, beim
  Verschieben, Verknüpfen und Umbenennen nach einer Rückfrage, die bei einer jüngeren Datei am
  Ziel auch nach dem Datum fragt.
- Dateien: Ein Inhalt, der am Ziel schon als Fassung vorliegt, wird nicht noch einmal abgelegt;
  Hochladen und Kopieren melden das, Verschieben bietet an, die Datei hier zu löschen.
  „Version wiederherstellen“ tauscht nur noch die vordere Fassung und lässt den Namen stehen.
- Dateien: Die Fassungen einer Datei sind nach „Geändert“ sortiert, vorne steht die jüngste. Von
  identischen Fassungen bleibt nur die älteste in der Historie. „Version wiederherstellen“ gibt
  der Fassung das Datum von jetzt, „Hochgeladen“ bleibt unverändert.
- Ordner: Einen Unterordner gleichen Namens gibt es nur einmal — Anlegen, Umbenennen und
  Verschieben auf einen vergebenen Namen werden abgelehnt.

### Behoben

- Ordner: Ein Ordner lässt sich nicht mehr in sich selbst oder einen seiner Unterordner
  verschieben; der Zweig verschwand dabei aus dem Ordnerbaum.
- Profilbild, Forenbild, Titel-Dateien und Antrags-PDFs legten bei gleichem Namen eine zweite
  Datei neben die vorhandene; die neue wird jetzt deren Fassung, und der Verweis zeigt auf sie.

## v1.0.0 — 2026-10-05

### Hinzugefügt

- Dateien: Die Migration legt die Ordner „Organisation Chor“, „Organisation Konzerte“ und
  „Verein“ mit ihren Unterordnern an; „Verein/Vorstand“ sieht nur der Vorstand.
- Dateien: Ein Upload, der in der obersten Ebene landet, zeigt in der Upload-Karte den Hinweis,
  ihn in einen Ordner zu verschieben.
- Foren: „Forum deaktivieren“ auf der Bearbeitungsseite archiviert ein Forum (Recht „Forum
  bearbeiten“).
- Datenschutz-Bestätigung: Konten mit Portalzugang ohne Tag „Mitglied“ bestätigen nach dem Login
  einmalig die Datenschutzerklärung und die Foto-Einwilligung, mit PDF und Quittung. Erledigt ist
  das mit dem Tag „DSGVO“; `datenschutz_zuruecksetzen` fragt erneut.
- Mitgliedsantrag für bestehende Konten: `send_antragslink --user NAME` schickt einem Konto ohne
  Zugang und ohne Tag „Mitglied“ den Link zu einem vorausgefüllten Antragsformular. Benutzername
  und Passwort bleiben, die Aufnahme folgt wie gewohnt über „Mitgliedschaft genehmigen“.

### Geändert

- Migration: neue Ausgangsrechte der Gruppen — Vorstand: Mitglieder anlegen/bearbeiten und
  Termine; Webmaster: Mitglieder löschen sowie Dateien, Artikel und Forum vollständig; Termine:
  Termine; Mitglied: Mitglieder benachrichtigen und Orte. Die Gruppe „Repertoire" heißt jetzt
  „KonzertOrga" und darf Termine, Repertoire und Orte verwalten.
- Migration: Webmaster und KonzertOrga werden mit festen Personen besetzt statt aus den Rechten
  des Altsystems; die Gruppe „Termine" bleibt anfangs leer.
- Dateien: Den Ordner „Eingang“ gibt es nicht mehr; Uploads ohne Zielordner landen in der
  obersten Ebene. Antrags- und Bestätigungs-PDFs liegen in „Verein/Vorstand/Mitgliedsanträge“
  statt in „Mitglieder-Verwaltung“, und die Rundmail bietet Anhänge aus „Verein“ an.
- Migration: Altdateien ohne Zuordnung zu Lied oder Artikel werden nicht mehr importiert;
  übrige Audiodateien landen weiterhin in „Probenmitschnitte“.
- Dateien: „Backstage“ erscheint in der Ordneransicht nur noch für Webmaster; die Dateien darin
  bleiben überall sonst erreichbar.
- Foren: deaktivierte (archivierte) Foren sieht nur noch, wer das neue Recht „Forum: Archiv“
  hat — auch Superuser brauchen es ausdrücklich. Nur dieses Recht erlaubt das Reaktivieren; in
  der Forenliste tragen archivierte Foren ein Archiv-Symbol.
- Navigation: der Versionslink zur Seite „Änderungen" erscheint nur noch mit dem Recht
  „Mitglieder: Berechtigungen"; die Seite selbst ist nur noch damit zugänglich.
- E-Mails: Kopf und Titel jeder Mail zeigen den Vereinsnamen (`VEREINSNAME`) statt des langen
  Namens. Die Standardtexte von `MAIL_EINLADUNG`, `MAIL_MAILINGLISTE_OPTIN` und
  `MAIL_MAILINGLISTE_WILLKOMMEN` setzen `{vereinsname}` statt `{vereinsname_lang}`; unveränderte
  Texte werden beim Start nachgezogen.
- Einladungen: Eine E-Mail-Adresse, zu der es schon ein Konto gibt, wird abgelehnt, im Portal
  wie in `make_invite_url`. Die Meldung nennt den Benutzer und verweist auf `send_antragslink`.
- Datenbestätigung: Die Pflicht-Häkchen tragen ein Sternchen. Wer bestätigt, sagt bei nicht
  mehr aktuellen Daten die sofortige Korrektur nach der Freischaltung zu, und das Quittungs-PDF
  übernimmt diesen Wortlaut. Ein Hinweis erklärt, dass das Foto-Häkchen den gespeicherten Stand zeigt.
- Datenbestätigung: Aufforderungsmail und Formular sagen, dass der Zugang zum internen Bereich bis
  zur Bestätigung gesperrt bleibt. Ein nie geänderter Mailtext `MAIL_BESTAETIGUNG` wird beim Start
  auf den neuen Standard gehoben.
- Datenbestätigung: Das Formular fragt als viertes Pflicht-Häkchen die Kenntnisnahme der
  Beitragsordnung ab, wie es die Aufforderungsmail ankündigt; das Quittungs-PDF führt sie mit auf.
- Datenbestätigung: Ein Link wirkt nur noch bei einem gesperrten Konto mit Tag „Mitglied“; nach dem
  Absenden zeigt er „Bereits bestätigt“, nach „Mitgliedschaft beenden“ ist er ungültig.
  `send_reconfirmation --print-url` sperrt jetzt wie der Mailversand, und Konten ohne Tag werden
  weder angeschrieben noch gesperrt.
- Mitgliedsantrag und Datenbestätigung: Die Beitragsordnung wird nur noch zur Kenntnis genommen,
  nicht mehr anerkannt, im Formular wie im Quittungs-PDF. Die Aufforderungsmail `MAIL_BESTAETIGUNG`
  sagt das ebenso; ein nie geänderter Text wird beim Start auf den neuen Standard gehoben.

### Behoben

- XMPP-Brücke: deaktivierte Foren bleiben außen vor — der Bot tritt ihren Räumen nicht mehr bei,
  übernimmt keine Nachrichten oder Reaktionen daraus und lädt niemanden ein. Wird ein Forum
  deaktiviert, verlässt er dessen Raum beim nächsten Abgleich.

## v1.0.0-rc7 — 2026-10-04

### Hinzugefügt

- Mitglieder: das Tag „kein Bild" kennzeichnet Personen ohne Einwilligung zur Veröffentlichung
  von Fotos. Mitgliedsantrag und Datenschutz-Bestätigung setzen oder entfernen es nach dem
  Foto-Häkchen.
- Mitglied bearbeiten: Konten ohne Tag „Mitglied" (etwa Chorleitung oder Gäste) lassen sich mit
  „Zugang sperren" und „Zugang freischalten" sperren und entsperren, ohne die Mitgliedschaft zu
  berühren. Die Aktion steht nur Superusern und Inhabern des Rechts „Kann
  Mitglieder-Berechtigungen verwalten" zur Verfügung.
- Konfiguration: `FORUM_ANZEIGE_AB` unter „Aufbewahrung & Bereinigung“ legt den Stichtag fest,
  vor dem das Portal Forenbeiträge nirgends anzeigt; gelöscht wird nichts.
- Forum bearbeiten: ein deaktiviertes Forum zeigt statt „Forum deaktivieren“ die Aktion
  „Reaktivieren“, die es wieder für alle Leser sichtbar macht.
- Forenübersicht: deaktivierte Foren erscheinen in etwas hellerer Schrift.

### Geändert

- Mitgliederliste: der Hinweis im Einladungs-Panel nennt den Vorstand statt eines Admins als
  den, der das neue Mitglied freischaltet.
- Mitgliederliste: „manuell anlegen" im Einladungs-Panel steht nur noch Superusern und Inhabern
  des Rechts „Kann Mitglieder-Berechtigungen verwalten" zur Verfügung; die Seite zum manuellen
  Anlegen prüft dasselbe Recht.
- Mitglied bearbeiten: „Ruhend setzen" heißt jetzt „Mitgliedschaft beenden" und entfernt neben
  dem Zugang auch das Tag „Mitglied"; „Zugang freischalten" heißt „Mitgliedschaft wieder
  aufnehmen" und setzt beides wieder. Beide Aktionen stehen nur Superusern und Inhabern des
  Rechts „Kann Mitglieder-Berechtigungen verwalten" zur Verfügung; ein ehemaliges Mitglied sieht
  statt „Mitgliedschaft genehmigen" nur noch „wieder aufnehmen".
- Mitglied bearbeiten und Aufgaben: das Badge „Ruhend" heißt jetzt „Kein Zugang".
- Mitgliederliste: Filter und Spalte „Aktiv" heißen jetzt „Zugang", ihre Tooltips „Zugang
  erlaubt" und „Zugang gesperrt". Die übrigen Spaltenüberschriften stehen auf Deutsch wie auf der
  Profilseite (etwa „Straße", „E-Mail", „Mobil (Privat)").
- Anmeldeseite: Titel und Begrüßung nennen den Vereinsnamen (`VEREINSNAME`) statt des langen
  Chornamens.
- Migration: alle Foren und alle Beiträge des Altportals werden übernommen; Foren ohne Beitrag ab
  dem Stichtag kommen deaktiviert an und sind nur für Inhaber der Forum-Berechtigungsverwaltung
  sichtbar.
- Migration: Absender alter Beiträge und Autoren alter Artikelfassungen ohne eigenes Konto kommen
  als Namensverweis mit nur dem Vornamen, den keine Mitgliederansicht listet.
- Migration: Artikelversionen vor dem 12.12.2015 werden nicht übernommen; Artikel, die nur
  ältere Versionen haben, entfallen ganz.

## v1.0.0-rc6 — 2026-10-04

### Geändert

- Startseite: der Schriftzug, der beim Scrollen an die Stelle der Bildmarke tritt, steht in der
  Markenfarbe statt in Schwarz.
- Datenbestätigung: wer die Aufforderung per E-Mail bekommt, kann sich bis zum Absenden des
  Bestätigungsformulars nicht mehr anmelden; das Absenden gibt den Zugang ohne Eintrittsdatum
  und ohne Willkommensmail wieder frei. Die Anmeldeseite nennt bei richtigem Passwort die Sperre
  statt eines falschen Passworts.
- Mitgliedsantrag: der Button „Antrag ansehen" in der Benachrichtigung an die Verwalter führt
  direkt auf die Bearbeiten-Seite mit „Mitgliedschaft genehmigen" statt auf das Profil.
- Mitgliedsantrag: die Option, förderndes Mitglied zu werden, wird nicht mehr angeboten.
- Mitgliedsseite: der Hinweistext zu „Mitgliedschaft genehmigen" beschreibt Zugang,
  Willkommensmail und Eintrittsdatum ausführlicher.
- Mitgliedsantrag: die Begrüßung nennt den Vereinsnamen (`VEREINSNAME`) statt des langen
  Chornamens.

## v1.0.0-rc5 — 2026-09-27

### Hinzugefügt

- Mitgliedschaft: die Gruppe „Mitglied" trägt ab jetzt die Vereinsmitgliedschaft, `is_active` nur
  noch den Zugang zum Portal. Die Aktion „Mitgliedschaft genehmigen" auf der Mitgliedsseite setzt
  beides in einem Schritt — bei einem Fördermitglied nur das Tag —, und die Karte „Mitgliedschaft"
  zeigt die zwei Zustände als Pillen. Eine ruhende Mitgliedschaft behält ihr Tag.

### Geändert

- Willkommensmail und Eintrittsdatum hängen am Tag „Mitglied": ein Konto ohne Mitgliedschaft gilt
  beim Einschalten als Reaktivierung und bekommt beides nicht. Der Schalter „Ruhend setzen" bzw.
  „Zugang freischalten" fasst Tags nicht mehr an.
- Gruppenmatrix: sie listet auch ruhende Konten, gekennzeichnet mit „ruhend" — sonst wäre das Tag
  einer ruhenden Mitgliedschaft dort nicht pflegbar. Anonymisierte Konten bleiben draußen.
- Startseite: das Menüband oben rechts trägt nur noch „Login". „Konzerte" und „Kontakt" stehen als
  Buttons unter dem Schriftzug, „Home" ist die Bildmarke links. Das Milchglas sitzt jetzt am
  Login-Knopf statt hinter der ganzen Leiste.
- Ein von Hand angelegtes Mitglied bekommt das Tag „Mitglied" und den Anlagetag als
  Eintrittsdatum.
- Migration: die Gründungsmitglieder bekommen zusätzlich das Tag „Mitglied", das Chorleiter-Konto
  bleibt aktiv und ohne Mitgliedschaft. „Gründer" ist damit ein Etikett ohne weitere Funktion.

### Behoben

- Startseite: die Auftritte, deren Ankündigungstext nur aus einem Leerzeichen besteht, fehlten
  unter MySQL/MariaDB in der Konzertliste. Deren Kollation vergleicht Zeichenketten mit
  `PAD SPACE`, wo `' ' = ''` gilt; das Kriterium prüft jetzt die Länge des Feldes. Dieselben
  Auftritte lösten darum auch keine Erinnerungsmail der Auftritts-Mailingliste aus.

## v1.0.0-rc4 — 2026-09-23

### Hinzugefügt

- Änderungen: die Versionszeile in der Seitenleiste führt auf die neue Seite `/intern/changelog/`.
  Sie zeigt je Auslieferung eine Karte mit Kennung und Datum — die laufende Version mit Markenkante
  und der Pille „Deine Version" —, ältere lädt sie beim Scrollen zu zweien nach. Gelesen wird
  `CHANGELOG.md` von `intern/auslieferungen.py`, einem eigenen Zerleger ohne Markdown-Abhängigkeit
  im Abbild.
- Terminseite: der öffentliche Ankündigungstext (`Termin.extern`) steht in einer eigenen Karte
  „Extern", die fehlt, solange das Feld leer ist. Gepflegt wird er über die gleichnamige Kachel im
  Bearbeiten-Formular (mehrzeilig, HTML erlaubt); aus dem Kalender-Offcanvas bleibt das Feld
  draußen.
- Terminliste: zwischen Datum und Termin stehen zwei schmale Spalten — ein Mikrofon für Termine mit
  Ankündigungstext, bei „Repertoire" eine Pille mit der Zahl der Lieder im Ablauf. Die Zahl kommt
  als Annotation mit der Liste, und das Datum bricht nicht mehr um. Dasselbe Mikrofon trägt im
  Kalender der Termin-Chip, dort nur am ersten Tag eines mehrtägigen Termins.
- Erinnerungsmail der Auftritts-Mailingliste: der Platzhalter `{extern}` setzt den Ankündigungstext
  des Termins ein, auf einen Absatz Fließtext reduziert (ohne Markup und ohne Linkziele). Den Text
  der Mail führt nicht mehr der Code, sondern `seed_konfiguration` in der Migration;
  `_CONFIG_DEFAULTS` hält den Schlüssel leer wie die übrigen vereinsspezifischen Texte.

### Geändert

- Syntax-Hilfe im Artikel-Editor: die Pillen sind Knöpfe — ein Klick setzt das Muster an der
  Cursorposition ein und markiert den Platzhalter. Über einer Markierung umschließen Fett, Kursiv
  und der interne Link sie, statt sie zu ersetzen; die beiden Datei-Pillen übergeben an die
  Dateisuche, und beim Medienplayer steht danach `|Titel` markiert da.
- Abstimmungen: das Ende ist Pflicht — `{abstimmung:Titel:1:TT.MM.JJJJ:A;B}`. Eine Abstimmung ohne
  Datum bliebe für immer offen; das Bearbeiten-Formular speichert sie deshalb nicht mehr, sondern
  nennt die Zeile und lässt den Text im Editor stehen. Syntaxhilfe, Editor-Gerüst (Datum in zwei
  Wochen) und die Feld-Hinweise zeigen die neue Form, „Hilfe:Wiki" erklärt sie mit Beispielen zum
  31.12.2039.
- Mitgliedskarte: kein umrandeter Kasten mehr, sondern das Muster der übrigen Detailseiten —
  Seitenkopf mit Porträt und Namen, darunter die Abschnitte als Karten in zwei Spalten. Die vier
  Kopfzeilen „Vorname: / Nachname: / Stimme: / Gruppen:" sind entfallen: der Name ist die
  Überschrift, die Stimme steht als Wort neben den Gruppen-Marken, und die Liedlisten laufen über
  die volle Breite.
- Die Stimme bleibt der Akzent dieser Seite, nur ohne Kasten: eine 4 px breite Kante am linken
  Seitenrand und ein 3-px-Ring um das Porträt. Das `(S)` neben dem Namen ist eine Pille in der
  Stimmenfarbe und sitzt **neben** dem Titel statt darin — der Titel kürzt lange Namen mit einer
  Ellipsis ab, und die traf zuvor genau das `(S)`.
- Startseite: unter „Konzerte" stehen jetzt die Termine mit einem **Ankündigungstext**
  (`Termin.extern`) statt die mit „Repertoire", und der Text wird mit ausgegeben (Adresse, Einlass,
  Eintritt, Links). **Zum Ausrollen:** ein Auftritt ohne Eintrag fehlt auf der Startseite — für
  einen Auftritt ohne Text genügt ein Leerzeichen, er wird dann ohne Ankündigungsblock gelistet.
- Erinnerungsmails der Auftritts-Mailingliste: erinnert wird, was öffentlich angekündigt ist —
  Kriterium ist der Ankündigungstext (`Termin.extern`) statt „Repertoire", das jetzt nur noch die
  Karte „Lieder" auf der Terminseite steuert. **Zum Ausrollen:** ein Auftritt mit „Repertoire",
  aber ohne Ankündigungstext bekommt keine Erinnerung mehr; er braucht einen Text.
- Datumsangaben nennen den kurzen Wochentag und den Monat als Zahl: „Mi, 24.09.2026 19:30" statt
  „24. September 19:30". Das gilt überall, wo `replacements.format_datetime` ausgibt; die Zweige
  für „heute" (nur Uhrzeit) und „gestern" bleiben wie sie waren.
- Terminliste: die Spalte „Du" ist entfallen. Stattdessen pulsiert bei offener Antwort das eigene
  Kästchen der Aufstellung und mit ihm der Terminname — beides nur bei kommenden Terminen ohne
  eigene Antwort. Wer Bewegung reduziert haben will, bekommt die Rahmen stehend statt blinkend.
- Migration: der Neuaufbau startet mit den Gründerinnen und Gründern als einzigen aktiven Konten,
  Eintrittsdatum 17.06.2026; jeder andere Zugang kommt deaktiviert und ohne Eintrittsdatum an.
  **Zum Ausrollen:** diese Konten werden einzeln über die Mitgliederverwaltung freigeschaltet — das
  verschickt die Willkommensmail und stempelt den Tag der Aktivierung als Eintritt.
- Migration: welche Lieder nach dem Import aktiv sind, sagt der Wiki-Artikel „Aktuell" mit seinem
  Abschnitt „Repertoire für 2026/27" (18 Titel) — die Altsystem-Spalte `repertoire.aktiv` hatte die
  Auswahl mehrerer Spielzeiten angesammelt (32 Titel). Alles andere ist archiviert; die sieben
  Weihnachtslieder bleiben davon unberührt und stehen weiter über den Filter „Weihnachten".
- Die Altdaten bringen eigenes HTML mit: beim Anzeigen werden Zeilenumbrüche zu `<br>`,
  `style`-Angaben entfernt und Überschriften zu `<strong>` (55 der 74 Zeilen beginnen mit `<h1>`).
  Der gespeicherte Wert bleibt unberührt — eine Anzeigeregel, keine Sanitisierung.
- Diese Datei folgt jetzt Keep a Changelog: je Auslieferung eine Gruppe nach Art der Änderung, je
  Eintrag höchstens drei Sätze. Die Überschriften der Auslieferungen bleiben unverändert — der
  `update`-Hook vergleicht das zweite Feld der Zeile mit dem Tagnamen.
- Änderungsseite: die Karten sind auf 1280 px gedeckelt und bleiben linksbündig.
- Bekannte technische Schuld: der neue Abschnitt „First install vs. legacy import" hält fest, dass
  eine Erst-Installation ohne die Migration ohne Gruppen, Ordner und Administrator dasteht, und
  beschreibt die geplante Trennung von Altdaten-Import und Installationsvorgaben. Gebaut wird sie
  nach der Migration.

### Behoben

- Chorleiter und Musiker: der senkrecht beschriftete Gruppenstreifen der Mitgliederliste und die
  neutrale Topbar-Pille stehen jetzt in `--t3` — auf ihrer Tintfläche erreichte `--t4` nur 2,2:1.
  Balken und Kartenkante bleiben bei `--t4`: ein Strich darf leise sein, ein Buchstabe nicht.
- Die Markenfarbe als Schrift auf einer Karte hat einen eigenen Token (`--brand-text`); im dunklen
  Thema stand sie dort bei 2,7:1. Vier Stellen, die sich dafür ein hartkodiertes Rosa gegeben
  hatten, folgen jetzt ebenfalls der Markenfarbe.
- Startseite: im Impressum steht der Vereinsname jetzt über der Vereinsadresse — war eine Adresse
  konfiguriert, nannte die Karte „Verantwortlich für den Webauftritt" nur die Adresse.
- Migration: `{abstimmung:…}`-Direktiven aus dem Altportal bekommen beim Import die Frist
  30.06.2026. Ohne Ablaufdatum bliebe die Abstimmung im Portal für immer offen, statt ihr Ergebnis
  zu zeigen — im Altbestand trägt keine einzige eine Frist. Ergänzt wird nur, was der Renderer
  auswertet; die Syntax-Beispiele in „Hilfe:Wiki" bleiben unangetastet.

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
