"""WSGI entry point, e.g. ``gunicorn smartdispatch.wsgi``."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartdispatch.settings")

application = get_wsgi_application()
