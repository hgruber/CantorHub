import re
from datetime import datetime

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
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Concat
from django.utils import timezone
from django.utils.html import format_html
from filer.fields.file import FilerFileField

from .replacements import apply_replacements, format_datetime

# Contact and address fields a member may individually hide from other members.
# When ANY of ADDRESS_TRIGGER_FIELDS is hidden, breite/laenge are nulled at save
# time so the address cannot be reconstructed from the coordinates.
PRIVACY_FIELDS = [
    "email", "xmpp",
    "telefon", "telefon_job", "telefon_mobil", "telefon_job_mobil", "fax",
    "geburtstag", "strasse", "plz", "ort",
]
ADDRESS_TRIGGER_FIELDS = {"strasse", "plz", "ort"}

# MUC-Nickname des XMPP-Brücken-Bots (muss mit ejabberd_bot.join_muc übereinstimmen).
BOT_NICK = "CantorBot"


def fallback_avatar_url(original_filename):
    """URL eines per ``import_files`` (django-filer) importierten Fallback-Avatars
    (z. B. ``kein_photo.png`` / ``bot.png``). Leerer String, falls nicht vorhanden."""
    from filer.models import File

    f = File.objects.filter(original_filename=original_filename).first()
    return f.url if f else ""


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
    last_name = models.CharField(max_length=32, verbose_name="Nachname")

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
        return f"{self.first_name} {self.last_name}"

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
    def datei_referenzen(cls):
        """
        Gibt alle Dateien zurück, die mindestens einen Dateireferenz‑Link
        haben (z. B. [[Datei:Bild.jpg|Beschreibung]]).
        """
        qs = cls.objects.filter(text__contains="[[Datei:")
        dateien = set()
        for artikel in qs:
            dateien.update(
                cls.dateiname_aus_link(n)
                for n in cls.DATEI_LINK_RE.findall(artikel.text)
            )
        return sorted(d for d in dateien if d)

    @classmethod
    def aktuelle_datei_referenzen(cls):
        """
        Gibt alle Dateien zurück, die mindestens einen Dateireferenz‑Link
        in einem aktuellen Artikel haben (z. B. [[Datei:Bild.jpg|Beschreibung]]).
        """
        return sorted(cls.aktuelle_datei_verweise())

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


