import re

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import (
    Case,
    CharField,
    Count,
    F,
    IntegerField,
    Max,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Concat, Length
from django.utils import timezone
from django.utils.html import format_html
from filer.fields.file import FilerFileField

from . import zusage
from .avatare import avatar_vorschau_url, fallback_avatar_datei
from .replacements import apply_replacements, format_datetime

# MUC-Nickname des XMPP-Brücken-Bots (muss mit ejabberd_bot.join_muc übereinstimmen).
BOT_NICK = "CantorBot"


class User(AbstractUser):
    # Override AbstractUser.date_joined: nullable so applications start with None,
    # and the signal sets it on first activation (= Eintrittsdatum).
    date_joined = models.DateTimeField(
        verbose_name="Eintrittsdatum",
        null=True,
        blank=True,
        default=None,
    )

    # --- Legacy Identity ---
    legacy_id = models.PositiveSmallIntegerField(unique=True, null=True)

    # --- Namen ---
    first_name = models.CharField(max_length=32, verbose_name="Vorname")
    # NULL nur beim Namensverweis (siehe ``NAMENSVERWEIS``); Formulare speichern "".
    last_name = models.CharField(max_length=32, null=True, verbose_name="Nachname")

    username = models.CharField(
        max_length=150,
        unique=True,
        validators=[],  # <--- Leerzeichen erlaubt
        error_messages={
            "unique": "Ein Benutzer mit diesem Namen existiert bereits.",
        },
    )

    avatar = FilerFileField(
        null=True, blank=True, on_delete=models.SET_NULL, related_name="avatar"
    )
    # --- Personendaten ---
    STIMMEN = [
        ("N", "None"),
        ("S", "Sopran"),
        ("A", "Alt"),
        ("T", "Tenor"),
        ("B", "Bass"),
        ("C", "Chorleiter"),
        ("M", "Musiker"),
    ]
    # Canonical sort order of voices (anything not listed sorts last).
    STIMME_ORDER = ["S", "A", "T", "B", "C", "M"]
    stimme = models.CharField(max_length=1, choices=STIMMEN, default="N")

    geburtstag = models.DateField(null=True, blank=True)

    # --- Adresse ---
    strasse = models.CharField(max_length=48, null=True, blank=True)
    plz = models.CharField(max_length=5, null=True, blank=True)
    ort = models.CharField(max_length=48, null=True, blank=True)
    breite = models.FloatField(null=True, blank=True)
    laenge = models.FloatField(null=True, blank=True)

    # --- Kontakt ---
    telefon = models.CharField(max_length=32, null=True, blank=True)
    telefon_job = models.CharField(max_length=32, null=True, blank=True)
    telefon_mobil = models.CharField(max_length=32, null=True, blank=True)
    telefon_job_mobil = models.CharField(max_length=32, null=True, blank=True)
    fax = models.CharField(max_length=32, null=True, blank=True)
    email = models.EmailField(max_length=48, null=True, blank=True)
    xmpp = models.CharField(max_length=255, null=True, blank=True)

    # --- Meta / Status ---
    text = models.TextField(null=True, blank=True)
    private_fields = models.JSONField(default=list, blank=True)
    # Der stärkere Bruder von private_fields: nicht einzelne Felder, sondern der
    # ganze Datensatz bleibt aus dem CardDAV-Adressbuch draussen. Partizip statt
    # Verb, weil es einen Zustand der Person beschreibt; und positiv formuliert,
    # damit zwischen Checkbox und Feld nirgends invertiert werden muss.
    adressbuch_verborgen = models.BooleanField(
        default=False,
        verbose_name="Nicht im Adressbuch",
        help_text=(
            "Andere Mitglieder können das Mitgliederverzeichnis mit dem Adressbuch "
            "ihres Telefons abgleichen. Mit diesem Haken wird Dein Eintrag dabei "
            "vollständig ausgelassen — auch Name und Stimme —, und bereits "
            "abgeglichene Geräte entfernen ihn beim nächsten Abgleich. Im Portal "
            "bleibt Dein Profil unverändert sichtbar; einzelne Felder verbirgst Du "
            "dort mit „verbergen“."
        ),
    )
    notify_enabled = models.BooleanField(default=True, verbose_name="Benachrichtigungen")

    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "Mitglied"
        verbose_name_plural = "Mitglieder"
        permissions = [
            ("manage_user_permissions", "Kann Mitglieder-Berechtigungen verwalten"),
            ("notify_user", "Kann Mitglieder per E-Mail benachrichtigen"),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name or ''}".strip()

    def get_full_name(self):
        return str(self)

    @property
    def ist_namensverweis(self):
        return self.last_name is None

    def mitteilungen(self):
        return self.mitteilung_set.count()

    def bild(self):
        if self.avatar:
            return format_html(
                '<img src="{}"></img>',
                self.avatar.thumbnails.get("admin_clipboard_icon"),
            )

    @staticmethod
    def stimme_order_case():
        """Case expression mapping each Stimme letter to its sort index.

        Use in an ORM `.annotate(...)` call when ordering members by voice:
            User.objects.annotate(_so=User.stimme_order_case()).order_by("_so", ...)
        """
        return Case(
            *[When(stimme=s, then=Value(i)) for i, s in enumerate(User.STIMME_ORDER)],
            default=Value(len(User.STIMME_ORDER)),
            output_field=IntegerField(),
        )

    @property
    def stimme_pos(self):
        """Sort index of this member's voice in the canonical STIMME_ORDER.

        Used as a column-sort accessor so Python-side table sorting (e.g.
        django-tables2 with list data) matches the SQL ordering produced by
        `stimme_order_case()`.
        """
        try:
            return User.STIMME_ORDER.index(self.stimme)
        except ValueError:
            return len(User.STIMME_ORDER)

    def field_visible_to(self, viewer, field):
        if viewer.id == self.id or viewer.has_perm("intern.change_user"):
            return True
        return field not in (self.private_fields or [])


class Artikel(models.Model):
    name = models.CharField(max_length=256)
    version = models.IntegerField()
    datum = models.DateTimeField()
    autor = models.ForeignKey("User", null=True, on_delete=models.SET_NULL)
    kommentar = models.CharField(max_length=256, blank=True, null=True)
    text = models.TextField()

    class Meta:
        unique_together = ("name", "version")
        verbose_name_plural = "Artikel"
        permissions = [
            ("manage_artikel_permissions", "Artikel-Berechtigungen bearbeiten"),
        ]

    def __str__(self):
        return self.name

    DATEI_LINK_RE = re.compile(r"\[\[Datei:([^|\]]+)(?:\|[^\]]+)?\]\]")

    @staticmethod
    def dateiname_aus_link(roh):
        """Strip whitespace and quotes around a [[Datei:…]] name, the way
        replacements.get_references does."""
        return roh.strip().strip("\"'").strip()

    @classmethod
    def aktuelle_datei_verweise(cls):
        """{dateiname: [artikelname, …]} over each article's **latest** version.

        Basis for warning that renaming or deleting a file breaks a wiki link —
        those links address a file by name (replacements.internal_links)."""
        max_id_sub = (
            Artikel.objects.filter(name=OuterRef("name"))
            .order_by("-version")
            .values("id")[:1]
        )
        qs = cls.objects.filter(
            id=Subquery(max_id_sub), text__contains="[[Datei:"
        ).only("name", "text")
        verweise = {}
        for artikel in qs:
            for roh in cls.DATEI_LINK_RE.findall(artikel.text):
                name = cls.dateiname_aus_link(roh)
                if not name:
                    continue
                artikelnamen = verweise.setdefault(name, [])
                if artikel.name not in artikelnamen:
                    artikelnamen.append(artikel.name)
        return verweise


class ArtikelPermission(models.Model):
    artikel_name = models.CharField(max_length=256)
    group = models.ForeignKey(
        "auth.Group", on_delete=models.CASCADE, related_name="artikel_permissions"
    )
    can_read = models.BooleanField(default=False)
    can_edit = models.BooleanField(default=False)

    class Meta:
        unique_together = [("artikel_name", "group")]
        verbose_name = "Artikelberechtigung"
        verbose_name_plural = "Artikelberechtigungen"

    def __str__(self):
        return f"{self.artikel_name} – {self.group}"


class FolderPermission(models.Model):
    folder = models.ForeignKey(
        "filer.Folder", on_delete=models.CASCADE, related_name="folder_permissions"
    )
    group = models.ForeignKey(
        "auth.Group", on_delete=models.CASCADE, related_name="folder_permissions"
    )
    can_read = models.BooleanField(default=False)
    can_write = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)

    class Meta:
        unique_together = [("folder", "group")]
        verbose_name = "Ordnerberechtigung"
        verbose_name_plural = "Ordnerberechtigungen"
        permissions = [
            ("manage_folder_permissions", "Kann Ordner-Berechtigungen verwalten"),
            ("delete_folder", "Kann Ordner und Dateien löschen"),
        ]

    def __str__(self):
        return f"{self.folder} – {self.group}"


