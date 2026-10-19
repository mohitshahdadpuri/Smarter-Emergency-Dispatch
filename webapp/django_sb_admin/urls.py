from django.urls import path

from . import views

urlpatterns = [
    path("", views.main, name="sb_admin_main"),
    path("map/", views.map_page, name="sb_admin_map"),
    path("charts/", views.charts, name="sb_admin_charts"),
    path("about/", views.about, name="sb_admin_about"),
]
