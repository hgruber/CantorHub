from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import (
    Case,
    CharField,
    Count,
    F,
    Max,
    OuterRef,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Concat
from django.utils.html import format_html
from filer.fields.file import FilerFileField

from .replacements import apply_replacements, format_datetime


class User(AbstractUser):
    # --- Legacy Identity ---
    legacy_id = models.PositiveSmallIntegerField(unique=True, null=True)

    # --- Namen ---
    first_name = models.CharField(max_length=32, verbose_name="Vorname")
    last_name = models.CharField(max_length=32, verbose_name="Nachname")

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
    xmpp = models.CharField(max_length=48, null=True, blank=True)

    # --- Meta / Status ---
    text = models.TextField(null=True, blank=True)

    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "Mitglied"
        verbose_name_plural = "Mitglieder"

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

    def __str__(self):
        return self.name


class ForumQuerySet(models.QuerySet):
    def extra_data(self):
        # Get the full name of the sender of the most recent message
        last_sender_subquery = (
            Mitteilung.objects.filter(forum=OuterRef("pk"))
            .order_by("-datum")
            .values(
                full_name=Concat("sender__first_name", Value(" "), "sender__last_name")
            )[:1]
        )

        return self.annotate(
            anzahl_mitteilungen=Count("mitteilung"),
            zugriff=Max("mitteilung__datum"),
            letzter_absender=Subquery(last_sender_subquery),
        )


class Forum(models.Model):
    thema = models.CharField(max_length=120)
    objects = ForumQuerySet.as_manager()

    class Meta:
        verbose_name_plural = "Foren"

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

    class Meta:
        verbose_name_plural = "Mitteilungen"
        ordering = ["-datum"]

    def __str__(self):
        return f"Message from {self.sender} in forum {self.forum}"

    def formatiert(self):
        return apply_replacements(self.mitteilung)


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
    ort = models.ForeignKey("Ort", null=True, on_delete=models.SET_NULL)
    extern = models.TextField(blank=True, null=True)
    ctag = models.IntegerField(default=0)
    repertoire = models.BooleanField(default=False)
    anwesenheit = models.BooleanField(default=False)
    mitglied = models.ManyToManyField("User", through="Zusage", related_name="termin")

    class Meta:
        verbose_name_plural = "Termine"

    def __str__(self):
        return self.kurz


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
    tempo = models.CharField(
        max_length=1, choices=[("l", "l"), ("m", "m"), ("s", "s")], default="m"
    )
    beats = models.SmallIntegerField(blank=True, null=True)
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
    lied = models.ForeignKey("Lied", on_delete=models.CASCADE)
    position = models.IntegerField(default=1)

    class Meta:
        verbose_name_plural = "Konzerte"
        ordering = ["position"]

    def __str__(self):
        return f"{self.position} - {self.termin.kurz}"


class Zusage(models.Model):
    person = models.ForeignKey("User", on_delete=models.CASCADE)
    termin = models.ForeignKey("Termin", on_delete=models.CASCADE)
    option = models.CharField(max_length=255, default="1")

    class Meta:
        verbose_name_plural = "Zusagen"


class Abstimmung(models.Model):
    person = models.ForeignKey("User", on_delete=models.CASCADE)
    abstimmung = models.CharField(max_length=256)
    option = models.CharField(max_length=256)

    class Meta:
        verbose_name_plural = "Abstimmungen"


class TabellenPreferenzen(models.Model):
    person = models.ForeignKey("User", on_delete=models.CASCADE)
    tabelle = models.CharField(max_length=100)
    sichtbare_spalten = models.JSONField(default=list)

    class Meta:
        unique_together = (
            "person",
            "tabelle",
        )