def ab_stichtag(prefix="mitteilung__"):
    """Bedingung „Beitrag ab dem Stichtag ``FORUM_ANZEIGE_AB``“ für einen Join.

    ``Mitteilung.objects`` filtert selbst; ein Join über ``mitteilung`` (``Count``,
    ``Max``, ``mitteilung__…``) umgeht aber jeden Manager und braucht die Bedingung
    ausdrücklich. ``MitteilungStichtagTest`` hält die Join-Stellen fest.
    """
    from .app_settings import get_forum_anzeige_ab

    return Q(**{f"{prefix}datum__gte": get_forum_anzeige_ab()})


class MitteilungManager(models.Manager):
    """Nur Beiträge ab dem Stichtag — ältere zeigt das Portal nirgends an."""

    def get_queryset(self):
        return super().get_queryset().filter(ab_stichtag(prefix=""))


class ForumQuerySet(models.QuerySet):
    def extra_data(self):
        # Get the full name of the sender of the most recent message.
        # Nach id wie ``Forum.letzte()``, damit die Spalte denselben Beitrag meint,
        # den das Forum oben zeigt.
        last_sender_subquery = (
            Mitteilung.objects.filter(forum=OuterRef("pk"))
            .order_by("-id")
            .values(
                besitzer=Concat("sender__first_name", Value(" "), "sender__last_name")
            )[:1]
        )

        return self.select_related("bild").annotate(
            anzahl_mitteilungen=Count("mitteilung", filter=ab_stichtag()),
            zugriff=Max("mitteilung__datum", filter=ab_stichtag()),
            letzter_absender=Subquery(last_sender_subquery),
        )

    def mit_ungelesen(self, user):
        """Annotate `ungelesen`: messages from others above the user's read marker.
        A forum without a ForumGelesen row counts from 0 — see intern/forum_gelesen.py."""
        bis_id = ForumGelesen.objects.filter(forum=OuterRef("pk"), user=user).values("bis_id")[:1]
        return self.alias(
            _gelesen_bis=Coalesce(Subquery(bis_id), Value(0)),
        ).annotate(
            ungelesen=Count(
                "mitteilung",
                filter=Q(mitteilung__id__gt=F("_gelesen_bis"))
                & ab_stichtag()
                & (Q(mitteilung__sender__isnull=True) | ~Q(mitteilung__sender=user)),
            ),
        )


