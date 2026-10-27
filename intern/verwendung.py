"""Wo wird eine Datei verwendet?

Grundlage für die Warnung, dass Löschen oder Umbenennen einer Datei einen
Verweis bricht. Zwei Arten von Verweisen mit unterschiedlichem Verhalten:

* **Wiki-Links** (`[[Datei:name.pdf]]`) adressieren die Datei über ihren
  **Namen** (`replacements.internal_links`). Sie brechen beim Umbenennen — und
  beim Löschen nur dann, wenn die *letzte* File-Zeile verschwindet: liegt die
  Datei noch in einem anderen Ordner, löst der Link weiter auf.
* **Alle anderen** Verweise (Lied, Forum, Avatar, Termin, Konfiguration) hängen an der
  **PK**. Sie brechen, sobald genau diese Zeile gelöscht wird, auch wenn die
  Datei anderswo verknüpft bleibt; ein Umbenennen stört sie nicht.
"""

from django.urls import reverse

from . import liedrollen
from .models import Artikel, Forum, Konfiguration, LiedDatei, Termin, User

# Konfigurationsschlüssel mit einer Filer-ID als Wert folgen dieser Konvention;
# so werden künftige Dokumente automatisch mit erfasst (SATZUNG_FILE_ID, …).
_CONFIG_FILE_SUFFIX = "_FILE_ID"

# Jeder Verweis auf eine File-PK als (Modell, Feld) — die eine Liste hinter der
# Warnung (pk_verwendungen) und dem Umhängen beim Verschmelzen
# (verweise_umhaengen). DateiVerweiseTest vergleicht sie mit allen FKs auf
# filer.File; die Konfiguration hält ihre IDs als Text und kommt eigens dazu.
DATEI_PK_VERWEISE = [
    (LiedDatei, "datei"),
    (Forum, "bild"),
    (User, "avatar"),
]

# Dasselbe für die Mehrfachverweise (M2M): sie lassen sich nicht per update()
# umhängen, verweise_umhaengen() geht über die Zwischentabelle.
DATEI_M2M_VERWEISE = [(Termin, "dateien")]


def _artikel_lesbar(user, artikel_name):
    if user is None:
        return True
    from .views.artikel import _artikel_access

    can_read, _ = _artikel_access(user, artikel_name)
    return can_read


def wiki_verwendungen(namen, user=None):
    """{dateiname: [Verwendung, …]} für die übergebenen Dateinamen.

    Artikel, die `user` nicht lesen darf, werden nicht benannt, sondern nur
    gezählt — sonst verriete die Warnung geschützte Artikelnamen."""
    gesucht = {n for n in namen if n}
    if not gesucht:
        return {}
    treffer = {}
    for dateiname, artikelnamen in Artikel.aktuelle_datei_verweise().items():
        if dateiname not in gesucht:
            continue
        sichtbar = [a for a in artikelnamen if _artikel_lesbar(user, a)]
        verborgen = len(artikelnamen) - len(sichtbar)
        eintraege = [
            {
                "art": "wiki",
                "label": f"Wiki-Artikel „{a}“",
                "url": reverse("article_view", args=[a]),
            }
            for a in sichtbar
        ]
        if verborgen:
            eintraege.append({
                "art": "wiki",
                "label": f"{verborgen} weitere{'r' if verborgen == 1 else ''} Wiki-Artikel",
                "url": None,
            })
        treffer[dateiname] = eintraege
    return treffer


