import numpy as np
import pandas as pd
import shapely
from django.test import SimpleTestCase

from map import placement


def predictions(value=1.0):
    zctas = placement.load_regions()["zcta"]
    return pd.DataFrame({"zcta": zctas, "call_counts": value})


def ambulances(rows):
    return pd.DataFrame(rows, columns=["amb_id", "LAT", "LONG", "AVAILABLE"])


class PlacementTests(SimpleTestCase):
    def test_far_away_ambulances_move_to_distinct_posts_on_land(self):
        start = (37.80, -122.46)
        units = ambulances([(i, *start, 1) for i in range(5)])
        result = placement.update_ambulance_assignments(units, predictions())

        self.assertTrue(result["moved"].all())
        posts = set(zip(result["LAT"].round(6), result["LONG"].round(6)))
        self.assertEqual(len(posts), 5)
        city = placement.load_regions().union_all()
        for lat, lon in posts:
            self.assertTrue(city.contains(shapely.Point(lon, lat)))

    def test_ambulances_already_on_posts_stay_put(self):
        # Regression test: the original code computed a matching between
        # ambulances and posts but then ignored it, sending ambulance i to
        # cluster center i. Ambulances sitting on the posts (in shuffled
        # order) must not be moved.
        preds = predictions()
        posts = placement.choose_posts(placement.demand_points(preds), 4)
        lonlat = placement._project(posts[:, 0], posts[:, 1], placement.PROJECTED_CRS, placement.GEOGRAPHIC_CRS)
        order = [2, 0, 3, 1]
        units = ambulances([(10 + i, lonlat[j, 1], lonlat[j, 0], 1) for i, j in enumerate(order)])

        result = placement.update_ambulance_assignments(units, preds)

        self.assertFalse(result["moved"].any())
        np.testing.assert_allclose(result["LAT"].to_numpy(), units["LAT"].to_numpy())

    def test_unavailable_ambulances_are_not_moved(self):
        units = ambulances([(1, 37.80, -122.46, 0), (2, 37.80, -122.46, 1)])
        result = placement.update_ambulance_assignments(units, predictions())
        self.assertFalse(result.loc[1, "moved"])
        self.assertEqual((result.loc[1, "LAT"], result.loc[1, "LONG"]), (37.80, -122.46))
        self.assertTrue(result.loc[2, "moved"])

    def test_no_available_ambulances(self):
        units = ambulances([(1, 37.80, -122.46, 0)])
        result = placement.update_ambulance_assignments(units, predictions())
        self.assertFalse(result["moved"].any())

    def test_zero_missing_and_partial_predictions_do_not_crash(self):
        units = ambulances([(i, 37.80, -122.46, 1) for i in range(3)])
        cases = [
            predictions(0.0),
            predictions(np.nan),
            pd.DataFrame({"zcta": [], "call_counts": []}),
            pd.DataFrame({"zcta": ["94110", "99999"], "call_counts": [2.0, 5.0]}),
            pd.DataFrame({"zcta": ["99999"], "call_counts": [5.0]}),
        ]
        for preds in cases:
            with self.subTest(preds=preds.head(2).to_dict()):
                result = placement.update_ambulance_assignments(units, preds)
                self.assertTrue(result["moved"].all())

    def test_demand_concentrates_posts(self):
        preds = predictions(0.0)
        preds.loc[preds["zcta"] == "94110", "call_counts"] = 10.0
        result = placement.update_ambulance_assignments(ambulances([(1, 37.80, -122.46, 1)]), preds)
        mission = placement.load_regions().set_index("zcta").loc["94110", "geometry"]
        self.assertTrue(mission.contains(shapely.Point(result.loc[1, "LONG"], result.loc[1, "LAT"])))

    def test_deterministic(self):
        units = ambulances([(i, 37.80, -122.46, 1) for i in range(4)])
        first = placement.update_ambulance_assignments(units, predictions())
        second = placement.update_ambulance_assignments(units, predictions())
        pd.testing.assert_frame_equal(first, second)
