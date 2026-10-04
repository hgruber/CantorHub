"""Die Vereinsmitgliedschaft und der Portalzugang an **einer** Stelle.

Zwei Achsen, die vorher in einem Feld steckten:

``is_active``
    Aktiv Mitwirkender — und damit Zugang zum Portal. Nichts weiter.

Gruppe „Mitglied"
    Die Vereinsmitgliedschaft. „Mitgliedschaft beenden" (``beende()``) nimmt Tag und
    Zugang zusammen weg, „wieder aufnehmen" bringt beides über ``nimm_auf()`` zurück.
    Tag ohne Zugang trägt das Fördermitglied. Umgekehrt gibt es Konten mit Zugang
    **ohne** Mitgliedschaft — das
    Chorleiter-Konto aus dem Altportal ist der Anlassfall (siehe
    ``migrations/0003_import.py``, ``deaktiviere_nicht_gruender``).

Die Gruppe „Gründer" hat damit keine Funktion mehr; sie ist nur noch ein Etikett und
darf später verschwinden. Bis dahin steuert sie allein den Import.

Die Entscheidungen stehen als reine Funktionen oben, ohne Datenbankzugriff, damit ein
``SimpleTestCase`` sie prüfen kann; die dünnen Wrapper darunter tragen die Abfragen
(dasselbe Muster wie ``lese_abmelde_token()`` / ``read_abmelde_token()`` in
``mailingliste.py``).
"""

# Die Gruppennamen, die der Code kennt. Persistierte Strings — ein Umbenennen
# reicht in die Datenbank jeder Installation und in ``ChangeLog.changes``.
GRUPPE_MITGLIED = "Mitglied"
GRUPPE_FOERDERMITGLIED = "Fördermitglied"
GRUPPE_GRUENDER = "Gründer"
# Keine Einwilligung zur Veröffentlichung von Fotos. Gesetzt und entfernt allein über
# das Foto-Häkchen in Antrag und Datenschutz-Bestätigung.
GRUPPE_KEIN_BILD = "kein Bild"

# Bietet der Mitgliedsantrag die Fördermitgliedschaft an? Vorerst aus; True
# bringt Checkbox, Hinweiskarte, Dialog und PDF-Abschnitt zurück.
FOERDERMITGLIED_IM_ANTRAG = False


def ist_erstaufnahme(date_joined, ist_mitglied):
    """Ist das Einschalten von ``is_active`` die **erste** Aufnahme?

    Nur dann gehören Willkommensmail und ein Eintrittsdatum dazu. Das fehlende
    Eintrittsdatum allein genügt nicht: ein Konto ohne Mitgliedschaft (Chorleiter,
    Gast) hat nie eines bekommen und würde sonst bei jedem Wiedereinschalten als
    Neuaufnahme gelten.
    """
    return bool(ist_mitglied) and date_joined is None


def aufnahme_setzt_aktiv(ist_foerdermitglied):
    """Bringt die Aufnahme auch den Portalzugang?

    Fördermitglieder wirken nicht mit — sie werden Mitglied, bleiben aber ohne Zugang.
    """
    return not ist_foerdermitglied


def mitgliedschafts_aktion(ist_mitglied, date_joined):
    """Welche Aktion bietet „Mitglied bearbeiten" an?

    ``"beenden"`` mit Tag; ohne Tag ``"wieder_aufnehmen"``, wenn ein Eintrittsdatum
    eine frühere Aufnahme verrät, sonst ``"aufnehmen"`` (der Antrag). Die Seite
    zeigt danach genau einen Button, und die Ansicht nimmt nur diese Aktion an.
    """
    if ist_mitglied:
        return "beenden"
    if date_joined is not None:
        return "wieder_aufnehmen"
    return "aufnehmen"


def mitglied_gruppe():
    """Die Gruppe „Mitglied", notfalls neu angelegt.

    Bewusst ``get_or_create`` und nicht ``get``: fehlt die Gruppe (Installation, die
    den Import nie gesehen hat), verschluckte ein ``get`` die Mitgliedschaft
    stillschweigend.
    """
    from django.contrib.auth.models import Group

    gruppe, _ = Group.objects.get_or_create(name=GRUPPE_MITGLIED)
    return gruppe


def ist_mitglied(user):
    """Trägt ``user`` das Tag „Mitglied"?"""
    return user.groups.filter(name=GRUPPE_MITGLIED).exists()


def ist_foerdermitglied(user):
    """Trägt ``user`` das Tag „Fördermitglied"?"""
    return user.groups.filter(name=GRUPPE_FOERDERMITGLIED).exists()


def nimm_auf(user, actor=None):
    """``user`` wird Vereinsmitglied. Gibt zurück, ob der Zugang mitkam.

    Das Tag wird **vor** dem Speichern gesetzt: ``signals._send_activation_mail``
    fragt es ab, um Willkommens- von Reaktivierungsmail zu unterscheiden.
    """
    from .models import ChangeLog

    gruppe = mitglied_gruppe()
    if not user.groups.filter(pk=gruppe.pk).exists():
        user.groups.add(gruppe)
        ChangeLog.objects.create(
            user=actor,
            action=ChangeLog.ACTION_UPDATE,
            model_name="User",
            object_id=user.pk,
            object_repr=str(user),
            changes={"gruppe": [None, gruppe.name]},
        )

    aktiv = aufnahme_setzt_aktiv(ist_foerdermitglied(user))
    if aktiv and not user.is_active:
        user.is_active = True
        user._audit_user = actor
        user.save(update_fields=["is_active"])
    return aktiv


def beende(user, actor=None):
    """Die Vereinsmitgliedschaft von ``user`` endet: Tag „Mitglied" und Zugang gehen.

    Das Eintrittsdatum bleibt stehen — es kennzeichnet das ehemalige Mitglied, damit
    die Seite danach „wieder aufnehmen" statt „genehmigen" anbietet und die erneute
    Aufnahme die Reaktivierungs- statt der Willkommensmail verschickt.
    """
    from .models import ChangeLog

    gruppe = mitglied_gruppe()
    if user.groups.filter(pk=gruppe.pk).exists():
        user.groups.remove(gruppe)
        ChangeLog.objects.create(
            user=actor,
            action=ChangeLog.ACTION_UPDATE,
            model_name="User",
            object_id=user.pk,
            object_repr=str(user),
            changes={"gruppe": [gruppe.name, None]},
        )

    if user.is_active:
        user.is_active = False
        user._audit_user = actor
        user.save(update_fields=["is_active"])


def kein_bild_aus_einwilligung(einwilligung):
    """Trägt jemand nach dem Foto-Häkchen ``einwilligung`` das Tag „kein Bild"?"""
    return not einwilligung


def hat_kein_bild(user):
    """Trägt ``user`` das Tag „kein Bild"?"""
    return user.groups.filter(name=GRUPPE_KEIN_BILD).exists()


def setze_kein_bild(user, an, actor=None):
    """Setzt (``an``) oder entfernt das Tag „kein Bild" und protokolliert die Änderung."""
    from django.contrib.auth.models import Group

    from .models import ChangeLog

    gruppe, _ = Group.objects.get_or_create(name=GRUPPE_KEIN_BILD)
    if user.groups.filter(pk=gruppe.pk).exists() == bool(an):
        return
    if an:
        user.groups.add(gruppe)
    else:
        user.groups.remove(gruppe)
    ChangeLog.objects.create(
        user=actor,
        action=ChangeLog.ACTION_UPDATE,
        model_name="User",
        object_id=user.pk,
        object_repr=str(user),
        changes={"gruppe": [None, gruppe.name] if an else [gruppe.name, None]},
    )
