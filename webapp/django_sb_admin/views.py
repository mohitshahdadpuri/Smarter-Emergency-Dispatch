from django.shortcuts import render


def main(request):
    """Landing page."""
    return render(request, "django_sb_admin/sb_admin_main.html", {"nav_active": "main"})


def map_page(request):
    """Dispatcher console, embedded from /rawmap/."""
    return render(request, "django_sb_admin/map.html", {"nav_active": "map"})


def charts(request):
    """Tableau dashboard of historical calls."""
    return render(request, "django_sb_admin/sb_admin_charts.html", {"nav_active": "charts"})


def about(request):
    """Project information."""
    return render(request, "django_sb_admin/sb_admin_about.html", {"nav_active": "about"})
