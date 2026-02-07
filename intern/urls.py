from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="login.html", next_page="/intern/forum/"
        ),
        name="login",
    ),
    path("register/", views.register, name="register"),
    path("register_success/", views.register_success, name="register_success"),
    path(
        "logout/",
        auth_views.LogoutView.as_view(next_page="login"),
        name="logout",
    ),
    path("forum/", views.foren, name="foren"),
    path("forum/<int:forum>/", views.view, name="view"),
    path("forum/<int:forum>/poll", views.poll, name="poll"),
    path("forum/<int:forum>/more", views.more, name="more"),
    path("forum/<int:forum>/send", views.send, name="send"),
    path("mitglied/", views.mitglieder_liste, name="mitglieder_liste"),
    path("mitglied/<int:id>/", views.mitglied, name="mitglied"),
    path("artikel/", views.artikel_liste, name="artikel_liste"),
    path("artikel/<str:name>/", views.artikel, name="artikel"),
]
