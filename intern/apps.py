import threading

from django.apps import AppConfig
from django.db.models.signals import post_migrate, post_save, pre_migrate

from .app_settings import FORUM_ANZEIGE_AB_STANDARD

# Thread-local for tracking migration status
_migrating = threading.local()


_MARKUP_HINT = (
    "Wiki-Markup erlaubt ('''fett'''; % grauer Hinweis; @ Hinweisbox; "
    "{button:Label} = Button auf {link})."
)

_CONFIG_DEFAULTS = [
    # key, default value, description
    ("EJABBERD_API_URL", "http://127.0.0.1:5280", "ejabberd REST API URL"),
    ("EJABBERD_HOST", "", "ejabberd XMPP-Domain"),
    ("EJABBERD_MUC_SERVICE", "", "ejabberd MUC-Service-Domain"),
    ("EJABBERD_BOT_JID", "", "JID des Forum-Bots"),
    ("EJABBERD_BOT_PASSWORD", "", "Passwort des Forum-Bots"),
    ("EJABBERD_BOT_PORT", "5222", "XMPP-Port des Forum-Bots"),
    ("ICAL_SECRET", "", "Geheimes Token für iCal-Feed-URL"),
    ("EMAIL_HOST", "", "SMTP-Server (leer = kein E-Mail-Versand)"),
    ("EMAIL_PORT", "25", "SMTP-Port"),
    ("EMAIL_HOST_USER", "", "SMTP-Benutzername"),
    ("EMAIL_HOST_PASSWORD", "", "SMTP-Passwort"),
    ("EMAIL_USE_TLS", "0", "SMTP STARTTLS verwenden (1/0)"),
    ("EMAIL_USE_SSL", "0", "SMTP SSL verwenden (1/0)"),
    ("DEFAULT_FROM_EMAIL", "webmaster@example.org", "Absenderadresse für E-Mails"),
    ("ZEITZONE", "Europe/Berlin",
     "Zeitzone des Portals (IANA-Name); steuert iCal/CalDAV-Uhrzeitumrechnung "
     "und Django-Zeitformatierung"),
    ("SPRACHE", "de-de",
     "Sprache des Portals; steuert Datums- und Zahlenformate sowie Djangos "
     "eigene Texte (Verwaltung, Formularfehler). Die Portaltexte selbst sind "
     "deutsch und werden nicht übersetzt"),
    ("UPLOAD_MAX_MB", "50", "Maximale Upload-Größe in MB"),
    ("MAP_CENTER_ID", "1", "ID des Orts, der als Karten-Mittelpunkt dient"),
    ("MAP_DEFAULT_ZOOM", "12", "Standard-Zoomstufe der Gesamtkarte"),
    ("PWRESET_MAX_PER_HOUR", "5", "Maximale Passwort-Reset-Anfragen pro IP und Stunde"),
    (
        "CARDDAV_AKTIV",
        "0",
        "CardDAV-Adressbuch für Mitglieder freischalten (1/0). Vor dem "
        "Einschalten die Mitglieder informieren — Datenschutzerklärung, "
        "Abschnitt „Sichtbarkeit Deiner Daten im Portal“.",
    ),
    (
        "CARDDAV_ADRESSBUCH_NAME",
        "",
        "Anzeigename des Adressbuchs auf dem Gerät "
        "(leer → „<Vereinsname> – Mitglieder“)",
    ),
    (
        "CARDDAV_ORGANISATION",
        "",
        "Wert der vCard-Eigenschaft ORG (leer → langer Vereinsname)",
    ),
    ("CARDDAV_FOTO", "1", "Profilbilder als PHOTO in die vCard aufnehmen (1/0)"),
    (
        "CARDDAV_AUTH_TTL",
        "300",
        "Sekunden, die eine erfolgreiche CardDAV-Passwortprüfung "
        "zwischengespeichert wird (spart PBKDF2 bei häufig abfragenden Clients)",
    ),
    (
        "CARDDAV_MAX_FEHLVERSUCHE_PRO_STUNDE",
        "30",
        "Maximale fehlgeschlagene CardDAV-Anmeldungen pro IP und Stunde",
    ),
    (
        "CALDAV_AKTIV",
        "0",
        "CalDAV-Kalender für Mitglieder freischalten (1/0). Vor dem "
        "Einschalten die Mitglieder informieren — Datenschutzerklärung, "
        "Abschnitt „Sichtbarkeit Deiner Daten im Portal“.",
    ),
    (
        "CALDAV_KALENDER_NAME",
        "",
        "Anzeigename des Terminkalenders auf dem Gerät "
        "(leer → „<Vereinsname> – Termine“)",
    ),
    (
        "CALDAV_GEBURTSTAGE",
        "1",
        "Geburtstage als zweiten Kalender ausliefern (1/0). Enthält nur "
        "Mitglieder, die ihr Geburtsdatum nicht verborgen haben.",
    ),
    (
        "CALDAV_GEBURTSTAGE_NAME",
        "",
        "Anzeigename des Geburtstagskalenders "
        "(leer → „<Vereinsname> – Geburtstage“)",
    ),
    (
        "CALDAV_TAGE_RUECKWIRKEND",
        "365",
        "Wie viele Tage in die Vergangenheit Termine ausgeliefert werden",
    ),
    (
        "CALDAV_AUTH_TTL",
        "300",
        "Sekunden, die eine erfolgreiche CalDAV-Passwortprüfung "
        "zwischengespeichert wird (spart PBKDF2 bei häufig abfragenden Clients)",
    ),
    (
        "CALDAV_MAX_FEHLVERSUCHE_PRO_STUNDE",
        "30",
        "Maximale fehlgeschlagene CalDAV-Anmeldungen pro IP und Stunde",
    ),
    ("NOTIFY_POLL_MS", "10000", "Abfrageintervall für Benachrichtigungen (ms)"),
    ("NOTIFY_DISMISS_MS", "6000", "Anzeigedauer einer Benachrichtigung (ms)"),
    (
        "TERMIN_BANNER_AKTIV",
        "1",
        "Terminerinnerung unterhalb der Topbar anzeigen (1/0). Wird sonst pro "
        "Mitglied und Sitzung wegklickbar angezeigt.",
    ),
    ("VEREINSNAME", "", "Name des Chors"),
    (
        "VEREINSNAME_LANG",
        "Just Gospel! Frankfurt",
        "Langer Vereinsname mit Ort (für E-Mail-Header, Seitentitel)",
    ),
    ("VEREINSNAME_KURZ", "", "Kurzer Vereinsname (für Sidebar, Alt-Texte)"),
    (
        "BRAND_FARBE",
        "#2b6cb0",
        "Akzentfarbe des Portals (Hex; Buttons, Links, Sidebar-Hervorhebung, "
        "Mail-Header, PDF-Briefkopf)",
    ),
    (
        "VEREINSADRESSE",
        "",
        "Ladungsfähige Kontaktanschrift des Vereins (Datenschutzerklärung, "
        "Abschnitt „Verantwortliche“; mehrzeilig erlaubt; leer → es werden nur "
        "die Vorstandsnamen genannt)",
    ),
    (
        "HOMEPAGE_UEBER_UNS",
        "Wir sind ein Chor aus Menschen, die gern gemeinsam singen — einmal in der "
        "Woche zur Probe und ein paar Mal im Jahr auf der Bühne. Unser Repertoire "
        "reicht vom Volkslied bis zur Moderne. Schau Dir unsere nächsten Auftritte "
        "an oder komm einfach einmal zur Probe vorbei.",
        "Über-uns-Text der öffentlichen Startseite (mehrzeilig erlaubt)",
    ),
    (
        "HOMEPAGE_AUFNAHME",
        "Du singst gern und möchtest mitmachen? Wir freuen uns über neue Stimmen in "
        "allen Lagen — melde Dich bei uns!",
        "Wir-suchen-Text der öffentlichen Startseite (mehrzeilig erlaubt)",
    ),
    (
        "MAIL_ANTRAG",
        "Hallo {vorname},\n\n"
        "vielen Dank für Deinen Mitgliedsantrag. Wir haben ihn erhalten und melden uns, "
        "sobald er geprüft ist.\n\n"
        "Dein gewünschter Benutzername: '''{username}'''\n\n"
        "Eine Kopie Deines Antrags findest Du im Anhang dieser E-Mail.\n\n"
        "Herzliche Grüße\n"
        "Dein Vorstand von {vereinsname}",
        "Bestätigungsmail an Antragsteller. " + _MARKUP_HINT
        + " Platzhalter: {vorname}, {nachname}, {email}, {xmpp}, {user}, {username}, "
        "{stimme}, {vereinsname}",
    ),
    (
        "MAIL_ANTRAG_ADMIN",
        "Es liegt ein neuer Mitgliedsantrag vor:\n\n"
        "'''{vorname} {nachname}''' ({email})\n\n"
        "{hinweise}\n\n"
        "{button:Antrag ansehen}\n\n"
        "% Falls der Button nicht funktioniert, kopiere diesen Link in Deinen Browser: {link}",
        "Admin-Benachrichtigung bei neuem Antrag. " + _MARKUP_HINT
        + " Platzhalter: {vorname}, {nachname}, {email}, {link}, {vereinsname}, "
        "{hinweise} (siehe MAIL_ANTRAG_ADMIN_*)",
    ),
    (
        "MAIL_ANTRAG_ADMIN_MINDERJAEHRIG",
        "@ '''Hinweis:''' Der Antragsteller war zum Zeitpunkt des Antrags minderjährig. "
        "Es ist eine schriftliche Einwilligung der Erziehungsberechtigten erforderlich.",
        "Zusatz zu MAIL_ANTRAG_ADMIN, wenn der Antragsteller minderjährig ist "
        "(erscheint an der Stelle von {hinweise})",
    ),
    (
        "MAIL_ANTRAG_ADMIN_FOERDER",
        "@ '''Hinweis:''' Der Antragsteller möchte förderndes Mitglied werden und wurde "
        "der entsprechenden Gruppe zugeordnet.",
        "Zusatz zu MAIL_ANTRAG_ADMIN bei Fördermitgliedschaft "
        "(erscheint an der Stelle von {hinweise})",
    ),
    (
        "SATZUNG_FILE_ID",
        "",
        "Filer-Datei-ID der aktuellen Satzung (leer → kein Link in Formularen)",
    ),
    (
        "BEITRAGSORDNUNG_FILE_ID",
        "",
        "Filer-Datei-ID der aktuellen Beitragsordnung (leer → kein Link in Formularen)",
    ),
    (
        "ANTRAG_EMAIL",
        "",
        "E-Mail-Adresse für Eingang neuer Mitgliedsanträge (leer → Mitglieder mit change_user-Recht)",
    ),
    (
        "VEREINS_URL",
        "",
        "Basis-URL des Portals für Links in E-Mails (z.B. https://portal.example.com)",
    ),
    (
        "MAIL_BEI_AKTIVIERUNG",
        "1",
        "Aktivierungsmails versenden (0 = deaktiviert, z.B. während Tests)",
    ),
    (
        "MAIL_BESTAETIGUNG",
        "Liebe/r {vorname},\n\n"
        "wir bitten Dich, Deine im Mitgliederportal gespeicherten Daten zu prüfen "
        "und zu bestätigen, dass sie korrekt und aktuell sind.\n\n"
        "Gleichzeitig bitten wir Dich, unsere Datenschutzerklärung erneut zu "
        "bestätigen und die Beitragsordnung des Chors zur Kenntnis zu nehmen.\n\n"
        "Sobald Deine Bestätigung erfolgt ist, kannst Du Dich im Mitgliederportal "
        "anmelden.\n\n"
        "{button:Jetzt bestätigen}\n\n"
        "Herzliche Grüße\n"
        "Dein Vorstand von {vereinsname}\n\n"
        "% Der Link ist 30 Tage gültig.\n"
        "% Falls der Button nicht funktioniert, kopiere diesen Link in Deinen Browser: {link}",
        "Aufforderung zur Datenbestätigung. " + _MARKUP_HINT
        + " Platzhalter: {vorname}, {nachname}, {email}, {xmpp}, {user}, {stimme}, "
        "{link}, {vereinsname}",
    ),
    (
        "MAIL_BESTAETIGUNG_BESTAETIGT",
        "Hallo {vorname},\n\n"
        "vielen Dank für Deine Bestätigung! Anbei findest Du eine Kopie als PDF.\n\n"
        "Herzliche Grüße\nDein Vorstand von {vereinsname}",
        "Quittung an Mitglied nach Datenbestätigung. " + _MARKUP_HINT
        + " Platzhalter: {vorname}, {nachname}, {user}, {stimme}, {vereinsname}",
    ),
    (
        "MAIL_EINLADUNG",
        "Hallo,\n\n"
        "Du wurdest eingeladen, Mitglied bei '''{vereinsname}''' zu werden. "
        "Über den folgenden Button kannst Du Deinen Antrag ausfüllen.\n\n"
        "{button:Jetzt Mitglied werden}\n\n"
        "% Dieser Einladungs-Link ist 7 Tage gültig. Wenn Du keine Einladung erwartet "
        "hast, kannst Du diese E-Mail einfach ignorieren.\n"
        "% Falls der Button nicht funktioniert, kopiere diesen Link in Deinen Browser: {link}",
        "Einladungs-Mail (ohne Empfängerkonto, daher keine Mitgliedsdaten). "
        + _MARKUP_HINT + " Platzhalter: {link}, {vereinsname}, {vereinsname_lang}",
    ),
    (
        "MAIL_NEUES_PASSWORT",
        "Hallo {vorname},\n\n"
        "über den folgenden Button kannst Du ein neues Passwort für Deinen Benutzernamen "
        "'''{user}''' setzen.\n\n"
        "{button:Passwort zurücksetzen}\n\n"
        "% Wenn Du das nicht angefordert hast, kannst Du diese E-Mail einfach ignorieren "
        "— Dein Passwort bleibt unverändert.\n"
        "% Falls der Button nicht funktioniert, kopiere diesen Link in Deinen Browser: {link}",
        "Passwort-zurücksetzen-Mail. " + _MARKUP_HINT
        + " Platzhalter: {vorname}, {nachname}, {email}, {xmpp}, {user}, {stimme}, "
        "{link}, {vereinsname}",
    ),
    (
        "MAIL_WILLKOMMEN",
        "Liebe/r {vorname},\n\n"
        "wir freuen uns sehr, Dich als neues Mitglied bei {vereinsname} begrüßen zu dürfen!\n\n"
        "Dein Benutzerkonto ist jetzt freigeschaltet. Du kannst Dich ab sofort mit dem "
        "Benutzernamen '''{user}''' im Mitgliederportal anmelden.\n\n"
        "{button:Zum Mitgliederportal}\n\n"
        "Herzliche Grüße\nDein Vorstand von {vereinsname}",
        "Willkommens-Mail bei erster Aktivierung. " + _MARKUP_HINT
        + " Platzhalter: {vorname}, {nachname}, {email}, {xmpp}, {user}, {stimme}, "
        "{link} (Login-Seite), {vereinsname}",
    ),
    (
        "MAIL_REAKTIVIERT",
        "Liebe/r {vorname},\n\n"
        "Dein Mitgliedskonto bei {vereinsname} wurde wieder aktiviert.\n\n"
        "Du kannst Dich ab sofort wieder im Mitgliederportal anmelden.\n\n"
        "{button:Zum Mitgliederportal}\n\n"
        "Herzliche Grüße\nDein Vorstand von {vereinsname}",
        "Mail bei Reaktivierung eines Mitglieds. " + _MARKUP_HINT
        + " Platzhalter: {vorname}, {nachname}, {email}, {xmpp}, {user}, {stimme}, "
        "{link} (Login-Seite), {vereinsname}",
    ),
    (
        "MAIL_RUNDMAIL",
        "Hallo {vorname},\n\n{text}",
        "Rahmen der Rundmail an Mitglieder; {text} ist der im Formular eingegebene Text. "
        + _MARKUP_HINT + " Platzhalter: {vorname}, {text}, {vereinsname}",
    ),
    # --- Öffentliche Auftritts-Mailingliste ---------------------------------
    (
        "MAILINGLISTE_WOCHEN",
        "4,1",
        "Vorlaufzeiten der Auftritts-Informationen in Wochen, kommagetrennt "
        "(z.B. '4,1' = vier Wochen und eine Woche vorher)",
    ),
    (
        "MAILINGLISTE_VERSANDZEIT",
        "18:00",
        "Uhrzeit HH:MM — nur Fallback für Termine ohne Uhrzeit. Sonst geht die "
        "Information zur Uhrzeit des Termins raus, also am selben Wochentag.",
    ),
    (
        "MAILINGLISTE_INTERVALL_MIN",
        "10",
        "Prüfintervall des Informations-Dauerlaufs in Minuten",
    ),
    (
        "MAILINGLISTE_OPTIN_TAGE",
        "7",
        "Gültigkeit des Bestätigungslinks in Tagen — dieselbe Zahl ist die Frist, "
        "nach der unbestätigte Anmeldungen gelöscht werden. Minimum 1 Tag; 0 würde "
        "jeden Link sofort ungültig machen und wird deshalb auf 1 angehoben.",
    ),
    (
        "MAILINGLISTE_TEXT",
        "Trag Dich hier ein, wenn wir Dich über unsere öffentlichen Auftritte "
        "informieren sollen. Wir schreiben Dir vier Wochen und noch einmal eine "
        "Woche vor jedem Konzert — also nur ein paar Nachrichten im Jahr.\n\n"
        "Nach dem Absenden bekommst Du eine E-Mail mit einem Bestätigungslink. "
        "Erst wenn Du darauf klickst, tragen wir Dich ein.",
        "Einleitungstext des öffentlichen Anmeldeformulars unter /auftritte/. "
        "Reiner Text, kein Markup — Absätze werden als Zeilenumbrüche gezeigt.",
    ),
    (
        "MAILINGLISTE_EINWILLIGUNG",
        "Ich möchte per E-Mail über die öffentlichen Auftritte informiert werden. "
        "Meine Adresse wird ausschließlich dafür verwendet und nicht an Dritte "
        "weitergegeben. Ich kann die Einwilligung jederzeit über den "
        "Abmelde-Link in jeder E-Mail widerrufen.",
        "Text der Einwilligungs-Checkbox. Wird bei jeder Anmeldung als "
        "Schnappschuss mitgespeichert (Nachweispflicht Art. 7 DSGVO).",
    ),
    (
        "MAIL_MAILINGLISTE_OPTIN",
        "Hallo{name_anrede},\n\n"
        "Du möchtest über die öffentlichen Auftritte von '''{vereinsname}''' "
        "informiert werden. Bitte bestätige das noch mit einem Klick — vorher "
        "tragen wir Dich nicht ein.\n\n"
        "{button:Eintrag bestätigen}\n\n"
        "% Wenn Du das nicht warst, ignoriere diese E-Mail einfach. Ohne "
        "Bestätigung passiert nichts.\n"
        "% Falls der Button nicht funktioniert, kopiere diesen Link in Deinen "
        "Browser: {link}",
        "Bestätigungsmail des Double-Opt-ins. " + _MARKUP_HINT
        + " Platzhalter: {name}, {name_anrede}, {email}, {link}, {abmelden}, "
        "{vereinsname}, {vereinsname_lang}",
    ),
    (
        "MAIL_MAILINGLISTE_WILLKOMMEN",
        "Hallo{name_anrede},\n\n"
        "Du stehst jetzt auf unserer Auftritts-Liste. Wir melden uns rechtzeitig "
        "vor jedem öffentlichen Auftritt — und sonst nicht.\n\n"
        "Wir freuen uns, Dich bei einem Konzert zu sehen!\n\n"
        "Herzliche Grüße\n{vereinsname}",
        "Willkommensmail nach bestätigter Anmeldung. " + _MARKUP_HINT
        + " Platzhalter: {name}, {name_anrede}, {email}, {abmelden}, "
        "{vereinsname}, {vereinsname_lang}",
    ),
    (
        "MAIL_MAILINGLISTE_BEREITS_ANGEMELDET",
        "Hallo{name_anrede},\n\n"
        "Deine Adresse steht bereits auf unserer Auftritts-Liste — Du musst "
        "nichts weiter tun.\n\n"
        "% Wenn Du keine Informationen mehr möchtest, kannst Du Dich hier "
        "austragen: {abmelden}",
        "Antwort, wenn sich eine bestätigte Adresse erneut einträgt. "
        + _MARKUP_HINT + " Platzhalter: {name}, {name_anrede}, {email}, "
        "{abmelden}, {vereinsname_lang}",
    ),
    (
        "MAIL_MAILINGLISTE_ERINNERUNG",
        "== {titel} ==\n\n"
        "{wochentag}, {datum}{uhrzeit_text}\n"
        ": {ort}\n"
        ": {ort_adresse}\n\n"
        "{extern}\n\n"
        "In {wochen_text} ist es soweit — wir freuen uns, wenn Du dabei bist.\n\n"
        "Herzliche Grüße\n{vereinsname}",
        "Information zu einem Auftritt. Wiki-Markup erlaubt. Platzhalter: {titel}, "
        "{datum}, {wochentag}, {uhrzeit}, {uhrzeit_text}, {ort}, {ort_adresse}, "
        "{extern} (der Ankündigungstext als Fließtext, ohne Markup), {wochen}, "
        "{wochen_text}, {name}, {abmelden}, {vereinsname}, {vereinsname_lang}.",
    ),
    (
        "MAIL_FOOTER",
        "Bitte antworte nicht auf diese E-Mail. Dies ist eine automatische Nachricht "
        "aus dem Mitgliederportal von {vereinsname}.",
        "Fußzeile aller E-Mails (leer = keine Fußzeile). Platzhalter: {vereinsname}, "
        "{vereinsname_lang}, {vereinsname_kurz}",
    ),
    # --- Mitglieds-Fristen (Einladung, Datenbestätigung) ---
    (
        "MITGLIED_EINLADUNG_TAGE",
        "7",
        "Gültigkeit des signierten Einladungs-Links zum Beitrittsformular in Tagen",
    ),
    (
        "MITGLIED_BESTAETIGUNG_TAGE",
        "30",
        "Gültigkeit des Datenbestätigungs-Links (Re-Confirmation) in Tagen",
    ),
    # --- Aufbewahrungsfristen der Cleanup-Jobs ---
    (
        "AENDERUNGSPROTOKOLL_AUFBEWAHRUNG_TAGE",
        "1095",
        "Aufbewahrungsfrist des Änderungsprotokolls in Tagen (Datenschutzerklärung, "
        "Abschnitt „Speicherdauer“; Standard 3 Jahre)",
    ),
    (
        "DATEIVERSION_AUFBEWAHRUNG_TAGE",
        "730",
        "Aufbewahrungsfrist alter Dateifassungen in Tagen (Standard 2 Jahre; "
        "Komfort-Feature, kein Archiv)",
    ),
    (
        "DATEIVERSION_AUFBEWAHRUNG_ANZAHL",
        "10",
        "Anzahl Fassungen, die je Datei mindestens behalten werden",
    ),
    (
        "ERINNERUNG_VERSAND_AUFBEWAHRUNG_TAGE",
        "365",
        "Aufbewahrungsfrist der Versand-Marker (ErinnerungVersand) in Tagen",
    ),
    (
        "FORUM_ANZEIGE_AB",
        FORUM_ANZEIGE_AB_STANDARD,
        "Stichtag der Foren (JJJJ-MM-TT): ältere Beiträge zeigt das Portal nicht an, "
        "gelöscht wird nichts",
    ),
    # --- iCal-Feed / CalDAV ---
    (
        "ICAL_TAGE_RUECKWIRKEND",
        "180",
        "Wie viele Tage in die Vergangenheit der öffentliche iCal-Feed Termine "
        "ausliefert (Spiegel zu CALDAV_TAGE_RUECKWIRKEND)",
    ),
    (
        "CALDAV_STANDARDDAUER_STUNDEN",
        "2",
        "Standarddauer eines Termins ohne Endzeitpunkt in Stunden (iCal-Feed, CalDAV "
        "und time-range-Filter)",
    ),
    # --- ejabberd REST-API und Bot-Intervalle ---
    (
        "EJABBERD_API_TIMEOUT",
        "10",
        "Timeout der ejabberd REST-API-Anfragen in Sekunden",
    ),
    (
        "EJABBERD_BOT_RESCAN_SECONDS",
        "60",
        "Intervall in Sekunden, in dem der Bot nach neuen Foren sucht",
    ),
    (
        "EJABBERD_BOT_RELAY_SECONDS",
        "3",
        "Intervall in Sekunden, in dem der Bot Forum→MUC und Reaktionen weiterleitet",
    ),
    # --- Karte: OSM-Tile- und Geocoder-Proxy ---
    (
        "OSM_TILE_URL",
        "https://tile.openstreetmap.org",
        "Basis-URL des Tile-Servers (ohne nachfolgenden /{z}/{x}/{y}.png)",
    ),
    (
        "OSM_NOMINATIM_URL",
        "https://nominatim.openstreetmap.org",
        "Basis-URL des Nominatim-Geocoders (ohne /search)",
    ),
    (
        "MAP_CENTER_LAT",
        "50.1109",
        "Breitengrad des Karten-Mittelpunkts als Fallback, wenn MAP_CENTER_ID keinen "
        "Ort liefert",
    ),
    (
        "MAP_CENTER_LNG",
        "8.6821",
        "Längengrad des Karten-Mittelpunkts als Fallback, wenn MAP_CENTER_ID keinen "
        "Ort liefert",
    ),
    # --- Datei-Archiv ---
    (
        "FILE_PREFIX",
        "JG",
        "Präfix für die alternativen Dateinamen im Lied-Archiv (z. B. JG-Titel)",
    ),
    # --- Datenschutzerklärung: Hosting-Anbieter und Aufsichtsbehörde ---
    (
        "HOSTING_ANBIETER_NAME",
        "Hetzner Online GmbH",
        "Name des Hosting-Anbieters in der Datenschutzerklärung, Abschnitt "
        "„Hosting und technischer Betrieb“",
    ),
    (
        "HOSTING_ANBIETER_ANSCHRIFT",
        "Industriestr. 25, 91710 Gunzenhausen, Deutschland",
        "Anschrift des Hosting-Anbieters in der Datenschutzerklärung, Abschnitt "
        "„Hosting und technischer Betrieb“ (mehrzeilig erlaubt)",
    ),
    (
        "DSB_NAME",
        "Der Hessische Beauftragte für Datenschutz und Informationsfreiheit (HBDI)",
        "Name der Datenschutz-Aufsichtsbehörde in der Datenschutzerklärung, "
        "Abschnitt „Beschwerderecht bei der Aufsichtsbehörde“",
    ),
    (
        "DSB_ANSCHRIFT",
        "Gustav-Stresemann-Ring 1, 65189 Wiesbaden",
        "Anschrift der Datenschutz-Aufsichtsbehörde in der Datenschutzerklärung, "
        "Abschnitt „Beschwerderecht bei der Aufsichtsbehörde“ (mehrzeilig erlaubt)",
    ),
    (
        "DSB_URL",
        "https://www.datenschutz.hessen.de",
        "URL der Datenschutz-Aufsichtsbehörde in der Datenschutzerklärung, "
        "Abschnitt „Beschwerderecht bei der Aufsichtsbehörde“",
    ),
]

