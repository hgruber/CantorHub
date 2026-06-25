# E-Mails in CantorHub

Alle ausgehenden Mails laufen durch `send_branded_mail()` in `intern/mail.py`. Die
Funktion baut eine HTML-Mail mit eingebettetem Logo (`cid:logo`) und einem
Plain-Text-Fallback auf. Der Absender ist immer `get_from_email()` — er liest
`DEFAULT_FROM_EMAIL` aus der `Konfiguration`-Tabelle, mit Fallback auf
`settings.DEFAULT_FROM_EMAIL`. Fehler werden geloggt und nie an den Aufrufer
weitergegeben.

## E-Mail-Übersicht

| Zweck | Empfänger | Template | Trigger |
|---|---|---|---|
| Passwort-Reset | `user.email` | `emails/password_reset.html` | POST `/intern/passwort/` (nur wenn Konto aktiv) |
| Mitgliedsantrag – Bestätigung an Bewerber | E-Mail aus Beitrittsformular | `emails/mitglied_beitritt_success.html` | POST `/intern/beitritt/<token>/` |
| Mitgliedsantrag – Admin-Benachrichtigung | `ANTRAG_EMAIL` (Konfig) oder alle Nutzer mit `intern.change_user` | `emails/mitglied_antrag_admin.html` | POST `/intern/beitritt/<token>/` (selber Auslöser wie Zeile zuvor) |
| Einladung zur Registrierung | Eingegebene E-Mail-Adresse | `emails/mitglied_invite.html` | POST `/intern/mitglied/einladen/` (Perm: `intern.add_user`) |
| Erstaktivierung – Willkommen | `user.email` | `emails/mitglied_willkommen.html` | Signal `post_save`: `is_active` → `True` & `date_joined is None` |
| Reaktivierung | `user.email` | `emails/mitglied_reaktiviert.html` | Signal `post_save`: `is_active` → `True` & `date_joined` bereits gesetzt |
| Datenbestätigung – Aufforderung | `user.email` | `emails/mitglied_bestaetigung_aufforderung.html` | Management-Command `send_reconfirmation` |
| Datenbestätigung – Quittung | `user.email` | `emails/mitglied_bestaetigung_bestaetigt.html` | POST `/intern/bestaetigung/<token>/` |
| Rundmail an Mitglieder | Alle ausgewählten Empfänger | `emails/mitglied_benachrichtigung.html` | POST `/intern/mitglied/benachrichtigen/` (Perm: `intern.notify_users`) |

## Konfigurierbare Mail-Texte

Die meisten Mails haben einen anpassbaren Textteil, der über die `Konfiguration`-Tabelle
(editierbar unter `/intern/konfiguration/`) gepflegt wird. Der Schlüssel wird in
`format_config_mail()` / `format_config_text()` gelesen und unterstützt Platzhalter wie
`{vorname}`, `{vereinsname}`, `{link}` u. a. — vollständige Referenz in `configuration.md`.

| Mail | Konfig-Schlüssel |
|---|---|
| Passwort-Reset | `MAIL_NEUES_PASSWORT` |
| Mitgliedsantrag – Bestätigung | `MAIL_ANTRAG` |
| Mitgliedsantrag – Admin-Notify | `MAIL_ANTRAG_ADMIN` |
| Einladung | `MAIL_EINLADUNG` |
| Erstaktivierung | `MAIL_WILLKOMMEN` |
| Reaktivierung | `MAIL_REAKTIVIERT` |
| Datenbestätigung – Aufforderung | `MAIL_BESTAETIGUNG` |
| Datenbestätigung – Quittung | `MAIL_BESTAETIGUNG_BESTAETIGT` |

Ist ein Schlüssel leer, wird nur das HTML-Template ohne Fließtext-Block gerendert.

## Anhänge

Zwei Mails enthalten ein PDF als Anhang:

- **Mitgliedsantrag – Bestätigung**: das ausgefüllte Antragsformular, erzeugt von
  `_save_antrag_pdf()` in `views/auth.py` mit reportlab.
- **Datenbestätigung – Quittung**: das Bestätigungsprotokoll, erzeugt von
  `_save_bestaetigung_pdf()` in `views/auth.py`. Das PDF wird außerdem im
  Filer-Ordner **„Verwaltung/Mitglieder"** gespeichert (Vorstand-only).

Die Rundmail unterstützt optionale Dateianhänge aus dem Filer.

## Aktivierungsmail-Schalter

Die Aktivierungs- und Reaktivierungsmails (Zeilen 5–6 der Tabelle) werden nur
versendet, wenn `MAIL_BEI_AKTIVIERUNG` in der Konfiguration auf `1` gesetzt ist.
Der Schalter gilt für beide Varianten gemeinsam.
