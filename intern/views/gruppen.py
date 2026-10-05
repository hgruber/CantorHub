import json

from django.contrib.auth.models import Group, Permission
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import render

from ..models import ChangeLog, User
from ._decorators import perm_or_home

__all__ = ["gruppen"]

PERMISSION_DEFS = [
    # Mitglieder
    ("intern.add_user",                    "anlegen",        "Mitglieder"),
    ("intern.change_user",                 "bearbeiten",     "Mitglieder"),
    ("intern.delete_user",                 "löschen",        "Mitglieder"),
    ("intern.manage_user_permissions",     "Berechtigungen", "Mitglieder"),
    ("intern.notify_user",                 "benachrichtigen","Mitglieder"),
    # Dateien
    ("intern.delete_folder",             "löschen",        "Dateien"),
    ("intern.manage_folder_permissions", "Berechtigungen", "Dateien"),
    # Termine
    ("intern.add_termin",                 "anlegen",        "Termine"),
    ("intern.change_termin",              "bearbeiten",     "Termine"),
    ("intern.delete_termin",              "löschen",        "Termine"),
    ("intern.change_zusage",              "Anwesenheit",    "Termine"),
    # Repertoire
    ("intern.add_lied",                   "anlegen",        "Repertoire"),
    ("intern.change_lied",                "bearbeiten",     "Repertoire"),
    ("intern.delete_lied",                "löschen",        "Repertoire"),
    # Aktuell (Artikel)
    ("intern.delete_artikel",             "löschen",        "Artikel"),
    ("intern.manage_artikel_permissions", "Berechtigungen", "Artikel"),
    # Forum
    ("intern.add_forum",                  "anlegen",        "Forum"),
    ("intern.change_forum",               "bearbeiten",     "Forum"),
    ("intern.delete_forum",               "löschen",        "Forum"),
    ("intern.manage_forum_permissions",   "Zugriff",        "Forum"),
    ("intern.view_forum_archiv",          "Archiv",         "Forum"),
    # Orte
    ("intern.add_ort",                    "anlegen",        "Orte"),
    ("intern.change_ort",                 "bearbeiten",     "Orte"),
    ("intern.delete_ort",                 "löschen",        "Orte"),
]