# Alte Default-Texte: wurde ein Wert nie händisch geändert, hebt _seed_config ihn auf
# den aktuellen Default (sonst fehlten in bestehenden Installationen die Buttons).
_LEGACY_MAIL_DEFAULTS = {
    "MAIL_ANTRAG": [
        "Hallo {vorname},\n\n"
        "vielen Dank für Deinen Mitgliedsantrag. Wir haben ihn erhalten.\n"
        "Du erhältst eine weitere Nachricht, sobald dieser geprüft ist.\n\n"
        "Dein gewünschter Benutzername: {username}",
    ],
    "MAIL_ANTRAG_ADMIN": [
        "Es liegt ein neuer Mitgliedsantrag vor:\n\n{vorname} {nachname} ({email})\n\nDetails: {link}",
    ],
    "MAIL_BESTAETIGUNG": [
        "Liebe/r {vorname},\n\n"
        "wir bitten Dich, Deine im Mitgliederportal gespeicherten Daten zu prüfen "
        "und zu bestätigen, dass sie korrekt und aktuell sind.\n\n"
        "Gleichzeitig bitten wir Dich, unsere Datenschutzerklärung, die Satzung "
        "sowie die Beitragsordnung des Chors erneut zu bestätigen.\n\n"
        "Bitte klicke auf den folgenden Link (gültig 30 Tage):\n"
        "{link}\n\n"
        "Herzliche Grüße\n"
        "Dein Vorstand von {vereinsname}",
        "Liebe/r {vorname},\n\n"
        "wir bitten Dich, Deine im Mitgliederportal gespeicherten Daten zu prüfen "
        "und zu bestätigen, dass sie korrekt und aktuell sind.\n\n"
        "Gleichzeitig bitten wir Dich, unsere Datenschutzerklärung, die Satzung "
        "sowie die Beitragsordnung des Chors erneut zu bestätigen.\n\n"
        "{button:Jetzt bestätigen}\n\n"
        "Herzliche Grüße\n"
        "Dein Vorstand von {vereinsname}\n\n"
        "% Der Link ist 30 Tage gültig.\n"
        "% Falls der Button nicht funktioniert, kopiere diesen Link in Deinen Browser: {link}",
        "Liebe/r {vorname},\n\n"
        "wir bitten Dich, Deine im Mitgliederportal gespeicherten Daten zu prüfen "
        "und zu bestätigen, dass sie korrekt und aktuell sind.\n\n"
        "Gleichzeitig bitten wir Dich, unsere Datenschutzerklärung, die Satzung "
        "sowie die Beitragsordnung des Chors erneut zu bestätigen.\n\n"
        "Bis Du bestätigt hast, bleibt Dein Zugang zum internen Bereich des Portals "
        "gesperrt.\n\n"
        "{button:Jetzt bestätigen}\n\n"
        "Herzliche Grüße\n"
        "Dein Vorstand von {vereinsname}\n\n"
        "% Der Link ist 30 Tage gültig.\n"
        "% Falls der Button nicht funktioniert, kopiere diesen Link in Deinen Browser: {link}",
        "Liebe/r {vorname},\n\n"
        "wir bitten Dich, Deine im Mitgliederportal gespeicherten Daten zu prüfen "
        "und zu bestätigen, dass sie korrekt und aktuell sind.\n\n"
        "Gleichzeitig bitten wir Dich, unsere Datenschutzerklärung und die Satzung "
        "erneut zu bestätigen und die Beitragsordnung des Chors zur Kenntnis zu "
        "nehmen.\n\n"
        "Bis Du bestätigt hast, bleibt Dein Zugang zum internen Bereich des Portals "
        "gesperrt.\n\n"
        "{button:Jetzt bestätigen}\n\n"
        "Herzliche Grüße\n"
        "Dein Vorstand von {vereinsname}\n\n"
        "% Der Link ist 30 Tage gültig.\n"
        "% Falls der Button nicht funktioniert, kopiere diesen Link in Deinen Browser: {link}",
    ],
    "MAIL_BESTAETIGUNG_BESTAETIGT": [
        "Hallo {vorname},\n\nvielen Dank für Deine Bestätigung! Anbei findest Du eine Kopie als PDF.\n\n"
        "Herzliche Grüße\nDein Vorstand von {vereinsname}",
    ],
    "MAIL_EINLADUNG": [
        "Hallo,\n\nDu wurdest eingeladen, Mitglied bei {vereinsname_lang} zu werden.\n"
        "Über diesen Link kannst Du Deinen Antrag ausfüllen (7 Tage gültig):\n\n{link}",
        "Hallo,\n\n"
        "Du wurdest eingeladen, Mitglied bei '''{vereinsname_lang}''' zu werden. "
        "Über den folgenden Button kannst Du Deinen Antrag ausfüllen.\n\n"
        "{button:Jetzt Mitglied werden}\n\n"
        "% Dieser Einladungs-Link ist 7 Tage gültig. Wenn Du keine Einladung erwartet "
        "hast, kannst Du diese E-Mail einfach ignorieren.\n"
        "% Falls der Button nicht funktioniert, kopiere diesen Link in Deinen Browser: {link}",
    ],
    "MAIL_MAILINGLISTE_OPTIN": [
        "Hallo{name_anrede},\n\n"
        "Du möchtest an die öffentlichen Auftritte von '''{vereinsname_lang}''' "
        "erinnert werden. Bitte bestätige das noch mit einem Klick — vorher "
        "tragen wir Dich nicht ein.\n\n"
        "{button:Eintrag bestätigen}\n\n"
        "% Wenn Du das nicht warst, ignoriere diese E-Mail einfach. Ohne "
        "Bestätigung passiert nichts.\n"
        "% Falls der Button nicht funktioniert, kopiere diesen Link in Deinen "
        "Browser: {link}",
        "Hallo{name_anrede},\n\n"
        "Du möchtest an die öffentlichen Auftritte von '''{vereinsname}''' "
        "erinnert werden. Bitte bestätige das noch mit einem Klick — vorher "
        "tragen wir Dich nicht ein.\n\n"
        "{button:Eintrag bestätigen}\n\n"
        "% Wenn Du das nicht warst, ignoriere diese E-Mail einfach. Ohne "
        "Bestätigung passiert nichts.\n"
        "% Falls der Button nicht funktioniert, kopiere diesen Link in Deinen "
        "Browser: {link}",
    ],
    "MAIL_MAILINGLISTE_BEREITS_ANGEMELDET": [
        "Hallo{name_anrede},\n\n"
        "Deine Adresse steht bereits auf unserer Auftritts-Liste — Du musst "
        "nichts weiter tun.\n\n"
        "% Wenn Du keine Erinnerungen mehr möchtest, kannst Du Dich hier "
        "austragen: {abmelden}",
    ],
    "MAILINGLISTE_TEXT": [
        "Trag Dich hier ein, wenn wir Dich an unsere öffentlichen Auftritte "
        "erinnern sollen. Wir schreiben Dir vier Wochen und noch einmal eine "
        "Woche vor jedem Konzert — also nur ein paar Nachrichten im Jahr.\n\n"
        "Nach dem Absenden bekommst Du eine E-Mail mit einem Bestätigungslink. "
        "Erst wenn Du darauf klickst, tragen wir Dich ein.",
    ],
    "MAILINGLISTE_EINWILLIGUNG": [
        "Ich möchte per E-Mail an die öffentlichen Auftritte erinnert werden. "
        "Meine Adresse wird ausschließlich dafür verwendet und nicht an Dritte "
        "weitergegeben. Ich kann die Einwilligung jederzeit über den "
        "Abmelde-Link in jeder E-Mail widerrufen.",
    ],
    "MAIL_MAILINGLISTE_WILLKOMMEN": [
        "Hallo{name_anrede},\n\n"
        "Du stehst jetzt auf unserer Auftritts-Liste. Wir melden uns rechtzeitig "
        "vor jedem öffentlichen Auftritt — und sonst nicht.\n\n"
        "Wir freuen uns, Dich bei einem Konzert zu sehen!\n\n"
        "Herzliche Grüße\n{vereinsname_lang}",
    ],
    "MAIL_NEUES_PASSWORT": [
        "Hallo {vorname},\n\nüber diesen Link kannst Du ein neues Passwort für Deinen "
        "Benutzer '{user}' setzen:\n\n{link}\n\nWenn Du das nicht angefordert hast, kannst "
        "Du diese E-Mail ignorieren — Dein Passwort bleibt unverändert.",
        "Hallo {vorname},\n\n"
        "über den folgenden Button kannst Du ein neues Passwort für Deinen Benutzer "
        "'''{user}''' setzen.\n\n"
        "{button:Passwort zurücksetzen}\n\n"
        "% Wenn Du das nicht angefordert hast, kannst Du diese E-Mail einfach ignorieren "
        "— Dein Passwort bleibt unverändert.\n"
        "% Falls der Button nicht funktioniert, kopiere diesen Link in Deinen Browser: {link}",
    ],
    "MAIL_WILLKOMMEN": [
        "Liebe/r {vorname},\n\nwir freuen uns sehr, Dich als neues Mitglied bei {vereinsname} begrüßen zu dürfen!\n\n"
        "Dein Benutzerkonto ist jetzt freigeschaltet. Du kannst Dich ab sofort im Mitgliederportal anmelden.\n\n"
        "Herzliche Grüße\nDein Vorstand von {vereinsname}",
    ],
    "MAIL_REAKTIVIERT": [
        "Liebe/r {vorname},\n\nDein Mitgliedskonto bei {vereinsname} wurde wieder aktiviert.\n\n"
        "Du kannst Dich ab sofort wieder im Mitgliederportal anmelden.\n\n"
        "Herzliche Grüße\nDein Vorstand von {vereinsname}",
    ],
}


