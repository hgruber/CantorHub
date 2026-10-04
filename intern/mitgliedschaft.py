"""Die Vereinsmitgliedschaft und der Portalzugang an **einer** Stelle.

Zwei Achsen, die vorher in einem Feld steckten:

``is_active``
    Aktiv Mitwirkender — und damit Zugang zum Portal. Nichts weiter.

Gruppe „Mitglied"
    Die Vereinsmitgliedschaft. Sie überlebt eine ruhende Mitgliedschaft: wer pausiert,
    verliert den Zugang (``is_active=False``), bleibt aber Mitglied und trägt das Tag
    weiter. Umgekehrt gibt es Konten mit Zugang **ohne** Mitgliedschaft — das
    Chorleiter-Konto aus dem Altportal ist der Anlassfall (siehe
    ``migrations/0003_import.py``, ``deaktiviere_nicht_gruender``).

Die Gruppe „Gründer" hat damit keine Funktion mehr; sie ist nur noch ein Etikett und
darf später verschwinden. Bis dahin steuert sie allein den Import.

Die Entscheidungen stehen als reine Funktionen oben, ohne Datenbankzugriff, damit ein
``SimpleTestCase`` sie prüfen kann; die dünnen Wrapper darunter tragen die Abfragen
(dasselbe Muster wie ``lese_abmelde_token()`` / ``read_abmelde_token()`` in
``mailingliste.py``).
"""

# Die drei Gruppennamen, die der Code kennt. Persistierte Strings — ein Umbenennen
# reicht in die Datenbank jeder Installation und in ``ChangeLog.changes``.
GRUPPE_MITGLIED = "Mitglied"
GRUPPE_FOERDERMITGLIED = "Fördermitglied"
GRUPPE_GRUENDER = "Gründer"

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
