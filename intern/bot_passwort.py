"""Was beim Speichern eines neuen Bot-Passworts mit ejabberd passiert.

Die Konfigurationsseite setzt ein geändertes ``EJABBERD_BOT_PASSWORD`` auch in
ejabberd, und zwar **vor** dem Speichern: ``ejabberd.set_user_password`` meldet
sich mit den noch gespeicherten, also alten Zugangsdaten an. Danach merkt der Bot
die geänderte Konfiguration und startet mit dem neuen Passwort neu (siehe
``management/commands/ejabberd_bot.py``).

Hier steht nur die Entscheidung, ohne Datenbank und damit testbar; den Aufruf
macht ``views/konfiguration.py``.
"""

SCHLUESSEL = "EJABBERD_BOT_PASSWORD"

EJABBERD = "ejabberd"
NUR_SPEICHERN = "nur_speichern"

# Ändert dasselbe Speichern einen dieser Schlüssel, gehört das neue Passwort
# womöglich zu einem anderen Konto oder Server — dann nichts in ejabberd setzen;
# der Bot legt sein Konto beim Start an (ensure_bot), falls es fehlt.
_KONTO_SCHLUESSEL = ("EJABBERD_BOT_JID", "EJABBERD_HOST", "EJABBERD_API_URL")


def bot_passwort_weg(alt, neu, nur_speichern=False):
    """Entscheidet, ob ein neues Bot-Passwort in ejabberd gesetzt wird.

    ``alt`` sind die gespeicherten Werte, ``neu`` die Werte, die dieses Speichern
    schreibt (beide ``dict`` Schlüssel → Wert). Ergebnis ``None``, wenn sich das
    Bot-Passwort nicht ändert, sonst ``EJABBERD`` oder ``NUR_SPEICHERN``:

    - ``nur_speichern``: im Hinweis angekreuzt, in ejabberd schon geändert;
    - altes Passwort, Host oder JID leer: Erstbelegung, es gibt nichts zu ändern
      und keine Zugangsdaten, mit denen sich das Portal anmelden könnte;
    - JID, Host oder API-Adresse ändern sich mit: siehe ``_KONTO_SCHLUESSEL``.
    """
    if SCHLUESSEL not in neu or neu[SCHLUESSEL] == alt.get(SCHLUESSEL, ""):
        return None
    if nur_speichern:
        return NUR_SPEICHERN
    if not (alt.get(SCHLUESSEL) and alt.get("EJABBERD_HOST") and alt.get("EJABBERD_BOT_JID")):
        return NUR_SPEICHERN
    if any(k in neu and neu[k] != alt.get(k, "") for k in _KONTO_SCHLUESSEL):
        return NUR_SPEICHERN
    return EJABBERD


def lokalteil(jid):
    """``bot@chat.example.org`` → ``bot``, wie ``ejabberd.ensure_bot`` es bildet."""
    return (jid or "").split("@")[0]