PERMISSION_DESCRIPTIONS = {
    "intern.delete_artikel":
        "Darf Artikel (Neuigkeiten) dauerhaft löschen. "
        "Achtung: Artikel sind versioniert – das Löschen entfernt alle "
        "Versionen gleichzeitig und kann nicht rückgängig gemacht werden.",
    "intern.manage_artikel_permissions":
        "Darf festlegen, welche Gruppen bestimmte Artikel lesen oder "
        "bearbeiten dürfen. Ohne diese Berechtigung sind Artikel für alle "
        "angemeldeten Mitglieder sichtbar.",
    "intern.add_forum":
        "Darf neue Diskussionsthemen (Foren) anlegen.",
    "intern.change_forum":
        "Darf bestehende Foren bearbeiten – z. B. Titel ändern, das "
        "Titelbild anpassen oder (sofern XMPP konfiguriert ist) den "
        "verknüpften Chat-Raum verwalten.",
    "intern.delete_forum":
        "Darf Foren dauerhaft löschen. Achtung: Dabei werden auch alle "
        "darin enthaltenen Nachrichten unwiederbringlich entfernt.",
    "intern.manage_forum_permissions":
        "Darf festlegen, welche Gruppen ein Forum lesen dürfen. Ohne "
        "Einschränkung ist jedes Forum für alle angemeldeten Mitglieder "
        "sichtbar. Bei eingeschränkten Foren wird auch der verknüpfte "
        "Chat-Raum entsprechend synchronisiert.",
    "intern.view_forum_archiv":
        "Darf deaktivierte (archivierte) Foren sehen, lesen und wieder "
        "aktivieren. Ohne dieses Recht ist ein archiviertes Forum für "
        "niemanden sichtbar – auch nicht für Administratoren. Archivieren "
        "selbst darf jeder mit dem Recht „Forum bearbeiten“.",
    "intern.add_termin":
        "Darf neue Termine eintragen.",
    "intern.change_termin":
        "Darf bestehende Termine bearbeiten – z. B. Datum, Uhrzeit, Ort "
        "oder Beschreibung anpassen.",
    "intern.delete_termin":
        "Darf Termine dauerhaft löschen.",
    "intern.change_zusage":
        "Darf die Anwesenheit anderer Mitglieder eintragen oder ändern. "
        "Hinweis: Jedes Mitglied kann seine eigene Anwesenheit immer selbst "
        "angeben – diese Berechtigung gilt nur für die Einträge anderer.",
    "intern.add_lied":
        "Darf neue Lieder ins Repertoire aufnehmen.",
    "intern.change_lied":
        "Darf bestehende Lieder im Repertoire bearbeiten.",
    "intern.delete_lied":
        "Darf Lieder dauerhaft aus dem Repertoire entfernen.",
    "intern.add_user":
        "Darf neue Mitglieder anlegen.",
    "intern.change_user":
        "Darf Mitgliedsdaten bearbeiten – z. B. Name, E-Mail-Adresse, "
        "Stimmgruppe oder Anschrift ändern.",
    "intern.delete_user":
        "Darf Mitgliedskonten dauerhaft löschen.",
    "intern.manage_user_permissions":
        "Darf Gruppenberechtigungen verwalten – also diese Seite aufrufen "
        "und Berechtigungen vergeben oder entziehen. "
        "Achtung: Diese Berechtigung sollte nur an sehr vertrauenswürdige "
        "Personen vergeben werden, da sie alle weiteren Berechtigungen "
        "einschließt.",
    "intern.notify_user":
        "Darf Mitglieder direkt aus der Mitgliederliste heraus per E-Mail "
        "benachrichtigen. Die Empfänger ergeben sich aus dem aktiven Filter.",
    "intern.add_ort":
        "Darf neue Orte (Veranstaltungsorte, Proberäume) anlegen.",
    "intern.change_ort":
        "Darf bestehende Orte bearbeiten.",
    "intern.delete_ort":
        "Darf Orte dauerhaft löschen.",
    "intern.delete_folder":
        "Darf Dateiordner dauerhaft löschen.",
    "intern.manage_folder_permissions":
        "Darf festlegen, welche Gruppen auf bestimmte Dateiordner zugreifen "
        "dürfen. Ohne diese Berechtigung gelten die Standard-Zugriffsregeln "
        "des jeweiligen Ordners.",
}

