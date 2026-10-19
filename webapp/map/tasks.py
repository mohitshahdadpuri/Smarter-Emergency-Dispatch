"""Periodic jobs. Run a worker with beat to keep forecasts warm:

    celery -A smartdispatch worker --beat --loglevel=info

The web app also refreshes forecasts on demand, so this is optional.
"""
from celery import shared_task

from .services import ensure_current_predictions


@shared_task
def refresh_current_predictions():
    ensure_current_predictions()