class Forum(models.Model):
    thema = models.CharField(max_length=120)
    bild = FilerFileField(null=True, blank=True, on_delete=models.SET_NULL, related_name="forum_bild")
    aktiv = models.BooleanField(default=True)
    xmpp_muc_jid = models.CharField(max_length=255, null=True, blank=True, unique=True)
    objects = ForumQuerySet.as_manager()

    class Meta:
        verbose_name_plural = "Foren"
        permissions = [
            ("manage_forum_permissions", "Forum-Berechtigungen bearbeiten"),
            ("view_forum_archiv", "Archivierte Foren sehen und reaktivieren"),
        ]

    def __str__(self):
        return self.thema

    def sender(self):
        mitteilung = self.mitteilung_set.order_by("-id").first()
        if mitteilung:
            return mitteilung.sender
        return None

    def letzte(self):
        return format_datetime(self.zugriff)


class Mitteilung(models.Model):
    forum = models.ForeignKey("Forum", on_delete=models.CASCADE)
    sender = models.ForeignKey("User", null=True, on_delete=models.SET_NULL)
    datum = models.DateTimeField()
    # null erlaubt, aber `formatiert()` verträgt es — siehe dort. Die Spalte auf
    # NOT NULL zu ziehen wäre der sauberere Schnitt, ließe aber `makemigrations`
    # interaktiv nachfragen (Django: „It is impossible to change a nullable field
    # to non-nullable without a default"); genau dieses `makemigrations` läuft im
    # Dockerfile und in start.sh ohne `--no-input` und bräche den Bau ab.
    mitteilung = models.TextField(blank=True, null=True)
    # unique legt den Index bereits an; ein zusätzliches db_index wäre wirkungslos.
    xmpp_stanza_id = models.CharField(
        max_length=255, null=True, blank=True, unique=True
    )
    # Set by forum_react when a web user's reaction set changed; the bot relays
    # the new web-reaction union to the MUC and clears the flag (see ejabberd_bot).
    reactions_dirty = models.BooleanField(default=False)

    # ``objects`` zuerst: der Standardmanager (auch hinter ``forum.mitteilung_set``)
    # blendet alles vor dem Stichtag aus. ``alle`` nur für technische Pfade, die
    # alte Beiträge sehen müssen — die Liste steht in ``MitteilungStichtagTest``.
    objects = MitteilungManager()
    alle = models.Manager()

    class Meta:
        verbose_name_plural = "Mitteilungen"
        # By id, not by datum: the read marker (ForumGelesen.bis_id), the divider
        # (trenner_id), the poll (forum_get: id__gt) and the paging (forum_more:
        # id__lt) all speak ids. datum is stored at second resolution and has no
        # tiebreaker, so messages sharing a second came back in an undefined order
        # — the divider landed inside that group and the visible number of new
        # messages differed from the badge by one. See docs/forum.md.
        ordering = ["-id"]

    def __str__(self):
        return f"Message from {self.sender} in forum {self.forum}"

    def formatiert(self):
        # `or ""`: die Spalte erlaubt NULL (Altdaten, Import), `apply_replacements`
        # scheitert aber an None. Der leere Text ist die richtige Anzeige dafür.
        return apply_replacements(self.mitteilung or "")

    def is_from_bot(self):
        """True, wenn diese Nachricht vom XMPP-Brücken-Bot stammt."""
        if not self.sender or not self.sender.xmpp:
            return False
        from .app_settings import get_config

        bot_jid = get_config("EJABBERD_BOT_JID", "")
        return bool(bot_jid) and self.sender.xmpp.lower() == bot_jid.lower()

    def sender_name(self):
        """Anzeigename des Absenders, robust gegen fehlende Senderdaten."""
        if self.is_from_bot():
            return BOT_NICK
        if self.sender:
            return self.sender.first_name or self.sender.get_username()
        return "Unbekannt"

    def sender_avatar_url(self):
        """Avatar-URL des Absenders mit Fallback auf bot.png bzw. kein_photo.png.

        Als Vorschaubild, nicht im Original: die Blase zeigt 38 Pixel, und jede
        Bilddatei laeuft ueber ``media_auth`` einzeln durch Django.
        """
        if self.is_from_bot():
            return avatar_vorschau_url(fallback_avatar_datei("bot.png"))
        if self.sender and self.sender.avatar:
            return avatar_vorschau_url(self.sender.avatar)
        return avatar_vorschau_url(fallback_avatar_datei("kein_photo.png"))


