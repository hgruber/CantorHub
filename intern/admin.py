from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import *


class TerminLiedInline(admin.TabularInline):
    model = Konzert
    extra = 0
    fields = ("lied", "position")


class TerminUserInline(admin.TabularInline):
    model = Zusage
    extra = 0
    fields = ("person", "option")


class UserTerminInline(admin.TabularInline):
    model = Zusage
    extra = 0
    fields = ("termin", "option")


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = [
        "first_name",
        "last_name",
        "stimme",
        "email",
        "is_active",
        "bild",
    ]
    # fields = []
    # fieldsets = ()
    # readonly_fields = []
    list_filter = [
        "stimme",
        "is_active",
    ]
    search_fields = ["text"]
    # ordering_fields = ['first_name']


#    inlines = [UserTerminInline]


@admin.register(Artikel)
class ArtikelAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "autor",
        "datum",
    ]


@admin.register(Forum)
class ForumAdmin(admin.ModelAdmin):
    list_display = [
        "thema",
        "anzahl_mitteilungen",
        "sender",
        "zugriff",
    ]

    def get_queryset(self, request):
        return Forum.objects.extra_data().order_by("-zugriff")

    def anzahl_mitteilungen(self, obj):
        return obj.anzahl_mitteilungen

    def zugriff(self, obj):
        return obj.zugriff


@admin.register(Mitteilung)
class MitteilungAdmin(admin.ModelAdmin):
    list_display = [
        "sender",
        "datum",
        "forum",
        "mitteilung",
    ]
    list_filter = [
        "forum",
        "sender",
    ]


@admin.register(Ort)
class OrtAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "plz",
        "ort",
    ]


@admin.register(Termin)
class TerminAdmin(admin.ModelAdmin):
    list_display = (
        "kurz",
        "ort__name",
        "lang",
        "datum",
        "repertoire",
        "anwesenheit",
    )
    inlines = [TerminLiedInline, TerminUserInline]


@admin.register(Lied)
class LiedAdmin(admin.ModelAdmin):
    list_display = ("titel", "original", "aktiv", "tempo", "beats", "hymne", "acapella")
    list_filter = ("aktiv", "tempo", "hymne", "acapella")