# Hilfe beim Klick auf einen Spaltenkopf: wo ein Recht im Portal wirkt, in Worten
# für Verwaltende. Ein drittes Element nennt das Recht, ohne das die Stelle nicht
# erreichbar ist. docs/permissions.md ist dieselbe Liste für Entwickler — eine
# Änderung an einer Abfrage gehört in beide.
PERMISSION_DETAILS = {
    "intern.add_user": [
        ("Mitgliederliste",
         "Zeigt den Knopf „+“ mit dem Einladungs-Panel: Eine neue Person bekommt per "
         "E-Mail einen Link zum Mitgliedsantrag."),
        ("Mitgliederliste › manuell anlegen",
         "Ein Konto direkt anlegen, ohne Einladung und ohne Antrag.",
         "intern.manage_user_permissions"),
    ],
    "intern.change_user": [
        ("Mitgliederliste",
         "Zeigt auch Konten ohne Portalzugang, etwa beendete Mitgliedschaften oder "
         "Fördermitglieder; ohne dieses Recht erscheinen nur Personen mit Zugang. Das "
         "gilt ebenso für die E-Mail-Liste und die Empfänger beim Benachrichtigen."),
        ("Profil einer Person",
         "Bearbeiten-Knopf und Änderungsverlauf bei anderen Personen. Das eigene Profil "
         "kann jede Person immer selbst bearbeiten."),
        ("Mitglied bearbeiten",
         "Name, Anschrift, Stimme, E-Mail und die weiteren Angaben anderer Personen "
         "ändern und einen Mitgliedsantrag mit „Mitgliedschaft genehmigen“ annehmen."),
        ("Verborgene Angaben",
         "Angaben, die eine Person für andere verborgen hat (etwa Telefon oder "
         "Anschrift), bleiben im Portal sichtbar. Im Adressbuch und Kalender auf dem "
         "Handy bleiben sie trotzdem verborgen."),
        ("Karte",
         "Zeigt auch Personen, die ihre Anschrift verborgen haben."),
        ("Profilbilder",
         "Das Profilbild einer anderen Person ersetzen."),
        ("E-Mail bei neuem Antrag",
         "Bekommt eine Nachricht, sobald ein neuer Mitgliedsantrag eingeht."),
        ("Mitgliedschaft beenden oder wieder aufnehmen, Zugang sperren",
         "Auf der Seite „Mitglied bearbeiten“ — mehr dazu unter „Mitglieder "
         "Berechtigungen“.",
         "intern.manage_user_permissions"),
    ],
    "intern.delete_user": [
        ("Mitglied bearbeiten",
         "Zeigt „Mitglied löschen“ und löscht das Konto endgültig. Das eigene Konto "
         "lässt sich so nicht löschen."),
    ],
    "intern.manage_user_permissions": [
        ("Gruppen",
         "Diese Seite: Rechte an Gruppen vergeben und entziehen, Gruppen anlegen und "
         "löschen. Wer das darf, kann sich jedes andere Recht selbst geben."),
        ("Aufgaben",
         "Personen den Gruppen zuordnen — darüber erhalten sie deren Rechte."),
        ("Änderungsprotokoll",
         "Einsicht in das Protokoll aller Änderungen im Portal."),
        ("Versionshinweise",
         "Der Versionslink unten in der Seitenleiste und die Seite mit den Neuerungen "
         "jeder Version."),
        ("Seitenleiste",
         "Das Menü „Admin“ mit Aufgaben, Gruppen und Änderungsprotokoll."),
        ("Mitgliedschaft beenden oder wieder aufnehmen",
         "Auf der Seite „Mitglied bearbeiten“: eine Mitgliedschaft beenden (Tag "
         "„Mitglied“ und Zugang werden entfernt) oder wieder aufnehmen.",
         "intern.change_user"),
        ("Zugang sperren oder freischalten",
         "Für Konten ohne Tag „Mitglied“, etwa Chorleitung oder Gäste: nur die "
         "Anmeldung ein- oder ausschalten.",
         "intern.change_user"),
        ("Mitgliederliste › manuell anlegen",
         "Ein Konto direkt anlegen, ohne Einladung und ohne Antrag.",
         "intern.add_user"),
    ],
    "intern.notify_user": [
        ("Mitgliederliste",
         "Zeigt den Knopf zum Benachrichtigen."),
        ("Benachrichtigen",
         "Eine E-Mail an alle Personen schreiben, die der aktuelle Filter der "
         "Mitgliederliste zeigt, auf Wunsch mit Dateien aus dem Ordner „Verein“ als "
         "Anhang."),
    ],
    "intern.delete_folder": [
        ("Ordner",
         "In jedem Ordner Dateien und Unterordner löschen — auch dort, wo die "
         "Ordnerrechte das sonst nicht erlauben. Ohne dieses Recht entscheiden allein "
         "die Ordnerrechte."),
    ],
    "intern.manage_folder_permissions": [
        ("Ordner",
         "Der Knopf „Berechtigungen“ in jedem Ordner: festlegen, welche Gruppen einen "
         "Ordner sehen, darin hochladen und löschen dürfen."),
        ("Oberste Ordnerebene",
         "Zeigt den Ordner „Backstage“, in dem das Portal seine eigenen Dateien ablegt. "
         "Für alle anderen ist er nur ausgeblendet; die Dateien bleiben überall "
         "erreichbar, wo sie verwendet werden."),
    ],
    "intern.add_termin": [
        ("Terminliste und Kalender",
         "Zeigt den Knopf „+“ und das Formular für einen neuen Termin."),
    ],
    "intern.change_termin": [
        ("Termin",
         "Bearbeiten-Knopf und Änderungsverlauf eines Termins."),
        ("Termin bearbeiten",
         "Datum, Uhrzeit, Ort, Beschreibung und Ankündigungstext ändern."),
    ],
    "intern.delete_termin": [
        ("Termin bearbeiten",
         "Zeigt „Termin löschen“ und löscht den Termin endgültig."),
    ],
    "intern.change_zusage": [
        ("Termin › Anwesenheit",
         "Schaltet die Anwesenheitstabelle in den Bearbeitungsmodus: Zu- und Absagen "
         "anderer Personen eintragen oder ändern. Die eigene Antwort kann jede Person "
         "immer selbst geben."),
    ],
    "intern.add_lied": [
        ("Repertoire",
         "Zeigt den Knopf „+“ und nimmt neue Lieder auf."),
    ],
    "intern.change_lied": [
        ("Lied",
         "Bearbeiten-Knopf und Änderungsverlauf eines Liedes."),
        ("Lied bearbeiten",
         "Titel, Angaben und zugeordnete Dateien eines Liedes ändern."),
        ("Ablauf eines Termins",
         "Im Repertoire, gefiltert auf einen Termin: die Reihenfolge der Lieder "
         "festlegen."),
        ("Hochladen",
         "Eine hochgeladene Datei direkt einem Lied zuordnen, etwa beim Ablegen auf der "
         "Seite des Liedes."),
    ],
    "intern.delete_lied": [
        ("Lied bearbeiten",
         "Zeigt „Lied löschen“ und entfernt das Lied endgültig aus dem Repertoire."),
    ],
    "intern.delete_artikel": [
        ("Artikel",
         "Zeigt „Löschen“ und entfernt einen Artikel mit allen Versionen; das lässt "
         "sich nicht rückgängig machen."),
    ],
    "intern.manage_artikel_permissions": [
        ("Artikel",
         "Der Knopf „Berechtigungen“: festlegen, welche Gruppen einen Artikel lesen und "
         "bearbeiten dürfen."),
        ("Artikelliste",
         "Listet auch Artikel, deren Lesen auf andere Gruppen beschränkt ist. Öffnen "
         "lassen sie sich nur mit einer passenden Gruppe."),
    ],
    "intern.add_forum": [
        ("Foren",
         "Zeigt den Knopf „+“ und legt neue Foren an."),
    ],
    "intern.change_forum": [
        ("Forum",
         "Bearbeiten-Knopf und Änderungsverlauf eines Forums."),
        ("Forum bearbeiten",
         "Titel und Titelbild ändern und — wenn ein Chat-Server angebunden ist — den "
         "verknüpften Chat-Raum verwalten und Personen dorthin einladen."),
        ("Forum deaktivieren",
         "Ein Forum archivieren. Danach sehen es nur noch Personen mit dem Recht "
         "„Forum Archiv“."),
    ],
    "intern.delete_forum": [
        ("Forum bearbeiten",
         "Zeigt „Forum löschen“ und löscht das Forum mit allen Beiträgen."),
    ],
    "intern.manage_forum_permissions": [
        ("Forum",
         "Der Knopf „Zugriff“: festlegen, welche Gruppen ein Forum lesen dürfen; der "
         "verknüpfte Chat-Raum folgt dieser Einstellung."),
        ("Foren, Ungelesen-Markierung und Benachrichtigungen",
         "Liest auch Foren, die auf andere Gruppen beschränkt sind, und sieht deren "
         "neue Beiträge."),
    ],
    "intern.view_forum_archiv": [
        ("Foren",
         "Zeigt archivierte Foren und öffnet sie zum Lesen. Ohne dieses Recht sieht sie "
         "niemand — auch Admins nicht, solange sie es nicht ausdrücklich haben."),
        ("Forum bearbeiten",
         "Bei einem archivierten Forum erscheint „Reaktivieren“ statt „Forum "
         "deaktivieren“.",
         "intern.change_forum"),
    ],
    "intern.add_ort": [
        ("Orte",
         "Zeigt den Knopf „+“ und legt neue Orte an."),
        ("Karte",
         "Einen neuen Ort direkt auf der Karte setzen."),
    ],
    "intern.change_ort": [
        ("Ort",
         "Bearbeiten-Knopf und Änderungsverlauf eines Ortes."),
        ("Ort bearbeiten",
         "Name, Anschrift und Position ändern — auch über die Karte."),
    ],
    "intern.delete_ort": [
        ("Ort bearbeiten",
         "Zeigt „Ort löschen“ und löscht den Ort endgültig, auch über die Karte."),
    ],
}