class ForumPermission(models.Model):
    """Read restriction for a forum. The presence of a row means the forum is
    restricted to the listed groups; no row for a forum = open to everyone.
    There is no write dimension — readers may post, non-readers don't see the
    forum at all."""

    forum = models.ForeignKey(
        "Forum", on_delete=models.CASCADE, related_name="forum_permissions"
    )
    group = models.ForeignKey(
        "auth.Group", on_delete=models.CASCADE, related_name="forum_permissions"
    )

    class Meta:
        unique_together = [("forum", "group")]
        verbose_name = "Forenberechtigung"
        verbose_name_plural = "Forenberechtigungen"

    def __str__(self):
        return f"{self.forum} → {self.group}"


class ForumGelesen(models.Model):
    """How far a member has read a forum: every message with an id up to `bis_id`.

    The message id is stored rather than a date — `forum_get` polls by `id__gt` as well,
    and the `datum` of messages relayed from XMPP is not guaranteed to be monotonic.
    Reading in an XMPP client is not recorded here."""

    user = models.ForeignKey(
        "User", on_delete=models.CASCADE, related_name="foren_gelesen"
    )
    forum = models.ForeignKey(
        "Forum", on_delete=models.CASCADE, related_name="gelesen"
    )
    bis_id = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("user", "forum")]
        verbose_name = "Forum gelesen"
        verbose_name_plural = "Foren gelesen"

    def __str__(self):
        return f"{self.user} → {self.forum} bis #{self.bis_id}"


class Reaktion(models.Model):
    """An emoji reaction (XEP-0444) on a single Mitteilung.

    Per XEP-0444 the latest reaction stanza from a reactor fully replaces that
    reactor's previous set, so uniqueness is enforced in application code via
    delete-then-insert (see views.forums / ejabberd_bot), not a DB constraint:
    the reactor identity is ``sender`` for web reactions and ``reactor_jid`` for
    XMPP ones (where ``sender`` may be None for an unmapped JID).
    """

    REACTION_EMOJIS = ["👍", "❤️", "😂", "🎉", "😮", "😢", "🙏", "👏"]

    # Der FK bringt seinen Index selbst mit; db_index wäre hier wirkungslos.
    mitteilung = models.ForeignKey(
        "Mitteilung", on_delete=models.CASCADE, related_name="reaktionen"
    )
    sender = models.ForeignKey("User", null=True, blank=True, on_delete=models.SET_NULL)
    reactor_jid = models.CharField(max_length=255, null=True, blank=True)
    emoji = models.CharField(max_length=64)
    origin = models.CharField(max_length=8, default="web")  # "web" | "xmpp"
    datum = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name_plural = "Reaktionen"

    def __str__(self):
        return f"{self.emoji} on #{self.mitteilung_id}"


class Ort(models.Model):
    name = models.CharField(max_length=48)
    beschreibung = models.TextField(blank=True, null=True)
    strasse = models.CharField(max_length=48, blank=True, null=True)
    plz = models.CharField(max_length=5, blank=True, null=True)
    ort = models.CharField(max_length=48, blank=True, null=True)
    breite = models.FloatField(blank=True, null=True)
    laenge = models.FloatField(blank=True, null=True)

    class Meta:
        verbose_name_plural = "Orte"

    def __str__(self):
        return self.name


