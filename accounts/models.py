from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Count, F, Max, Min, OuterRef, Subquery
from django.db.models import Value as V
from django.db.models.functions import Concat


class User(AbstractUser):
    # --- Legacy Identity ---
    legacy_id = models.PositiveSmallIntegerField(unique=True, null=True)

    # --- Namen ---
    first_name = models.CharField(max_length=32)
    last_name = models.CharField(max_length=32)

    # --- Personendaten ---
    STIMME_CHOICES = [
        ("N", "None"),
        ("S", "Sopran"),
        ("A", "Alt"),
        ("T", "Tenor"),
        ("B", "Bass"),
        ("M", "Mixed"),
    ]
    stimme = models.CharField(max_length=1, choices=STIMME_CHOICES, default="N")

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

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class ForumQuerySet(models.QuerySet):
    def extra(self):
        return self.annotate(
            anzahl_mitteilungen=Count("mitteilung"), zugriff=Max("mitteilung__datum")
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


class Mitteilung(models.Model):
    forum = models.ForeignKey("Forum", on_delete=models.CASCADE)
    sender = models.ForeignKey("User", null=True, on_delete=models.SET_NULL)
    datum = models.DateTimeField()
    mitteilung = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name_plural = "Mitteilungen"

    def __str__(self):
        return f"Message from {self.sender} in forum {self.forum}"


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

    class Meta:
        verbose_name_plural = "Termine"

    def __str__(self):
        return self.kurz


class Lied(models.Model):
    titel = models.CharField(max_length=48)
    aktiv = models.BooleanField(default=False)
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

    class Meta:
        verbose_name_plural = "Lieder"

    def __str__(self):
        return self.titel


class Konzert(models.Model):
    termin = models.ForeignKey("Termin", on_delete=models.CASCADE)
    lied = models.ForeignKey("Lied", on_delete=models.CASCADE)
    position = models.IntegerField(default=1)

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return f"{self.position} - {self.termin.kurz}"


Lied.konzert = models.ManyToManyField("Lied", through="Konzert", related_name="konzert")
