from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    # Authentication URLs
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="login.html", next_page="/intern/artikel/Aktuell/"
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
    # Upload and File URLs
    path("upload/", views.upload, name="upload"),
    path("ordner/<int:pk>/", views.folder_view, name="folder_view"),
    path("file/", views.dummy, name="file_list"),
    path("file/<str:name>/", views.dummy, name="file_view"),
    path("file/<str:name>/edit/", views.dummy, name="file_edit"),
    # Forum URLs
    path("forum/", views.forum_list, name="forum_list"),
    path("forum/<int:forum>/", views.forum_view, name="forum_view"),
    path("forum/<int:forum>/get/", views.forum_get, name="forum_get"),
    path("forum/<int:forum>/edit/", views.dummy, name="forum_edit"),
    path("forum/<int:forum>/more/", views.forum_more, name="forum_more"),
    path("forum/<int:forum>/send/", views.forum_send, name="forum_send"),
    # Mitglieder URLs
    path("mitglied/", views.mitglieder_liste, name="member_list"),
    path("mitglied/<int:id>/", views.mitglied_view, name="member_view"),
    path("mitglied/<int:id>/edit/", views.dummy, name="member_edit"),
    # Artikel URLs
    path("artikel/", views.artikel_liste, name="article_list"),
    path("artikel/<str:name>/", views.artikel, name="article_view"),
    path("artikel/<str:name>/edit/", views.article_edit, name="article_edit"),
]