# Kriterium für „öffentlich angekündigt": ein nicht-leerer Ankündigungstext
# (`Termin.extern`). Die Startseite listet danach (`home()` in `views/auth.py`),
# und die Auftritts-Erinnerungen verschickt danach der Daemon
# (`send_auftritt_erinnerungen`) — beide lesen diese eine Menge.
#
# Beide Leerformen zählen — die Altdaten führen 248×"" und 27×NULL —, und
# `exclude(extern="")` allein genügt nicht: Django setzt bei der Negation auf
# einer nullable-Spalte ein `IS NOT NULL` in die Bedingung
# (`NOT (extern = '' AND extern IS NOT NULL)`), ein NULL-Datensatz überlebt sie.
# Bewusst ohne `.strip()`: ein einzelnes Leerzeichen soll einen Auftritt listen,
# ohne dass ein Text erfunden wird — siehe `_STARTSEITE_OHNE_TEXT` in
# `intern/migrations/0003_import.py`. Die *Anzeige* hängt dagegen am
# Template-Filter `extern_html`, der reinen Leerraum fallen lässt.
#
# Gemessen wird die Länge, nicht der Wert, und das ist der Kern der Sache:
# MySQL/MariaDB vergleichen Zeichenketten unter den gängigen Kollationen mit
# `PAD SPACE` (hier `utf8mb4_general_ci`), dort ist `' ' = ''` **wahr**. Ein
# `Q(extern="")` hätte genau die Auftritte wieder ausgeschlossen, die das
# Leerzeichen listen soll — auf SQLite unsichtbar, weil dort `' ' <> ''` gilt.
# `CHAR_LENGTH()` zählt das Leerzeichen auf beiden Datenbanken als 1. Die
# Suite läuft ohne Datenbank, kann den Unterschied also nicht sehen:
# `AnkuendigungLeerformenTest` pinnt darum die Form der Bedingung.
models.TextField.register_lookup(Length)

OHNE_ANKUENDIGUNG = Q(extern__isnull=True) | Q(extern__length=0)

# Ein Namensverweis ist eine Person aus dem Altportal, die nur noch als Absender
# alter Forenbeiträge oder als Autor alter Artikelfassungen gebraucht wird: der
# Import legt sie mit Vornamen und ``last_name = NULL`` an. NULL statt "" — kein
# Formular schreibt NULL, und unter MariaDB (PAD SPACE) wäre "" auch " ".
# Keine Ansicht listet sie; siehe docs/members.md.
NAMENSVERWEIS = Q(last_name__isnull=True)


class Termin(models.Model):
    # db_index: fast jede Abfrage filtert oder sortiert nach dem Datum (Terminliste,
    # Kalender, CalDAV, Erinnerungsversand). Kein Meta.ordering — das würde jede
    # ungeordnete Query stillschweigend umsortieren, u. a. die Basis für
    # paginate_ordered; .order_by() steht dort bereits explizit.
    datum = models.DateTimeField(db_index=True)
    datum_bis = models.DateTimeField(blank=True, null=True)
    wiederholung = models.CharField(max_length=1, default="e")
    kurz = models.CharField(max_length=64)
    lang = models.TextField(blank=True, null=True)
    ort = models.ForeignKey("Ort", null=True, blank=True, on_delete=models.SET_NULL)
    extern = models.TextField(
        blank=True,
        null=True,
        help_text="Der öffentliche Ankündigungstext: Adresse, Einlass und Links für "
        "das Publikum. Er steht auf der öffentlichen Startseite unter „Konzerte“, "
        "auf der Terminseite in der Karte „Extern“ und löst die Erinnerungsmails "
        "der Auftritts-Mailingliste aus. Ist das Feld leer, fehlt die Karte, der "
        "Termin steht nicht auf der Startseite und die Mailingliste wird nicht "
        "erinnert. HTML ist erlaubt (Links, Zeilenumbrüche).",
    )
    ctag = models.IntegerField(default=0)
    # Die help_texts sind die einzige Quelle der Erklärungs-Tooltips:
    # das Formular erbt sie, die Anzeigeseiten holen sie über {% hilfe %}.
    repertoire = models.BooleanField(
        default=False,
        help_text="Der Termin ist ein Auftritt mit einem Ablauf: Er bekommt auf der "
        "Terminseite die Karte „Lieder“. Für die öffentliche Ankündigung auf der "
        "Startseite und die Erinnerungsmails der Auftritts-Mailingliste ist der "
        "Ankündigungstext in „Extern“ zuständig.",
    )
    anwesenheit = models.BooleanField(
        default=False,
        help_text="Die Mitglieder werden um Zu- oder Absage gebeten: Terminseite und "
        "Banner zeigen die Zusage-Schaltflächen, die Rückmeldungen werden nach Stimmen "
        "ausgewertet. Bis zur Antwort zählt der Termin in der Seitenleiste als offener "
        "Termin.",
    )
    mitglied = models.ManyToManyField("User", through="Zusage", related_name="termin")

    class Meta:
        verbose_name_plural = "Termine"

    def __str__(self):
        return self.kurz + " am " + self.datum.strftime("%d.%m.%y")