def _seed_config(sender, **kwargs):
    import os
    import secrets as _secrets

    from intern.models import Konfiguration

    # post_migrate: _end_migration (siehe unten) ist vor _seed_config verbunden und
    # setzt _migrating.active bereits auf False, bevor dieser Handler läuft. Ohne
    # eigenes Flag würde jedes ENV-Reseeding (bei jedem Deploy/Neustart) als
    # Änderungsprotokoll-Eintrag von "System" auftauchen, auch ohne echte Änderung.
    _migrating.active = True
    try:
        # description ist ein CharField — MySQL bricht bei Überlänge hart ab (SQLite nicht),
        # deshalb hier kappen statt den Start zu riskieren.
        max_desc = Konfiguration._meta.get_field("description").max_length

        for key, value, raw_description in _CONFIG_DEFAULTS:
            description = raw_description[:max_desc]
            env_val = os.environ.get(key)
            if env_val is not None:
                Konfiguration.objects.update_or_create(
                    key=key,
                    defaults={"value": env_val, "description": description},
                )
            else:
                obj, created = Konfiguration.objects.get_or_create(
                    key=key,
                    defaults={"value": value, "description": description},
                )
                if created:
                    continue
                fields = []
                # Unveränderte Alt-Texte auf den aktuellen Default heben; händisch
                # angepasste Texte bleiben unberührt.
                if obj.value.strip() in _LEGACY_MAIL_DEFAULTS.get(key, ()):
                    obj.value = value
                    fields.append("value")
                # Die Beschreibung ist Systemdokumentation (Platzhalter, Syntax) und
                # wird deshalb immer nachgezogen.
                if obj.description != description:
                    obj.description = description
                    fields.append("description")
                if fields:
                    obj.save(update_fields=fields)

        obj = Konfiguration.objects.get(key="ICAL_SECRET")
        if not obj.value:
            obj.value = _secrets.token_urlsafe(6)  # 8 URL-safe chars
            obj.save(update_fields=["value"])
    finally:
        _migrating.active = False


