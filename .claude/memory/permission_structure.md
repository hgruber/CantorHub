---
name: permission-structure
description: "Vollständige Dokumentation der Berechtigungsstruktur in CantorHub — Modell, Gruppen, GUI, Lücken und Handhabungsregeln"
metadata: 
  node_type: memory
  type: project
  originSessionId: 56ad1070-c8ab-423d-a547-2ffcda91915b
---

# Berechtigungsstruktur CantorHub

## Überblick

CantorHub verwendet drei Schichten für Zugriffskontrollen:

1. **Django-Standardberechtigungen** (add/change/delete/view pro Modell)
2. **Eigene Modell-Permissions** (z. B. `manage_artikel_permissions`)
3. **ArtikelPermission-Modell** — separates, gruppenbasiertes Lese/Schreib-System für einzelne Artikel

---

## 1. Django User-Flags

| Flag | Bedeutung |
|---|---|
| `is_active` | Darf sich der User einloggen (nicht `is_staff`!) |
| `is_staff` | Zugang zum Django-Admin `/admin/` |
| `is_superuser` | Umgeht alle Berechtigungsprüfungen |

Superuser-Checks sind in vielen Views als Fallback hart kodiert (z. B. `mitglieder.py`, `artikel.py`, `gruppen.py`).

---

## 2. Gruppen und ihre Berechtigungen

Definiert in `intern/migrations/0003_import.py` → `GROUPS`-Dict. Wird einmalig beim `./migrate.sh` angelegt.

### Aktuelle Gruppen (Stand nach letzter Korrektur)

| Gruppe | Zweck | Zugewiesene Permissions |
|---|---|---|
| **Vorstand** | Breit — Mitglieder, Termine, Orte, Dateien, Artikel | add/change/delete_user, add/change/delete_artikel, manage_artikel_permissions, add/change/delete_termin, add/change/delete_ort, filer: add/change/delete_folder + add/change/delete_file |
| **Webmaster** | Datei- und Artikelverwaltung | filer: add/change/delete_folder + add/change/delete_file, add/change_artikel |
| **Termine** | Terminverwaltung | add/change/delete_termin, add/change/delete_ort |
| **Repertoire** | Liedverwaltung | add/change/delete_lied |
| **Anwesenheit** | Anwesenheitslisten | change_zusage |

### Wichtige Korrekturen (bereits durchgeführt)
- `add_mitglied / change_mitglied / delete_mitglied` existieren nicht — richtige Codenames sind `add_user / change_user / delete_user`
- Vorstand hatte fälschlicherweise `change_lied` (Repertoire-Zugriff) → entfernt
- `manage_artikel_permissions` und `delete_artikel` wurden zu Vorstand hinzugefügt

---

## 3. Berechtigungen in der GUI verwalten — zwei Views

### 3a. `/intern/gruppen/` — Gruppenmatrix

Datei: `intern/views/gruppen.py`

Zeigt alle Gruppen als Zeilen, alle definierten Permissions als Spalten. Erlaubt Toggle per Klick. Nur Superuser haben Zugang.

**Kern: `PERMISSION_DEFS`** — eine geordnete Liste von `(permission_string, Label, Kategorie)`:

```
("intern.delete_artikel",             "löschen",        "Artikel"),
("intern.manage_artikel_permissions", "Berechtigungen", "Artikel"),
("intern.add_forum",      "anlegen",  "Forum"),
("intern.change_forum",   "bearbeiten","Forum"),
("intern.delete_forum",   "löschen",  "Forum"),
("filer.add_folder",  "anlegen",    "Dateien"),
("filer.change_folder","bearbeiten","Dateien"),
("filer.delete_folder","löschen",  "Dateien"),
("intern.add_ort",    "anlegen",   "Orte"),
("intern.change_ort", "bearbeiten","Orte"),
("intern.delete_ort", "löschen",  "Orte"),
("intern.add_termin",    "anlegen",   "Termine"),
("intern.change_termin", "bearbeiten","Termine"),
("intern.delete_termin", "löschen",  "Termine"),
("intern.change_zusage", "Anwesenheit","Termine"),
("intern.add_lied",    "anlegen",   "Repertoire"),
("intern.change_lied", "bearbeiten","Repertoire"),
("intern.delete_lied", "löschen",  "Repertoire"),
("intern.add_user",    "anlegen",   "Mitglieder"),
("intern.change_user", "bearbeiten","Mitglieder"),
("intern.delete_user", "löschen",  "Mitglieder"),
```

⚠️ **Nur Permissions, die hier stehen, sind in der GUI sichtbar und togglebar.**

### 3b. `/intern/berechtigungen/<id>/` — Artikel-Berechtigungen

Datei: `intern/views/berechtigungen.py` + `intern/views/artikel.py`

Verwaltet, welche Gruppen einen **bestimmten Artikel** lesen oder bearbeiten dürfen. Verwendet das `ArtikelPermission`-Modell (nicht Django-Permissions). Zugang: `manage_artikel_permissions` oder Superuser.

---

## 4. Vollständige Permission-Enforcement-Übersicht

