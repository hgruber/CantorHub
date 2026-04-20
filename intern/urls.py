from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    # Authentication URLs
    path(
        "login/",
        views.CantorLoginView.as_view(
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
    path("file-search/", views.file_search, name="file_search"),
    path("ordner/<int:pk>/", views.folder_view, name="folder_view"),
    path("ordner/<int:pk>/neu/", views.folder_create, name="folder_create"),
    path("ordner/<int:pk>/zip/", views.folder_zip_download, name="folder_zip"),
    path("ordner/loeschen/", views.folder_delete, name="folder_delete"),
    path("ordner/verschieben/", views.folder_move, name="folder_move"),
    path("ordner/kopieren/", views.folder_copy, name="folder_copy"),
    path("ordner/umbenennen/", views.folder_rename, name="folder_rename"),
    path("file/", views.dummy, name="file_list"),
    path("file/<int:pk>/entpacken/", views.file_unzip, name="file_unzip"),
    path("file/<str:name>/", views.dummy, name="file_view"),
    path("file/<str:name>/edit/", views.dummy, name="file_edit"),
    # Forum URLs
    path("forum/", views.forum_list, name="forum_list"),
    path("forum/<int:forum>/", views.forum_view, name="forum_view"),
    path("forum/<int:forum>/get/", views.forum_get, name="forum_get"),
    path("forum/<int:forum>/edit/", views.forum_edit, name="forum_edit"),
    path("forum/<int:forum>/invite/<int:user_id>/", views.forum_invite, name="forum_invite"),
    path("forum/<int:forum>/more/", views.forum_more, name="forum_more"),
    path("forum/<int:forum>/send/", views.forum_send, name="forum_send"),
    # Repertoire URLs
    path("titel/", views.titel_list, name="titel_list"),
    path("titel/<int:titel>/", views.titel_view, name="titel_view"),
    path("titel/<int:titel>/edit/", views.titel_edit, name="titel_edit"),
    path("update-order/", views.update_order, name="update-order"),
    # Termin URLs
    path("termin/", views.termin_list, name="termin_list"),
    path("termin/<int:id>/", views.termin_view, name="termin_view"),
    path("termin/<int:id>/edit/", views.termin_edit, name="termin_edit"),
    path("termin/<int:id>/zusage/", views.termin_zusage, name="termin_zusage"),
    # Karte
    path("karte/", views.karte_view, name="karte_view"),
    path("karte/ort/", views.karte_ort_create, name="karte_ort_create"),
    path("karte/ort/<int:pk>/", views.karte_ort_detail, name="karte_ort_detail"),
    path("karte/standort/", views.karte_standort, name="karte_standort"),
    path("calendar/<str:secret>.ics", views.calendar_ics, name="calendar_ics"),
    # Mitglieder URLs
    path("mitglied/", views.member_list, name="member_list"),
    path("mitglied/<int:id>/", views.member_view, name="member_view"),
    path("mitglied/<int:id>/edit/", views.member_edit, name="member_edit"),
    path("mitglied/<int:id>/passwd/", views.member_passwd, name="member_passwd"),
    # Artikel URLs
    path("artikel/", views.article_list, name="article_list"),
    path("artikel/<str:name>/", views.article_view, name="article_view"),
    path("artikel/<str:name>/edit/", views.article_edit, name="article_edit"),
    path("artikel/<str:name>/versionen/", views.article_history, name="article_history"),
    path("artikel/<str:name>/diff/", views.article_diff, name="article_diff"),
]