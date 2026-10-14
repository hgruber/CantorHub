"""Bootstrap-Einstellungen, die vor jedem Datenbankzugriff feststehen müssen.

Datenbankanbindung und Host-Listen kommen aus **einer** Umgebungsvariable je
Zweck, statt aus fünf (``DB_HOST``, ``DB_NAME``, …) bzw. aus fest verdrahteten
Listen in ``settings.py``. Alles andere gehört in die Tabelle ``Konfiguration``
und wird über ``intern.app_settings`` gelesen.

Das Modul ist bewusst frei von Django-Importen — ``settings.py`` importiert es,
bevor es selbst fertig ist, und die Tests prüfen es als ``SimpleTestCase`` ohne
Datenbank.
"""

from urllib.parse import unquote, urlsplit

# MySQL-Optionen wie zuvor in settings.py: utf8mb4 für Emoji in Forenbeiträgen,
# STRICT_TRANS_TABLES, damit eine zu lange Zeichenkette einen Fehler wirft statt
# stillschweigend abgeschnitten zu werden.
_MYSQL_OPTIONS = {
    "charset": "utf8mb4",
    "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
}


class KonfigurationsFehler(Exception):
    """Unbrauchbarer Bootstrap-Wert.

    Eigene Klasse statt ``ImproperlyConfigured``, damit das Modul ohne Django
    importierbar bleibt; ``settings.py`` übersetzt sie an der Aufrufstelle.
    """


def datenbank_aus_url(url, daten_verzeichnis):
    """``DATABASES["default"]`` aus einer Verbindungs-URL.

    ``mysql://benutzer:passwort@host:3306/name`` oder
    ``sqlite:////data/db.sqlite3`` (vier Schrägstriche — drei trennen die
    Autorität ab, der vierte gehört zum absoluten Pfad). Leere URL: SQLite als
    ``db.sqlite3`` im Datenverzeichnis, also genau das bisherige Verhalten ohne
    gesetzte Umgebungsvariablen.
    """
    if not url:
        return _sqlite(str(daten_verzeichnis).rstrip("/") + "/db.sqlite3")

    teile = urlsplit(url)
    schema = teile.scheme.lower()

    if schema in ("sqlite", "sqlite3"):
        # urlsplit("sqlite:////data/x") -> netloc "", path "/data/x".
        # Ein Host vor einem Dateipfad ist sinnlos und deshalb ein Fehler --
        # "sqlite://data/db.sqlite3" (drei statt vier Schrägstriche) ist der
        # wahrscheinlichste Tippfehler und soll nicht als leerer Pfad enden.
        if teile.netloc:
            raise KonfigurationsFehler(
                f"DATABASE_URL: SQLite kennt keinen Host ({teile.netloc!r}). "
                "Absoluter Pfad mit vier Schrägstrichen: sqlite:////data/db.sqlite3"
            )
        if not teile.path.strip("/"):
            raise KonfigurationsFehler("DATABASE_URL: SQLite ohne Dateipfad.")
        # urlsplit lässt bei vier Schrägstrichen einen zweiten am Pfadanfang
        # stehen ("//data/db.sqlite3"). Hier zusammenziehen, damit drei und vier
        # dasselbe bedeuten — der Unterschied ist eine Fussangel der URL-Form,
        # keine Absicht des Betreibers.
        return _sqlite("/" + teile.path.lstrip("/"))

    if schema in ("mysql", "mariadb"):
        name = teile.path.lstrip("/")
        if not name:
            raise KonfigurationsFehler("DATABASE_URL: MySQL ohne Datenbanknamen.")
        if not teile.hostname:
            raise KonfigurationsFehler("DATABASE_URL: MySQL ohne Host.")
        return {
            "ENGINE": "django.db.backends.mysql",
            "NAME": name,
            # unquote: Passwörter mit @ oder / müssen in der URL kodiert sein
            # (%40, %2F), sonst zerfällt sie an der falschen Stelle.
            "USER": unquote(teile.username or ""),
            "PASSWORD": unquote(teile.password or ""),
            "HOST": teile.hostname,
            "PORT": str(teile.port or 3306),
            "OPTIONS": dict(_MYSQL_OPTIONS),
        }

    raise KonfigurationsFehler(
        f"DATABASE_URL: unbekanntes Schema {teile.scheme!r}. "
        "Erlaubt sind mysql:// und sqlite://"
    )


def _sqlite(pfad):
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": pfad,
        # IMMEDIATE: eine Transaktion holt sich die Schreibsperre gleich zu
        # Beginn. Sonst bricht das Hochstufen einer Lese- zur Schreibtransaktion
        # ohne Warten mit „database is locked“ ab, sobald ein zweiter Schreiber
        # läuft — etwa die Indexier-Threads neuer Dateien (signals.py).
        "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"},
    }


# Immer erlaubt, unabhängig von der konfigurierten Adresse: nginx spricht
# gunicorn über 127.0.0.1 an (die auth_request-Unteranfrage für jede Datei unter
# /media/ trägt den Host-Header des Containers), und ohne localhost wäre eine
# lokale Testinstanz nicht bedienbar.
_LOKALE_HOSTS = ["localhost", "127.0.0.1"]
_LOKALE_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]


def hosts_aus_url(url):
    """``(ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS)`` aus der Basis-URL des Portals.

    Die Quelle ist ``VEREINS_URL`` — derselbe Wert, der die Links in den
    E-Mails trägt (``app_settings.get_base_url``). Ein Portal hat genau eine
    Adresse; sie zweimal zu pflegen, hieße nur, dass eine davon irgendwann
    falsch ist.

    Leere oder unbrauchbare URL: nur die lokalen Einträge. Das Portal startet
    dann, ist aber unter seinem echten Namen nicht erreichbar — der Aufrufer
    protokolliert das.
    """
    hosts = list(_LOKALE_HOSTS)
    origins = list(_LOKALE_ORIGINS)
    if not url:
        return hosts, origins

    teile = urlsplit(url.strip())
    if not teile.hostname or teile.scheme not in ("http", "https"):
        return hosts, origins

    if teile.hostname not in hosts:
        hosts.insert(0, teile.hostname)
    # CSRF_TRUSTED_ORIGINS braucht das Schema und, wo vorhanden, den Port.
    origin = f"{teile.scheme}://{teile.netloc}"
    if origin not in origins:
        origins.insert(0, origin)
    return hosts, origins