# Human-readable label for each permission string, e.g. "intern.add_artikel" → "Artikel anlegen"
_PERM_LABELS = {
    perm_str: f"{category} {label}"
    for perm_str, label, category in PERMISSION_DEFS
}

# Das eine Recht, das Admins nicht automatisch haben — darf_forum_archiv() liest es
# ausdrücklich aus der Rechtetabelle.
_OHNE_ADMIN = {"intern.view_forum_archiv"}


def rechte_inhaber(perm_strs, gruppen_rechte, gruppen_mitglieder, direkt, admins):
    """Je Recht, wer es hat — zusammengefasst nach der Quelle.

    gruppen_rechte: {gruppe: set(perm_str)} in Anzeigereihenfolge;
    gruppen_mitglieder: {gruppe: [name]}; direkt: {perm_str: [name]} (am Konto
    statt über eine Gruppe vergeben); admins: [name].
    Ergebnis: {perm_str: [{"quelle": …, "namen": [...]}]} — erst die Gruppen, die
    das Recht tragen (auch ohne Personen), dann „Direkt zugewiesen“, dann „Admin“.
    """
    ergebnis = {}
    for perm in perm_strs:
        quellen = [
            {"quelle": gruppe, "namen": gruppen_mitglieder.get(gruppe, [])}
            for gruppe, rechte in gruppen_rechte.items()
            if perm in rechte
        ]
        if direkt.get(perm):
            quellen.append({"quelle": "Direkt zugewiesen", "namen": direkt[perm]})
        if admins and perm not in _OHNE_ADMIN:
            quellen.append({"quelle": "Admin", "namen": admins})
        ergebnis[perm] = quellen
    return ergebnis


