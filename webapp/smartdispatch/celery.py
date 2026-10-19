import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartdispatch.settings")

app = Celery("smartdispatch")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
app.conf.beat_schedule = {
    "refresh-current-predictions": {
        "task": "map.tasks.refresh_current_predictions",
        "schedule": crontab(minute=0),
    },
}