def pk_verwendungen(datei):
    """Verweise, die an der Datei-PK hängen (brechen beim Löschen dieser Zeile)."""
    eintraege = []

    for zeile in LiedDatei.objects.filter(datei=datei).select_related("lied"):
        eintraege.append({
            "art": "lied",
            "label": f"Lied „{zeile.lied.titel}“ ({liedrollen.label(zeile.rolle)})",
            "url": reverse("titel_view", args=[zeile.lied.pk]),
        })

    for forum in Forum.objects.filter(bild=datei):
        eintraege.append({
            "art": "forum",
            "label": f"Forum „{forum.thema}“ (Titelbild)",
            "url": reverse("forum_view", args=[forum.pk]),
        })

    for mitglied in User.objects.filter(avatar=datei):
        name = f"{mitglied.first_name} {mitglied.last_name}".strip() or mitglied.username
        eintraege.append({
            "art": "avatar",
            "label": f"Profilbild von {name}",
            "url": reverse("mitglied_view", args=[mitglied.pk]),
        })

    for termin in Termin.objects.filter(dateien=datei):
        eintraege.append({
            "art": "termin",
            "label": f"Termin „{termin}“ (Dateien)",
            "url": reverse("termin_view", args=[termin.pk]),
        })

    for cfg in Konfiguration.objects.filter(key__endswith=_CONFIG_FILE_SUFFIX):
        if (cfg.value or "").strip() == str(datei.pk):
            eintraege.append({
                "art": "konfiguration",
                "label": f"Konfiguration: {cfg.description or cfg.key}",
                "url": reverse("konfiguration"),
            })

    return eintraege


def verweise_umhaengen(alt_pk, neu_pk):
    """Alles, was an der Zeile `alt_pk` hängt, auf `neu_pk` umbiegen — wenn
    beim Verschmelzen eine Zeile im Zielordner keinen Platz hat.

    Per update(): Das ist keine inhaltliche Änderung am Lied oder Mitglied,
    das Änderungsprotokoll bleibt davon frei."""
    if alt_pk == neu_pk:
        return
    for modell, feld in DATEI_PK_VERWEISE:
        modell.objects.filter(**{f"{feld}_id": alt_pk}).update(**{f"{feld}_id": neu_pk})
    for modell, feld in DATEI_M2M_VERWEISE:
        m2m = getattr(modell, feld)
        zwischen = m2m.through
        quelle = f"{m2m.field.m2m_field_name()}_id"
        datei = f"{m2m.field.m2m_reverse_field_name()}_id"
        # Wer beide Zeilen schon trägt, behält nur die neue — sonst verletzte
        # das Umhängen den Unique-Index der Zwischentabelle.
        schon = list(zwischen.objects.filter(**{datei: neu_pk}).values_list(quelle, flat=True))
        zwischen.objects.filter(**{datei: alt_pk, f"{quelle}__in": schon}).delete()
        zwischen.objects.filter(**{datei: alt_pk}).update(**{datei: neu_pk})
    # Gleicher Vergleich wie in pk_verwendungen (mit strip), damit Warnung und
    # Umhängen dieselben Einträge treffen. save() statt update(): post_save
    # leert den Konfigurations-Puffer der laufenden Anfrage.
    for cfg in Konfiguration.objects.filter(key__endswith=_CONFIG_FILE_SUFFIX):
        if (cfg.value or "").strip() == str(alt_pk):
            cfg.value = str(neu_pk)
            cfg.save(update_fields=["value"])


def datei_verwendungen(dateien, user=None, beim_loeschen=True):
    """{file_pk: [Verwendung, …]} für die übergebenen File-Objekte.

    `beim_loeschen=False` prüft den Umbenennen-Fall: dort brechen nur die
    Wiki-Links, und zwar unabhängig davon, in wie vielen Ordnern die Datei
    liegt (der Name ändert sich überall)."""
    from .dateiablage import verknuepfte_dateien

    dateien = list(dateien)
    if not dateien:
        return {}

    wiki = wiki_verwendungen({d.original_filename or d.name for d in dateien}, user)
    ergebnis = {}
    for datei in dateien:
        eintraege = []
        name = datei.original_filename or datei.name
        # Beim Löschen bricht der Wiki-Link nur, wenn kein anderes Vorkommen
        # der Datei stehen bleibt, auf das der Name weiter zeigen kann.
        letzte = (
            not verknuepfte_dateien(datei, inklusive_selbst=False).exists()
            if beim_loeschen
            else True
        )
        if letzte:
            eintraege.extend(wiki.get(name, []))
        if beim_loeschen:
            eintraege.extend(pk_verwendungen(datei))
        if eintraege:
            ergebnis[datei.pk] = eintraege
    return ergebnis
