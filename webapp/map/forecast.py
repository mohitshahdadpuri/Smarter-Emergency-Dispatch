"""Hourly EMS call-volume forecasts per ZIP code (ZCTA).

This module has no Django dependency so that the training script in
``models/train_forecast.py`` can import the exact feature definitions the
web app uses at prediction time.
"""
import logging
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

logger = logging.getLogger(__name__)

FORECAST_DIR = Path(__file__).resolve().parent / "data" / "forecast"
MODEL_PATH = FORECAST_DIR / "call_model.joblib"
PROFILE_PATH = FORECAST_DIR / "seasonal_profile.csv"

# Features that are known in advance for any future hour, so the model can
# forecast arbitrarily far ahead without a live call feed or weather forecast.
CALENDAR_FEATURES = [
    "zcta_code",
    "hour",
    "day_of_week",
    "month",
    "day_of_year",
    "is_holiday",
    "years_since_2000",
]


@lru_cache(maxsize=None)
def _holidays(start_year, end_year):
    calendar = USFederalHolidayCalendar()
    return calendar.holidays(start=f"{start_year}-01-01", end=f"{end_year}-12-31")


def calendar_features(frame, zctas):
    """Build model features from a frame with ``zcta`` and ``timestamp`` columns.

    ``timestamp`` holds naive local (America/Los_Angeles) wall-clock hours and
    ``zctas`` is the ordered list of ZIP codes the model was trained on; ZIPs
    outside that list get a missing ``zcta_code``.
    """
    ts = pd.to_datetime(frame["timestamp"])
    codes = {str(z): i for i, z in enumerate(zctas)}
    holidays = _holidays(int(ts.dt.year.min()), int(ts.dt.year.max()))
    return pd.DataFrame(
        {
            "zcta_code": frame["zcta"].astype(str).map(codes).astype("float64"),
            "hour": ts.dt.hour,
            "day_of_week": ts.dt.dayofweek,
            "month": ts.dt.month,
            "day_of_year": ts.dt.dayofyear,
            "is_holiday": ts.dt.normalize().isin(holidays).astype(int),
            "years_since_2000": (ts - pd.Timestamp("2000-01-01")).dt.days / 365.25,
        },
        index=frame.index,
    )


class ModelForecaster:
    """Gradient-boosted Poisson model exported by ``models/train_forecast.py``."""

    name = "model"

    def __init__(self, path=MODEL_PATH):
        bundle = joblib.load(path)
        self.model = bundle["model"]
        self.zctas = [str(z) for z in bundle["zctas"]]
        self.trained_through = bundle.get("trained_through")

    def predict(self, when):
        frame = pd.DataFrame({"zcta": self.zctas, "timestamp": pd.Timestamp(when).floor("h")})
        preds = self.model.predict(calendar_features(frame, self.zctas)[CALENDAR_FEATURES])
        return pd.DataFrame({"zcta": self.zctas, "call_counts": np.clip(preds, 0, None)})


class ProfileForecaster:
    """Average calls per (ZIP, weekday, hour) over the most recent history.

    Used when the trained model can't be loaded (for example after a
    scikit-learn upgrade that changes the pickle format).
    """

    name = "seasonal-profile"

    def __init__(self, path=PROFILE_PATH):
        self.profile = pd.read_csv(path, dtype={"zcta": str})
        self.zctas = sorted(self.profile["zcta"].unique())

    def predict(self, when):
        when = pd.Timestamp(when)
        rows = self.profile[
            (self.profile["day_of_week"] == when.dayofweek) & (self.profile["hour"] == when.hour)
        ]
        return rows[["zcta", "call_counts"]].reset_index(drop=True)


@lru_cache(maxsize=1)
def load_forecaster():
    try:
        return ModelForecaster()
    except Exception:
        logger.warning("Could not load %s; falling back to the seasonal profile", MODEL_PATH, exc_info=True)
        return ProfileForecaster()