class ForumQuerySet(models.QuerySet):
    def extra_data(self):
        # Get the full name of the sender of the most recent message
        last_sender_subquery = (
            Mitteilung.objects.filter(forum=OuterRef("pk"))
            .order_by("-datum")
            .values(
                besitzer=Concat("sender__first_name", Value(" "), "sender__last_name")
            )[:1]
        )

        return self.select_related("bild").annotate(
            anzahl_mitteilungen=Count("mitteilung"),
            zugriff=Max("mitteilung__datum"),
            letzter_absender=Subquery(last_sender_subquery),
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
    mitteilung = models.TextField(blank=True, null=True)
    xmpp_stanza_id = models.CharField(
        max_length=255, null=True, blank=True, unique=True, db_index=True
    )
    # Set by forum_react when a web user's reaction set changed; the bot relays
    # the new web-reaction union to the MUC and clears the flag (see ejabberd_bot).
    reactions_dirty = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "Mitteilungen"
        ordering = ["-datum"]

    def __str__(self):
        return f"Message from {self.sender} in forum {self.forum}"

    def formatiert(self):
        return apply_replacements(self.mitteilung)

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
        """Avatar-URL des Absenders mit Fallback auf bot.png bzw. kein_photo.png."""
        if self.is_from_bot():
            return fallback_avatar_url("bot.png")
        if self.sender and self.sender.avatar:
            return self.sender.avatar.url
        return fallback_avatar_url("kein_photo.png")


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


class Reaktion(models.Model):
    """An emoji reaction (XEP-0444) on a single Mitteilung.

    Per XEP-0444 the latest reaction stanza from a reactor fully replaces that
    reactor's previous set, so uniqueness is enforced in application code via
    delete-then-insert (see views.forums / ejabberd_bot), not a DB constraint:
    the reactor identity is ``sender`` for web reactions and ``reactor_jid`` for
    XMPP ones (where ``sender`` may be None for an unmapped JID).
    """

    REACTION_EMOJIS = ["👍", "❤️", "😂", "🎉", "😮", "😢", "🙏", "👏"]

    mitteilung = models.ForeignKey(
        "Mitteilung", on_delete=models.CASCADE, related_name="reaktionen", db_index=True
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


class Termin(models.Model):
    datum = models.DateTimeField()
    datum_bis = models.DateTimeField(blank=True, null=True)
    wiederholung = models.CharField(max_length=1, default="e")
    kurz = models.CharField(max_length=64)
    lang = models.TextField(blank=True, null=True)
    ort = models.ForeignKey("Ort", null=True, blank=True, on_delete=models.SET_NULL)
    extern = models.TextField(blank=True, null=True)
    ctag = models.IntegerField(default=0)
    repertoire = models.BooleanField(default=False)
    anwesenheit = models.BooleanField(default=False)
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

    @classmethod
    def find_similar_titles(cls, search_string, limit=5):
        """
        Find similar song titles using fuzzy matching.

        Args:
            search_string (str): The string to search for
            limit (int): Number of results to return (default: 5)

        Returns:
            list: List of tuples (song, similarity_score) sorted by similarity
        """
        try:
            from .fuzzy import find_similar_titles

            # Get all song objects from the database
            songs = cls.objects.all()
            return find_similar_titles(search_string, songs, limit)
        except ImportError:
            # If rapidfuzz is not available, return empty list
            return []

    @classmethod
    def get_similar_titles(cls, search_string, limit=5):
        """
        Get similar song titles in a user-friendly format.

        Args:
            search_string (str): The string to search for
            limit (int): Number of results to return (default: 5)

        Returns:
            list: List of dictionaries with song information and similarity score
        """
        try:
            from .fuzzy import get_similar_titles

            # Get all song objects from the database
            songs = cls.objects.all()
            return get_similar_titles(search_string, songs, limit)
        except ImportError:
            # If rapidfuzz is not available, return empty list
            return []

    @classmethod
    def datei_referenzen(cls):
        """
        Return all needed filenames for all songs
        """
        titel = list(Lied.objects.values_list("titel", flat=True))
        return [x for t in titel for x in (t, f"JG-{t}")]


class Konzert(models.Model):
    termin = models.ForeignKey("Termin", on_delete=models.CASCADE)
    lied = models.ForeignKey("Lied", null=True, on_delete=models.CASCADE)
    position = models.IntegerField(default=1)

    class Meta:
        verbose_name_plural = "Konzerte"
        ordering = ["position"]

    def __str__(self):
        return f"{self.position} - {self.termin.kurz} - {self.lied}"


class Zusage(models.Model):
    person = models.ForeignKey("User", on_delete=models.CASCADE)
    termin = models.ForeignKey("Termin", on_delete=models.CASCADE)
    option = models.CharField(max_length=255, default="1")

    OPTION_LABELS = {"1": "Zusage", "2": "Absage", "3": "Eventuell", "": "Keine Angabe"}

    class Meta:
        verbose_name_plural = "Zusagen"

    def __str__(self):
        label = self.OPTION_LABELS.get(self.option, self.option or "Keine Angabe")
        return f"{self.person} – {label}"


class Abstimmung(models.Model):
    person = models.ForeignKey("User", on_delete=models.CASCADE)
    abstimmung = models.CharField(max_length=256)
    option = models.CharField(max_length=256)

    class Meta:
        verbose_name_plural = "Abstimmungen"


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

    timestamp = models.DateTimeField(default=datetime.now)
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
            models.Index(fields=["user"]),
        ]
