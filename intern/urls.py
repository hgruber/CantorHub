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
    # Konfiguration URLs
    path("konfiguration/", views.konfiguration, name="konfiguration"),
    path("berechtigungen/", views.berechtigungen, name="berechtigungen"),
    path("aenderungsprotokoll/", views.aenderungsprotokoll_list, name="aenderungsprotokoll_list"),
    # Upload and File URLs
    path("upload/", views.upload, name="upload"),
    path("file-search/", views.file_search, name="file_search"),
    path("article-search/", views.article_search, name="article_search"),
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
    path("forum/add/", views.forum_add, name="forum_add"),
    path("forum/<int:forum>/", views.forum_view, name="forum_view"),
    path("forum/<int:forum>/get/", views.forum_get, name="forum_get"),
    path("forum/<int:forum>/edit/", views.forum_edit, name="forum_edit"),
    path("forum/<int:forum>/invite/<int:user_id>/", views.forum_invite, name="forum_invite"),
    path("forum/<int:forum>/more/", views.forum_more, name="forum_more"),
    path("forum/<int:forum>/send/", views.forum_send, name="forum_send"),
    path("forum/<int:id>/aenderungen/", views.forum_aenderungen, name="forum_aenderungen"),
    # Repertoire URLs
    path("titel/", views.titel_list, name="titel_list"),
    path("titel/add/", views.titel_add, name="titel_add"),
    path("titel/<int:titel>/", views.titel_view, name="titel_view"),
    path("titel/<int:titel>/edit/", views.titel_edit, name="titel_edit"),
    path("titel/<int:titel>/delete/", views.titel_delete, name="titel_delete"),
    path("titel/<int:id>/aenderungen/", views.titel_aenderungen, name="titel_aenderungen"),
    path("update-order/", views.update_order, name="update-order"),
    # Termin URLs
    path("termin/", views.termin_list, name="termin_list"),
    path("termin/add/", views.termin_add, name="termin_add"),
    path("termin/<int:id>/", views.termin_view, name="termin_view"),
    path("termin/<int:id>/edit/", views.termin_edit, name="termin_edit"),
    path("termin/<int:id>/aenderungen/", views.termin_aenderungen, name="termin_aenderungen"),
    path("termin/<int:id>/delete/", views.termin_delete, name="termin_delete"),
    path("termin/<int:id>/docx/", views.konzert_docx, name="konzert_docx"),
    path("termin/<int:id>/docx-titles/", views.konzert_docx_titles, name="konzert_docx_titles"),
    path("termin/<int:id>/pdf/", views.konzert_pdf, name="konzert_pdf"),
    path("termin/<int:id>/pdf-zip/", views.konzert_pdf_zip, name="konzert_pdf_zip"),
    path("termin/<int:id>/noten-zip/", views.konzert_noten_zip, name="konzert_noten_zip"),
    path("termin/<int:id>/zusage/", views.termin_zusage, name="termin_zusage"),
    path("termin/<int:id>/anwesenheit/", views.termin_anwesenheit_update, name="termin_anwesenheit_update"),
    # Ort URLs
    path("ort/", views.ort_list, name="ort_list"),
    path("ort/add/", views.ort_add, name="ort_add"),
    path("ort/<int:id>/", views.ort_view, name="ort_view"),
    path("ort/<int:id>/edit/", views.ort_edit, name="ort_edit"),
    path("ort/<int:id>/aenderungen/", views.ort_aenderungen, name="ort_aenderungen"),
    # Karte
    path("karte/", views.karte_view, name="karte_view"),
    path("karte/ort/", views.karte_ort_create, name="karte_ort_create"),
    path("karte/ort/<int:pk>/", views.karte_ort_detail, name="karte_ort_detail"),
    path("karte/standort/", views.karte_standort, name="karte_standort"),
    path("karte/standorte/", views.karte_standorte_live, name="karte_standorte_live"),
    path("calendar/<str:secret>.ics", views.calendar_ics, name="calendar_ics"),
    # Mitglieder URLs
    path("mitglied/", views.mitglied_list, name="mitglied_list"),
    path("mitglied/add/", views.mitglied_add, name="mitglied_add"),
    path("mitglied/<int:id>/", views.mitglied_view, name="mitglied_view"),
    path("mitglied/<int:id>/edit/", views.mitglied_edit, name="mitglied_edit"),
    path("mitglied/<int:id>/passwd/", views.mitglied_passwd, name="mitglied_passwd"),
    path("mitglied/<int:id>/aenderungen/", views.mitglied_aenderungen, name="mitglied_aenderungen"),
    # Artikel URLs
    path("abstimmung/vote/", views.abstimmung_vote, name="abstimmung_vote"),
    path("artikel/", views.article_list, name="article_list"),
    path("artikel/<str:name>/", views.article_view, name="article_view"),
    path("artikel/<str:name>/edit/", views.article_edit, name="article_edit"),
    path("artikel/<str:name>/versionen/", views.article_history, name="article_history"),
    path("artikel/<str:name>/diff/", views.article_diff, name="article_diff"),
]