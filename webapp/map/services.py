"""Operations behind the dispatcher console: forecasts, dispatching and rebalancing."""
import pandas as pd
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.utils import timezone

from . import dispatch, placement
from .forecast import load_forecaster
from .models import (
    Ambulance,
    Current_ambulance,
    Current_emscall,
    Current_predictions,
    EMS_Calls,
    Event_feed,
    Predictions,
)

PREDICTION_FIELDS = (
    "zcta",
    "year",
    "month",
    "day_of_month",
    "hour_of_day",
    "day_of_year",
    "week_of_year",
    "day_of_week",
    "is_weekend",
    "call_counts",
)


def local_hour(now=None):
    """The current hour in the project time zone (America/Los_Angeles)."""
    return timezone.localtime(now).replace(minute=0, second=0, microsecond=0)


def _hour_key(hour):
    return {"year": hour.year, "month": hour.month, "day_of_month": hour.day, "hour_of_day": hour.hour}


def log_event(event_type, description, **fields):
    max_length = Event_feed._meta.get_field("event_desc").max_length
    return Event_feed.objects.create(event_type=event_type, event_desc=description[:max_length], **fields)


def ensure_current_predictions(now=None):
    """Make ``Current_predictions`` hold the forecast for the current local hour.

    Rows already in ``Predictions`` for that hour (for example imported with
    ``manage.py load_data --predictions``) are used as-is; otherwise the
    trained model produces them and they are saved to ``Predictions``.
    """
    hour = local_hour(now)
    key = _hour_key(hour)
    with transaction.atomic():
        current = Current_predictions.objects
        if current.exists() and not current.exclude(**key).exists():
            return
        rows = list(Predictions.objects.filter(**key))
        if not rows:
            forecast = load_forecaster().predict(hour.replace(tzinfo=None))
            iso = hour.isocalendar()
            fields = dict(
                key,
                day_of_year=hour.timetuple().tm_yday,
                week_of_year=iso.week,
                day_of_week=hour.weekday(),
                is_weekend=hour.weekday() >= 5,
            )
            rows = Predictions.objects.bulk_create(
                Predictions(zcta=zcta, call_counts=float(calls), **fields)
                for zcta, calls in zip(forecast["zcta"], forecast["call_counts"])
            )
        current.all().delete()
        current.bulk_create(Current_predictions(**{f: getattr(row, f) for f in PREDICTION_FIELDS}) for row in rows)


def current_predictions():
    """DataFrame of ``zcta`` and ``call_counts`` for the current hour."""
    ensure_current_predictions()
    return pd.DataFrame(list(Current_predictions.objects.values("zcta", "call_counts")), columns=["zcta", "call_counts"])


def _record_position(ambulance):
    Ambulance.objects.create(
        amb_id=ambulance.amb_id, LAT=ambulance.LAT, LONG=ambulance.LONG, AVAILABLE=ambulance.AVAILABLE
    )


def rebalance_ambulances():
    """Move available ambulances to posts chosen from the current forecast.

    Returns the number of ambulances that moved.
    """
    ambulances = pd.DataFrame(
        list(Current_ambulance.objects.values("amb_id", "LAT", "LONG", "AVAILABLE")),
        columns=["amb_id", "LAT", "LONG", "AVAILABLE"],
    )
    if ambulances.empty:
        return 0
    updated = placement.update_ambulance_assignments(ambulances, current_predictions())
    moved = updated[updated["moved"]]
    with transaction.atomic():
        for amb_id, row in moved.iterrows():
            ambulance = Current_ambulance.objects.get(amb_id=amb_id)
            _record_position(ambulance)
            ambulance.LAT, ambulance.LONG = float(row["LAT"]), float(row["LONG"])
            ambulance.save(update_fields=["LAT", "LONG"])
        if len(moved):
            log_event("Positions", f"{len(moved)} available ambulance(s) moved to new posts")
    return len(moved)


def handle_call(address):
    """Record a new call, send the best available ambulance and rebalance the rest.

    Raises ``dispatch.GeocodingError`` if the address can't be located.
    Returns a ``(message level, text)`` pair for the dispatcher.
    """
    lat, lon = dispatch.geocode(address, settings.GGL_API_KEY)
    with transaction.atomic():
        for previous in Current_emscall.objects.all():
            EMS_Calls.objects.update_or_create(
                ems_id=previous.id,
                defaults={"addr": previous.addr, "LAT": previous.LAT, "LONG": previous.LONG, "time": previous.time},
            )
        Current_emscall.objects.all().delete()
        call = Current_emscall.objects.create(addr=address, LAT=lat, LONG=lon)
        log_event("Event", f"EMS #{call.id} incoming at ({lat:.5f}, {lon:.5f})", unit=call.id, LAT=lat, LONG=lon)

        available = list(
            Current_ambulance.objects.select_for_update()
            .filter(AVAILABLE=1)
            .order_by("amb_id")
            .values_list("amb_id", "LAT", "LONG")
        )
        choice = dispatch.choose_ambulance(available, lat, lon, settings.GGL_API_KEY)
        if choice is None:
            log_event("Unassigned", f"No ambulance available for EMS #{call.id}", unit=call.id)
            return messages.WARNING, f"EMS #{call.id} recorded, but no ambulance is available."

        ambulance = Current_ambulance.objects.get(amb_id=choice.amb_id)
        _record_position(ambulance)
        ambulance.LAT, ambulance.LONG, ambulance.AVAILABLE = lat, lon, 0
        ambulance.save()
        eta = f", ETA {round(choice.seconds / 60)} min" if choice.seconds is not None else ""
        log_event(
            "Dispatch", f"Amb #{ambulance.amb_id} dispatched to EMS #{call.id}{eta}", unit=ambulance.amb_id, LAT=lat, LONG=lon
        )
        rebalance_ambulances()
    return messages.SUCCESS, f"Ambulance #{ambulance.amb_id} dispatched to EMS #{call.id} (chosen by {choice.method}{eta})."


def activate_ambulance(amb_id):
    """Put an ambulance back in service and rebalance. Returns a message for the dispatcher."""
    with transaction.atomic():
        ambulance = Current_ambulance.objects.select_for_update().get(amb_id=amb_id)
        if ambulance.AVAILABLE == 1:
            return f"Ambulance #{amb_id} is already in service."
        _record_position(ambulance)
        ambulance.AVAILABLE = 1
        ambulance.save(update_fields=["AVAILABLE"])
        log_event("Activate", f"Amb #{amb_id} back in service", unit=amb_id)
        rebalance_ambulances()
    return f"Ambulance #{amb_id} is back in service."