class Auftrittsabo(models.Model):
    """Eintrag in der öffentlichen Auftritts-Mailingliste (Double-Opt-in).

    Empfänger sind ausdrücklich keine Mitglieder — es gibt keinen Bezug zu User.
    Die Nachweisfelder belegen die Einwilligung nach Art. 7 Abs. 1 DSGVO: *wann*
    (`bestaetigt_am`), *von wo* (`bestaetigt_ip`) und *wozu* — der
    Einwilligungstext wird als Schnappschuss gespeichert, weil er aus der
    jederzeit editierbaren Konfigurationstabelle stammt.

    Bewusst schmal gehalten: es gibt kein eigenes `bestaetigt`-Flag (das wäre
    Redundanz zu `bestaetigt_am` und könnte dazu inkonsistent werden), keine
    Anmelde-IP (rechtlich zählt der Bestätigungsklick) und keinen gespeicherten
    Abmelde-Token — der wird signiert erzeugt, siehe `make_abmelde_token()` in
    `intern/mailingliste.py`.
    """

    email = models.EmailField(max_length=254, unique=True)
    name = models.CharField(max_length=64, blank=True)
    angemeldet_am = models.DateTimeField(auto_now_add=True)
    bestaetigt_am = models.DateTimeField(null=True, blank=True)
    optin_gesendet_am = models.DateTimeField(null=True, blank=True)
    bestaetigt_ip = models.GenericIPAddressField(null=True, blank=True)
    einwilligungstext = models.TextField(blank=True)

    class Meta:
        ordering = ["-angemeldet_am"]
        verbose_name = "Auftrittsabo"
        verbose_name_plural = "Auftrittsabos"

    def __str__(self):
        return self.email

    @property
    def bestaetigt(self):
        """Lesbare Abkürzung für Python und Templates.

        In Abfragen **nicht** verwendbar — dort `bestaetigt_am__isnull=False`
        bzw. `=True` schreiben.
        """
        return self.bestaetigt_am is not None


class ErinnerungVersand(models.Model):
    """Marker: für diesen Termin wurde die Erinnerung mit N Wochen Vorlauf verschickt.

    Der Unique-Constraint ist der einzige Schutz gegen Doppelversand durch
    parallele Prozesse (Dauerloop, manueller Aufruf, Testsystem auf derselben
    Datenbank) — es gibt kein Prozess-Lock.  Zweitfunktion: wer sich erst nach
    der Fälligkeit einträgt, bekommt die Erinnerung nicht nachgereicht.
    """

    termin = models.ForeignKey(
        "Termin", on_delete=models.CASCADE, related_name="erinnerungen"
    )
    wochen = models.PositiveSmallIntegerField()
    faellig_am = models.DateTimeField()
    versendet_am = models.DateTimeField(auto_now_add=True)
    empfaenger = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-versendet_am"]
        verbose_name = "Erinnerungsversand"
        verbose_name_plural = "Erinnerungsversand"
        constraints = [
            models.UniqueConstraint(
                fields=["termin", "wochen"], name="uniq_erinnerung_termin_wochen"
            )
        ]

    def __str__(self):
        return f"{self.termin_id} / {self.wochen} Wochen"


class Lied(models.Model):
    titel = models.CharField(max_length=48)
    aktiv = models.BooleanField(default=False)
    original = FilerFileField(
        null=True, blank=True, on_delete=models.SET_NULL, related_name="original"
    )
    aufnahme = FilerFileField(
        null=True, blank=True, on_delete=models.SET_NULL, related_name="aufnahme"
    )
    pdf = FilerFileField(
        null=True, blank=True, on_delete=models.SET_NULL, related_name="pdf"
    )
    noten = FilerFileField(
        null=True, blank=True, on_delete=models.SET_NULL, related_name="noten"
    )
    solist = models.ManyToManyField("User", related_name="solist")
    dirigent = models.ManyToManyField("User", related_name="dirigent")
    CHOICES = [("l", "l"), ("m", "m"), ("s", "s")]
    TONART_CHOICES = [
        ("A",   "A"),
        ("Ab",  "A♭"),
        ("B",   "B"),
        ("Bb",  "B♭"),
        ("C",   "C"),
        ("D",   "D"),
        ("Db",  "D♭"),
        ("E",   "E"),
        ("Eb",  "E♭"),
        ("F",   "F"),
        ("Fs",  "F♯"),
        ("G",   "G"),
        ("Am",  "Am"),
        ("Abm", "A♭m"),
        ("Bm",  "Bm"),
        ("Bbm", "B♭m"),
        ("Cm",  "Cm"),
        ("Csm", "C♯m"),
        ("Dm",  "Dm"),
        ("Ebm", "E♭m"),
        ("Em",  "Em"),
        ("Fm",  "Fm"),
        ("Fsm", "F♯m"),
        ("Gm",  "Gm"),
    ]
    tempo = models.CharField(max_length=1, choices=CHOICES, default="m")
    beats = models.SmallIntegerField(blank=True, null=True)
    tonart = models.CharField(max_length=4, choices=TONART_CHOICES, blank=True, default="")
    hymne = models.BooleanField(default=False)
    acapella = models.BooleanField(default=False)
    weihnacht = models.BooleanField(default=False)
    komponist = models.TextField(blank=True, null=True)
    bearbeiter = models.TextField(blank=True, null=True)
    termin = models.ManyToManyField("Termin", through="Konzert", related_name="termin")

    class Meta:
        verbose_name_plural = "Lieder"

    def __str__(self):
        return self.titel


