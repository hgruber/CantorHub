"""URL-Muster des CalDAV-Diensts.

Die beiden Sammlungen stehen als feste Pfadsegmente da und reichen ``art`` als
Zusatzargument in dieselbe View — ein ``<str:art>`` würde jeden Tippfehler zu
einem 404 auf dem Umweg über die View machen, statt schon beim Auflösen zu
scheitern.
"""

from django.urls import path

from . import views

app_name = "caldav"

urlpatterns = [
    path("", views.dav_root, name="root"),
    path("principal/<int:pk>/", views.principal, name="principal"),
    path("kalender/<int:pk>/", views.home_set, name="home"),
    path("kalender/<int:pk>/termine/", views.sammlung,
         {"art": "termine"}, name="termine"),
    path("kalender/<int:pk>/termine/<int:eid>.ics", views.eintrag,
         {"art": "termine"}, name="termin"),
    path("kalender/<int:pk>/geburtstage/", views.sammlung,
         {"art": "geburtstage"}, name="geburtstage"),
    path("kalender/<int:pk>/geburtstage/<int:eid>.ics", views.eintrag,
         {"art": "geburtstage"}, name="geburtstag"),
]