def _zeitzone_uebernehmen(zone):
    """Die Zone auch für den Prozess setzen, nicht nur für Django.

    ``time.tzset()`` gibt es auf Windows nicht — dort bleibt es bei dem, was
    Django beim Laden der Einstellungen gesetzt hat.
    """
    import os
    import time

    if not hasattr(time, "tzset"):
        return
    if os.environ.get("TZ") == zone:
        return
    os.environ["TZ"] = zone
    time.tzset()


def _erlaubte_hosts_nachziehen():
    """``ALLOWED_HOSTS``/``CSRF_TRUSTED_ORIGINS`` aus ``VEREINS_URL`` der Datenbank.

    ``settings.py`` kennt beim Laden nur die Umgebungsvariable — eine Datenbank
    gibt es dort noch nicht. Steht die Adresse bereits in der Konfiguration (der
    Normalfall ab dem zweiten Start), holen wir sie hier nach; die Variable darf
    dann entfallen.

    Der Zeitpunkt trägt: ``ready()`` läuft vor der ersten Anfrage, also bevor
    ``CsrfViewMiddleware`` die Origins in seine ``cached_property`` übernimmt.
    Später festgelegte Origins (nach der Ersteinrichtung) erreicht der Cache nicht;
    das schadet nicht, weil Django eine Anfrage vom eigenen Host ohnehin annimmt.
    """
    import logging
    import os
    import warnings

    from django.conf import settings

    if os.environ.get("VEREINS_URL"):
        return  # settings.py hat den Wert bereits verarbeitet.

    try:
        from config.datenbank import hosts_aus_url

        from .app_settings import get_base_url

        # Der DB-Zugriff in ready() ist Absicht; die RuntimeWarning dazu stünde
        # sonst in jedem Startprotokoll (wie beim Zeitzonenblock oben).
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            url = get_base_url()
    except Exception:
        # Kein Grund, den Start zu verhindern: ohne Datenbank (Testlauf, erster
        # migrate) bleibt es bei den lokalen Einträgen aus settings.py.
        return

    if url:
        settings.ALLOWED_HOSTS, settings.CSRF_TRUSTED_ORIGINS = hosts_aus_url(url)
        return

    # Noch keine Adresse: eine neue Installation, deren Einrichtungsseite unter
    # jedem Namen erreichbar sein muss. middleware.Ersteinrichtung legt die
    # Liste fest, sobald es einen Superuser gibt (einrichtung.hosts_festlegen).
    from .einrichtung import hosts_oeffnen

    hosts_oeffnen()
    logging.getLogger(__name__).info(
        "VEREINS_URL ist noch nicht konfiguriert: bis zur Ersteinrichtung ist "
        "jeder Hostname zugelassen."
    )


