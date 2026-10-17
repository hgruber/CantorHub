"""Ob ein neuer SMTP-Zugang vor dem Speichern geprüft wird, und die Prüfung selbst.

Das Gegenstück zu ``bot_passwort.py``: dort setzt die Konfigurationsseite ein
neues Bot-Passwort vor dem Speichern in ejabberd. Ein Passwort beim Mail-Anbieter
setzen kann das Portal nicht — es meldet sich stattdessen mit den neuen Werten am
SMTP-Server an und speichert nur, wenn das gelingt. Sonst fiele ein Tippfehler erst
beim nächsten Versand auf, und das nur im Log (``send_branded_mail`` fängt alles
ab): Passwort-Reset und Erinnerungen gingen still verloren.

Einen Neustart wie beim Bot braucht es nicht: ``email_backend.DbEmailBackend``
liest den Zugang bei jeder Verbindung frisch aus der Konfiguration.

Die Entscheidung und die Fehlertexte sind frei von Datenbank und Netz und damit
testbar; ``anmeldung_pruefen`` ist der dünne Netz-Teil. Aufrufer sind
``views/konfiguration.py`` und das Formular der Ersteinrichtung (``forms.py``).
"""

import smtplib

SCHLUESSEL = (
    "EMAIL_HOST", "EMAIL_PORT", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD",
    "EMAIL_USE_TLS", "EMAIL_USE_SSL",
)

PRUEFEN = "pruefen"
NUR_SPEICHERN = "nur_speichern"
FEHLER_TLS_SSL = "tls_ssl"

TEXT_TLS_SSL = (
    "EMAIL_USE_TLS (STARTTLS) und EMAIL_USE_SSL schließen sich aus — mit beiden "
    "scheitert jeder Versand. Nichts wurde gespeichert."
)

# Wie in DbEmailBackend: ohne Zeitlimit wartete ein hängender Server, bis
# gunicorn den Worker abschießt.
ZEITLIMIT_SEKUNDEN = 10


def _an(wert):
    """Wie ``app_settings.get_config_bool``."""
    return str(wert).strip().lower() in ("1", "true", "yes", "on")


def zusammengefuehrt(alt, neu):
    """Die SMTP-Werte nach diesem Speichern: ``neu`` über ``alt``."""
    return {k: neu[k] if k in neu else alt.get(k, "") for k in SCHLUESSEL}


def smtp_pruefung(alt, neu, nur_speichern=False):
    """Entscheidet, was mit einem geänderten SMTP-Zugang beim Speichern geschieht.

    ``alt`` sind die gespeicherten Werte, ``neu`` die, die dieses Speichern
    schreibt (beide ``dict`` Schlüssel → Wert). Ergebnis ``None``, wenn sich kein
    SMTP-Schlüssel ändert, sonst:

    - ``FEHLER_TLS_SSL``: STARTTLS und SSL zugleich an — immer abgelehnt, auch
      ungeprüft, denn Django verweigert damit jede Verbindung;
    - ``NUR_SPEICHERN``: im Hinweis angekreuzt, oder der Host ist leer (Versand
      abgeschaltet, nichts zu prüfen);
    - ``PRUEFEN``: erst anmelden, dann speichern.
    """
    if not any(k in neu and neu[k] != alt.get(k, "") for k in SCHLUESSEL):
        return None
    werte = zusammengefuehrt(alt, neu)
    if _an(werte["EMAIL_USE_TLS"]) and _an(werte["EMAIL_USE_SSL"]):
        return FEHLER_TLS_SSL
    if nur_speichern or not werte["EMAIL_HOST"].strip():
        return NUR_SPEICHERN
    return PRUEFEN


def fehlertext(exc):
    """Der Satz, den die Seite zu einer gescheiterten Anmeldung zeigt."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return ("Der SMTP-Server hat die Anmeldung abgelehnt — Benutzername oder "
                "Passwort prüfen.")
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return ("Der SMTP-Server bietet die gewählte Anmeldung oder Verschlüsselung "
                "nicht an — Port und Verschlüsselung prüfen.")
    return ("Der SMTP-Server war nicht erreichbar oder hat die Verbindung abgebrochen "
            f"({exc.__class__.__name__}) — Server, Port und Verschlüsselung prüfen.")


def anmeldung_pruefen(werte):
    """Meldet sich mit ``werte`` (Schlüssel aus ``SCHLUESSEL``) an und gleich wieder ab.

    ``None`` bei Erfolg, sonst der Fehlertext. Ohne Benutzername nur Verbindung
    und Verschlüsselung — so wie der Versand selbst sich dann auch nicht anmeldet.
    """
    from django.core.mail.backends.smtp import EmailBackend

    try:
        port = int(werte["EMAIL_PORT"] or 25)
    except (TypeError, ValueError):
        return "EMAIL_PORT ist keine Zahl."
    try:
        verbindung = EmailBackend(
            host=werte["EMAIL_HOST"].strip(),
            port=port,
            username=werte["EMAIL_HOST_USER"] or None,
            password=werte["EMAIL_HOST_PASSWORD"] or None,
            use_tls=_an(werte["EMAIL_USE_TLS"]),
            use_ssl=_an(werte["EMAIL_USE_SSL"]),
            timeout=ZEITLIMIT_SEKUNDEN,
            fail_silently=False,
        )
        verbindung.open()
        verbindung.close()
    except ValueError:
        return TEXT_TLS_SSL
    except (OSError, smtplib.SMTPException) as exc:
        return fehlertext(exc)
    return None
