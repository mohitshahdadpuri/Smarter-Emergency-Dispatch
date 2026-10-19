from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("", include("django_sb_admin.urls")),
    path("admin/", admin.site.urls),
    path("rawmap/", include("map.urls")),
]