class Konzert(models.Model):
    termin = models.ForeignKey("Termin", on_delete=models.CASCADE)
    # SET_NULL, nicht CASCADE: ein gelöschtes Lied soll seinen Platz im Ablauf
    # verlieren, nicht den ganzen Programmpunkt mitnehmen — dieselbe Linie wie die
    # übrigen nullbaren FKs im Projekt. on_delete erzeugt kein DDL, die Änderung
    # wirkt also sofort.
    lied = models.ForeignKey("Lied", null=True, on_delete=models.SET_NULL)
    position = models.IntegerField(default=1)

    class Meta:
        verbose_name_plural = "Konzerte"
        ordering = ["position"]

    def __str__(self):
        return f"{self.position} - {self.termin.kurz} - {self.lied}"


class Zusage(models.Model):
    person = models.ForeignKey("User", on_delete=models.CASCADE)
    termin = models.ForeignKey("Termin", on_delete=models.CASCADE)
    # choices nur zur Validierung/Formularanzeige — der Katalog liegt in
    # intern/zusage.py, weil ihn fünf Stellen lesen. max_length bleibt bei 255:
    # unter MySQL (STRICT_TRANS_TABLES) risse ein einziger Legacy-Wert außerhalb
    # der Liste den Import um, und Django schneidet nicht ab.
    option = models.CharField(
        max_length=255,
        default="1",
        choices=[(wert, zusage.OPTION_LABELS[wert]) for wert in zusage.OPTIONEN],
    )

    OPTION_LABELS = zusage.OPTION_LABELS

    class Meta:
        verbose_name_plural = "Zusagen"
        constraints = [
            # Genau eine Antwort je Mitglied und Termin. Der Constraint ist nicht
            # nur Datenhygiene: ModelForm validiert Meta.constraints, also meldet
            # das Admin-Inline eine Dublette als Formularfehler statt sie still
            # anzulegen, und update_or_create (views/termine.py) wird race-sicher,
            # weil get_or_create den IntegrityError selbst abfängt. Ohne ihn wirft
            # update_or_create bei vorhandenen Dubletten MultipleObjectsReturned.
            models.UniqueConstraint(
                fields=["person", "termin"], name="uniq_zusage_person_termin"
            )
        ]

    def __str__(self):
        label = self.OPTION_LABELS.get(self.option, self.option or "Keine Angabe")
        return f"{self.person} – {label}"


class Abstimmung(models.Model):
    """Eine Stimme in einer Wiki-Abstimmung.

    ``abstimmung`` ist der Schlüssel ``"seite:titel"`` aus der Direktive im
    Artikeltext (``intern/replacements.py``), kein FK — die Abstimmung lebt im Text,
    nicht in einer eigenen Zeile.

    Bewusst **kein** Unique-Constraint auf ``(person, abstimmung)``: eine Abstimmung
    ist mehrfach-wählbar (``max_stimmen``, ``views/abstimmung.py``). Verboten ist nur
    die doppelte *gleiche* Stimme — deshalb der Dreier-Constraint. Er trägt, weil
    die Stimmabgabe ``delete()`` + ``bulk_create()`` ist und damit nicht atomar: zwei
    gleichzeitige POSTs könnten dieselbe Option sonst zweimal einfügen, und die
    Auswertung zählte sie doppelt.
    """

    person = models.ForeignKey("User", on_delete=models.CASCADE)
    abstimmung = models.CharField(max_length=256)
    option = models.CharField(max_length=256)

    class Meta:
        verbose_name_plural = "Abstimmungen"
        constraints = [
            models.UniqueConstraint(
                fields=["person", "abstimmung", "option"],
                name="uniq_abstimmung_person_abstimmung_option",
            )
        ]
        indexes = [
            # Für das Filter in views/abstimmung.py und die Auswertung in
            # replacements.py (values("option").annotate(Count)).
            models.Index(fields=["abstimmung", "person"]),
        ]


class Standort(models.Model):
    """Live location shared voluntarily by a member."""
    person = models.OneToOneField("User", on_delete=models.CASCADE)
    breite = models.FloatField()
    laenge = models.FloatField()
    aktualisiert = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Standorte"

    def __str__(self):
        return f"{self.person} ({self.breite:.4f}, {self.laenge:.4f})"


