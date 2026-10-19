from django.urls import path

from . import views

urlpatterns = [
    path("", views.current_map, name="current_map"),
    path("frame/", views.map_frame, name="map_frame"),
]
