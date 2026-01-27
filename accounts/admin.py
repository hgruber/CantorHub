from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import *


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = [
        "first_name",
        "last_name",
        "stimme",
        "email",
        "is_active",
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


@admin.register(Forum)
class ForumAdmin(admin.ModelAdmin):
    list_display = [
        "thema",
        "anzahl_mitteilungen",
        "sender",
        "zugriff",
    ]

    def get_queryset(self, request):
        return Forum.objects.extra().order_by("-zugriff")

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


class TerminLiedInline(admin.TabularInline):
    model = Konzert
    extra = 0
    fields = ("lied", "position")


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
    inlines = [TerminLiedInline]


@admin.register(Lied)
class LiedAdmin(admin.ModelAdmin):
    list_display = ("titel", "aktiv", "tempo", "beats", "hymne", "acapella")
    list_filter = ("aktiv", "tempo", "hymne", "acapella")