class InternConfig(AppConfig):
    name = "intern"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        def _start_migration(sender, **kwargs):
            _migrating.active = True

        def _end_migration(sender, **kwargs):
            _migrating.active = False

        pre_migrate.connect(_start_migration, dispatch_uid="intern_start_migration")
        post_migrate.connect(_end_migration, dispatch_uid="intern_end_migration")
        post_migrate.connect(
            _seed_config, sender=self, dispatch_uid="intern_seed_config"
        )

        from . import signals  # noqa: F401

        # django_tables2 fragt pro Zelle die Signatur der Render-Funktion ab;
        # das Ergebnis aendert sich nie (siehe tables2_beschleunigung.py).
        from .tables2_beschleunigung import einbauen as _tables2_beschleunigen

        _tables2_beschleunigen()

        # Zeitzone aus der Konfiguration in settings.TIME_ZONE nachziehen, damit
        # Legacy-ICS-Feed und Django-Vorlagen-Formatierung derselben Zone folgen
        # wie CalDAV (das daten.zeitzone() live liest). get_zeitzone() fällt auf
        # settings.TIME_ZONE zurück, wenn die DB (noch) nicht greifbar ist — beim
        # allerersten Start oder vor ``migrate`` also ein no-op. Eine nachträgliche
        # Änderung von ZEITZONE wirkt für CalDAV sofort, für den Rest beim nächsten
        # Prozess-Neustart. Der DB-Zugriff in ready() ist bewusst und try/except-
        # gesichert; die RuntimeWarning dazu unterdrücken wir gezielt.
        try:
            import warnings
            from django.conf import settings
            from .app_settings import get_zeitzone
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                settings.TIME_ZONE = get_zeitzone()
                # settings.TIME_ZONE allein erreicht nur Djangos Formatierung.
                # datetime.now() folgt der Zone des Prozesses, und die setzt
                # Django einmalig beim Laden der Einstellungen — also vor
                # diesem Nachziehen. Ohne tzset() liefe das Portal bei einer
                # abweichend konfigurierten ZEITZONE mit zwei Zeitbegriffen.
                # Bei USE_TZ = False ist jede gespeicherte Zeit naive Ortszeit;
                # eine Abweichung wäre also nicht zu bemerken, nur falsch.
                _zeitzone_uebernehmen(settings.TIME_ZONE)
        except Exception:
            pass

        # Sprache aus der Konfiguration. Ohne LocaleMiddleware bestimmt allein
        # die beim Start aktivierte Sprache, was Django ausgibt — ein Setzen
        # von settings.LANGUAGE_CODE bliebe folgenlos, deshalb activate().
        # RuntimeWarning wie oben unterdrückt: der DB-Zugriff in ready() ist
        # Absicht, und die Warnung stünde sonst in jedem Startprotokoll.
        try:
            import warnings
            from django.conf import settings
            from django.utils import translation
            from .app_settings import get_sprache

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                settings.LANGUAGE_CODE = get_sprache()
                translation.activate(settings.LANGUAGE_CODE)
        except Exception:
            pass

        _erlaubte_hosts_nachziehen()