| Permission | Zugewiesen an | View enforced | Methode |
|---|---|---|---|
| `intern.delete_artikel` | Vorstand | artikel.py:180,379 | `has_perm` + `is_superuser` |
| `intern.manage_artikel_permissions` | Vorstand | artikel.py:181,324 | `has_perm` + `is_superuser` |
| `intern.add_artikel` | Vorstand, Webmaster | ❌ nicht geprüft | — |
| `intern.change_artikel` | Vorstand, Webmaster | ❌ (ArtikelPermission stattdessen) | — |
| `intern.add_forum` | Vorstand | forums.py:122 | `@permission_required` |
| `intern.change_forum` | Vorstand | `forum_edit` + `forum_invite` | `@permission_required` |
| `intern.delete_forum` | Vorstand | `forum_delete` | `@permission_required` |
| `filer.add_folder` | Vorstand, Webmaster | folders.py — alle Ordner-Ops | `@permission_required` |
| `filer.change_folder` | Vorstand, Webmaster | ❌ nicht geprüft | — |
| `filer.delete_folder` | Vorstand, Webmaster | ❌ nicht geprüft | — |
| `filer.add_file` | Vorstand, Webmaster | files.py:189 | `has_perm` |
| `filer.change_file` | Vorstand, Webmaster | ❌ nicht geprüft | — |
| `filer.delete_file` | Vorstand, Webmaster | ❌ nicht geprüft | — |
| `intern.add_ort` | Vorstand, Termine | orte.py:73 | `@permission_required` |
| `intern.change_ort` | Vorstand, Termine | orte.py:91 + history | `@permission_required` |
| `intern.delete_ort` | Vorstand, Termine | ⚠️ kein dedizierter View | — |
| `intern.add_termin` | Vorstand, Termine | termine.py:475 | `@permission_required` |
| `intern.change_termin` | Vorstand, Termine | termine.py:439 + history | `@permission_required` |
| `intern.delete_termin` | Vorstand, Termine | termine.py:466 | `@permission_required` |
| `intern.change_zusage` | Anwesenheit | termine.py:388 + Template | `@permission_required` + `{% if perms %}` |
| `intern.add_lied` | Repertoire | titel.py:320 | `@permission_required` |
| `intern.change_lied` | Repertoire | titel.py:202,272 + Template | `@permission_required` + `{% if perms %}` |
| `intern.delete_lied` | Repertoire | titel.py:263 | `@permission_required` |
| `intern.add_user` | Vorstand | mitglieder.py:265 | `@permission_required` |
| `intern.change_user` | Vorstand | mitglieder.py:136 + karte.py + history | `has_perm` + `is_superuser` |
| `intern.delete_user` | Vorstand | ❌ kein View | — |

---

## 5. Bekannte Lücken und tote Permissions

(Stand Juni 2026, nach Security-Audit-Fixes)

| Problem | Permissions | Status |
|---|---|---|
| **Nicht in PERMISSION_DEFS** (GUI-blind) | `filer.add/change/delete_file`, `intern.add/change_artikel` | Aktiv in Gruppen, aber nicht togglebar im Admin |
| **Nicht im View enforced** | `add_artikel`, `change_artikel`, `filer.change_file` | Restlücken |

### Durch Security-Audit geschlossen (Juni 2026)
- `add/change/delete_forum` → Vorstand zugewiesen (0003_import GROUPS); `change_forum` enforced in `forum_edit` + `forum_invite` (forums.py); `delete_forum` war schon auf `forum_delete`
- Karte-Endpoints (`karte_ort_create`/`karte_ort_detail`) enforcen jetzt `add_ort`/`change_ort`/`delete_ort` (vorher nur login_required)
- Datei-Löschung in `folder_delete`: fremde Dateien brauchen `filer.delete_file`, eigene weiterhin nur Ordner-`can_delete`
- `delete_user` ist auf `mitglied_delete` enforced (View existiert inzwischen)
- Medien-Zugriff: nginx `/media/` per `auth_request` (Session nötig); Token-Route `/intern/datei/<id>/<token>/<name>` (HMAC via Signer, kein Ablauf) für XMPP-geteilte Dateien — siehe `intern/views/media.py`

---

## 6. Regeln für Korrekturen

### Neue Permission zu einer Gruppe hinzufügen
1. In `0003_import.py` → `GROUPS`-Dict eintragen (verwendet beim nächsten `migrate.sh`)
2. Falls noch nicht vorhanden: in `PERMISSION_DEFS` in `gruppen.py` eintragen (sonst GUI-blind)
3. Im View prüfen, ob die Permission tatsächlich enforced wird

### Neue custom Permission anlegen
1. In `intern/models.py` → `class Meta: permissions = [("codename", "Name")]` beim betreffenden Modell
2. In `PERMISSION_DEFS` (gruppen.py) eintragen
3. In `GROUPS` (0003_import.py) den gewünschten Gruppen zuweisen
4. Im View mit `has_perm("intern.codename")` oder `@permission_required(...)` enforzen

### Gruppen-Matrix nach migrate.sh prüfen
Nach jedem `./migrate.sh` die Seite `/intern/gruppen/` öffnen und visuell verifizieren, dass die Checkboxen mit dem GROUPS-Dict übereinstimmen. Insbesondere Vorstand-Zeile komplett durchprüfen.

### Codenames für User-Modell
Das User-Modell heißt in Django intern `user` (nicht `mitglied`):
- ✅ `add_user`, `change_user`, `delete_user`
- ❌ `add_mitglied`, `change_mitglied`, `delete_mitglied` (existieren nicht)

---

## 7. Dateien und ihre Rollen

| Datei | Rolle |
|---|---|
| `intern/models.py` | Custom permissions in `class Meta` |
| `intern/migrations/0003_import.py` → `GROUPS` | Initiale Gruppen-Zuweisung (einmalig beim migrate) |
| `intern/views/gruppen.py` → `PERMISSION_DEFS` | Was in der GUI sichtbar/togglebar ist |
| `intern/views/berechtigungen.py` | Artikel-spezifische Lese/Schreib-Rechte per Gruppe |
| `intern/views/artikel.py` | `_artikel_access()` — ArtikelPermission-Logik |
| `intern/templates/artikel_berechtigungen.html` | GUI für Artikel-Zugriffsrechte |
| `intern/templates/gruppen.html` | GUI für die Gruppenmatrix |

**Verwandte Memories:** [[migration-numbering-constraint]]