class TabellenPreferenzen(models.Model):
    """Sichtbare Spalten einer Tabelle je Mitglied.

    ``person=None`` ist **kein** verwaister Wert, sondern die globale Vorgabezeile,
    auf die zurückgefallen wird, wenn ein Mitglied nichts eigenes gesetzt hat
    (``views/files.py``). Der ``unique_together`` schützt nur die Mitgliedszeilen:
    auf MySQL und SQLite gelten NULLs im Unique-Index als verschieden, eine zweite
    Vorgabezeile für dieselbe Tabelle wäre also möglich. Django kann das nur auf
    PostgreSQL über ``UniqueConstraint(nulls_distinct=False)`` ändern und wirft auf
    den anderen Backends. Deshalb liest ``views/files.py`` bewusst mit ``first()``
    statt ``get()`` — siehe „Data model" in `docs/technical-debt.md`.
    """

    person = models.ForeignKey("User", on_delete=models.CASCADE, null=True)
    tabelle = models.CharField(max_length=100)
    sichtbare_spalten = models.JSONField(default=list)

    class Meta:
        unique_together = (
            "person",
            "tabelle",
        )


class Konfiguration(models.Model):
    key = models.CharField(max_length=64, unique=True, verbose_name="Schlüssel")
    value = models.TextField(blank=True, verbose_name="Wert")
    description = models.CharField(max_length=256, blank=True, verbose_name="Beschreibung")

    class Meta:
        verbose_name = "Konfiguration"
        verbose_name_plural = "Konfigurationen"
        ordering = ["key"]

    def __str__(self):
        return self.key


class DateiIndex(models.Model):
    """Extracted text content of a filer File, for content search in the folder
    browser. Populated lazily by intern.fileindex; file_size is used to detect
    when the underlying file changed and the row is stale."""

    file = models.OneToOneField(
        "filer.File", on_delete=models.CASCADE, related_name="suchindex"
    )
    text = models.TextField(blank=True)
    file_size = models.BigIntegerField(default=0)
    indexed_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "DateiIndizes"


class DateiVersion(models.Model):
    """A superseded revision of a file, kept when an upload overwrites it.

    The old blob is neither copied nor deleted — it stays where it is and this
    row records its path. A file's identity is its storage path (`File.file`),
    the same rule filer uses in `File.delete()` to decide whether a blob may go,
    so several File rows sharing a path are one file in several folders. When a
    new revision is stored under a fresh path, every row of the chain is moved
    over to it via `aktuell`.

    See intern/views/files.py for the helpers that maintain this.
    """

    aktuell = models.CharField(max_length=255, db_index=True)
    pfad = models.CharField(max_length=255)
    original_filename = models.CharField(max_length=255, blank=True)
    groesse = models.BigIntegerField(default=0)
    sha1 = models.CharField(max_length=40, blank=True)
    mime_type = models.CharField(max_length=255, blank=True)
    autor = models.ForeignKey("User", null=True, blank=True, on_delete=models.SET_NULL)
    datum = models.DateTimeField(auto_now_add=True)
    nummer = models.IntegerField(default=1)

    class Meta:
        ordering = ["-nummer"]
        verbose_name = "Dateiversion"
        verbose_name_plural = "Dateiversionen"

    def __str__(self):
        return f"{self.original_filename} v{self.nummer}"


class ChangeLog(models.Model):
    ACTION_CREATE = "create"
    ACTION_UPDATE = "update"
    ACTION_DELETE = "delete"
    ACTION_LOGIN = "login"
    ACTION_LOGOUT = "logout"
    ACTION_APPLICATION = "apply"
    ACTION_NOTIFY = "notify"
    ACTION_CHOICES = [
        (ACTION_CREATE, "Erstellt"),
        (ACTION_UPDATE, "Geändert"),
        (ACTION_DELETE, "Gelöscht"),
        (ACTION_LOGIN, "eingeloggt"),
        (ACTION_LOGOUT, "ausgeloggt"),
        (ACTION_APPLICATION, "Neuer Mitgliedsantrag"),
        (ACTION_NOTIFY, "E-Mail gesendet"),
    ]

    timestamp = models.DateTimeField(default=timezone.now)
    user = models.ForeignKey(
        "User", null=True, on_delete=models.SET_NULL, related_name="changelog_entries"
    )
    action = models.CharField(max_length=8, choices=ACTION_CHOICES)
    model_name = models.CharField(max_length=64)
    object_id = models.PositiveIntegerField()
    object_repr = models.CharField(max_length=200)
    changes = models.JSONField(default=dict)

    class Meta:
        verbose_name_plural = "Änderungsprotokoll"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["model_name", "object_id"]),
            # Aufsteigend, nicht -timestamp: MySQL vor 8 ignoriert DESC stillschweigend.
            # cleanup_changelog filtert timestamp__lt, die Protokollansicht sortiert danach.
            models.Index(fields=["timestamp"]),
        ]