@perm_or_home("intern.manage_user_permissions")
def gruppen(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

        # Create new group
        new_name = (data.get("new_group") or "").strip()
        if new_name:
            group, created = Group.objects.get_or_create(name=new_name)
            initial_perm_labels = []
            for perm_str in data.get("new_group_perms", []):
                try:
                    app_label, codename = perm_str.split(".", 1)
                    perm = Permission.objects.get(
                        content_type__app_label=app_label,
                        codename=codename,
                    )
                    group.permissions.add(perm)
                    initial_perm_labels.append(_PERM_LABELS.get(perm_str, perm_str))
                except Exception:
                    pass
            if created:
                try:
                    changes = {"name": [None, group.name]}
                    if initial_perm_labels:
                        changes["berechtigungen"] = [None, ", ".join(initial_perm_labels)]
                    ChangeLog.objects.create(
                        user=request.user,
                        action=ChangeLog.ACTION_CREATE,
                        model_name="Group",
                        object_id=group.pk,
                        object_repr=group.name,
                        changes=changes,
                    )
                except Exception:
                    pass

        # Delete group (only if no users are assigned)
        del_name = (data.get("delete_group") or "").strip()
        if del_name:
            try:
                g = Group.objects.get(name=del_name)
                if not g.user_set.exists():
                    g_pk, g_name = g.pk, g.name
                    g.delete()
                    try:
                        ChangeLog.objects.create(
                            user=request.user,
                            action=ChangeLog.ACTION_DELETE,
                            model_name="Group",
                            object_id=g_pk,
                            object_repr=g_name,
                            changes={"name": [g_name, None]},
                        )
                    except Exception:
                        pass
            except Group.DoesNotExist:
                pass

        # Toggle group permissions
        for change in data.get("changes", []):
            try:
                group = Group.objects.get(name=change["group"])
                perm_str = change["permission"]
                app_label, codename = perm_str.split(".", 1)
                perm = Permission.objects.get(
                    content_type__app_label=app_label,
                    codename=codename,
                )
                if change["granted"]:
                    group.permissions.add(perm)
                else:
                    group.permissions.remove(perm)
                try:
                    perm_label = _PERM_LABELS.get(perm_str, perm_str)
                    ChangeLog.objects.create(
                        user=request.user,
                        action=ChangeLog.ACTION_UPDATE,
                        model_name="Group",
                        object_id=group.pk,
                        object_repr=group.name,
                        changes={"berechtigung": [None, perm_label] if change["granted"] else [perm_label, None]},
                    )
                except Exception:
                    pass
            except Exception:
                pass

        return JsonResponse({"ok": True})

    all_groups = list(
        Group.objects.annotate(mitglieder_anzahl=Count("user"))
        .order_by("id")
        .prefetch_related("permissions__content_type")
    )

    # Build permission matrix: {group_name: [perm_strings]}
    matrix = {
        g.name: [
            f"{p.content_type.app_label}.{p.codename}"
            for p in g.permissions.all()
        ]
        for g in all_groups
    }

    # Build category structure for template header (same as berechtigungen)
    cat_order: list[str] = []
    cat_map: dict[str, list] = {}
    for perm_str, label, category in PERMISSION_DEFS:
        if category not in cat_map:
            cat_map[category] = []
            cat_order.append(category)
        cat_map[category].append({
            "key": perm_str,
            "label": label,
            "description": PERMISSION_DESCRIPTIONS.get(perm_str, ""),
        })
    categories = [{"name": c, "perms": cat_map[c]} for c in cat_order]

    # User count per group to guard the delete button. Kommt aus der Annotation
    # oben — sonst eine COUNT-Abfrage je Gruppe hier und drei weitere je Zeile im
    # Template. Bleibt im Kontext: gruppen.html reicht das Dict per json_script
    # ans JavaScript weiter.
    group_user_counts = {g.name: g.mitglieder_anzahl for g in all_groups}

    group_members = {
        g.name: [
            f"{u.first_name} {u.last_name}".strip() or u.username
            for u in g.user_set.order_by("first_name", "last_name")
        ]
        for g in all_groups
    }

    # Hilfe-Dialog je Spaltenkopf: wo das Recht wirkt und wer es hat. Gezählt
    # werden nur Konten mit Portalzugang — ohne Anmeldung nützt kein Recht.
    aktive = list(
        User.objects.filter(is_active=True)
        .order_by("first_name", "last_name")
        .prefetch_related("groups", "user_permissions__content_type")
    )
    aktive_mitglieder = {g.name: [] for g in all_groups}
    direkt: dict[str, list] = {}
    for u in aktive:
        name = f"{u.first_name} {u.last_name}".strip() or u.username
        for g in u.groups.all():
            aktive_mitglieder.setdefault(g.name, []).append(name)
        for p in u.user_permissions.all():
            direkt.setdefault(f"{p.content_type.app_label}.{p.codename}", []).append(name)
    admins = [
        f"{u.first_name} {u.last_name}".strip() or u.username
        for u in aktive if u.is_superuser
    ]
    inhaber = rechte_inhaber(
        [perm_str for perm_str, _, _ in PERMISSION_DEFS],
        {name: set(rechte) for name, rechte in matrix.items()},
        aktive_mitglieder, direkt, admins,
    )
    perm_hilfe = {
        perm_str: {
            "titel": f"{category} · {label}",
            "beschreibung": PERMISSION_DESCRIPTIONS.get(perm_str, ""),
            "stellen": [
                {
                    "ort": eintrag[0],
                    "text": eintrag[1],
                    "mit": _PERM_LABELS.get(eintrag[2], eintrag[2]) if len(eintrag) > 2 else "",
                }
                for eintrag in PERMISSION_DETAILS.get(perm_str, [])
            ],
            "inhaber": inhaber[perm_str],
        }
        for perm_str, label, category in PERMISSION_DEFS
    }

    return render(request, "gruppen.html", {
        "seitentitel": "Gruppen",
        "groups": all_groups,
        "categories": categories,
        "permission_defs": PERMISSION_DEFS,
        "matrix": matrix,
        "group_user_counts": group_user_counts,
        "group_members": group_members,
        "perm_hilfe": perm_hilfe,
    })
