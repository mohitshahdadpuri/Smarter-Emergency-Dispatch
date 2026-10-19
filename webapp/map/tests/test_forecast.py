from unittest import mock

import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from map import forecast


class ForecastTests(SimpleTestCase):
    def tearDown(self):
        forecast.load_forecaster.cache_clear()

    def test_model_forecasts_any_future_hour(self):
        model = forecast.ModelForecaster()
        for when in ["2017-12-01 08:00", "2026-10-19 21:00", "2031-03-01 03:00"]:
            with self.subTest(when=when):
                preds = model.predict(pd.Timestamp(when))
                self.assertEqual(len(preds), 27)
                self.assertTrue(np.isfinite(preds["call_counts"]).all())
                self.assertTrue((preds["call_counts"] >= 0).all())

    def test_busy_hours_forecast_more_calls_than_quiet_hours(self):
        model = forecast.ModelForecaster()
        evening = model.predict(pd.Timestamp("2026-10-16 18:00"))["call_counts"].sum()
        early_morning = model.predict(pd.Timestamp("2026-10-16 05:00"))["call_counts"].sum()
        self.assertGreater(evening, early_morning)

    def test_profile_forecaster(self):
        preds = forecast.ProfileForecaster().predict(pd.Timestamp("2026-10-19 21:00"))
        self.assertEqual(len(preds), 27)
        self.assertTrue((preds["call_counts"] >= 0).all())

    def test_falls_back_to_profile_when_model_cannot_load(self):
        forecast.load_forecaster.cache_clear()
        with mock.patch.object(forecast, "ModelForecaster", side_effect=ValueError("bad pickle")):
            with self.assertLogs("map.forecast", level="WARNING"):
                self.assertIsInstance(forecast.load_forecaster(), forecast.ProfileForecaster)

    def test_calendar_features(self):
        frame = pd.DataFrame(
            {"zcta": ["94110", "99999"], "timestamp": [pd.Timestamp("2026-07-03 12:00"), pd.Timestamp("2026-07-06")]}
        )
        X = forecast.calendar_features(frame, ["94102", "94110"])
        self.assertEqual(X.loc[0, "zcta_code"], 1)
        self.assertTrue(np.isnan(X.loc[1, "zcta_code"]))
        # July 4th 2026 is a Saturday, so the federal holiday is observed on Friday the 3rd.
        self.assertEqual(X["is_holiday"].tolist(), [1, 0])
        self.assertEqual(X.loc[0, "day_of_week"], 4)
