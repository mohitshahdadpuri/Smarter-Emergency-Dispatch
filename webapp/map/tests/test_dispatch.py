from unittest import mock

from django.test import SimpleTestCase
from googlemaps.exceptions import ApiError

from map import dispatch

CALL = (37.7793, -122.4193)


def element(seconds=None, traffic=None, status="OK"):
    result = {"status": status}
    if seconds is not None:
        result["duration"] = {"value": seconds}
    if traffic is not None:
        result["duration_in_traffic"] = {"value": traffic}
    return {"elements": [result]}


class ChooseAmbulanceTests(SimpleTestCase):
    available = [(1, 37.7795, -122.4195), (2, 37.75, -122.45), (3, 37.79, -122.40)]

    def test_picks_shortest_drive_time_in_traffic(self):
        client = mock.Mock()
        client.distance_matrix.return_value = {
            "rows": [element(100, traffic=900), element(300, traffic=400), element(status="ZERO_RESULTS")]
        }
        choice = dispatch.choose_ambulance(self.available, *CALL, api_key="", client=client)
        self.assertEqual(choice, dispatch.Choice(2, 400, "drive time in traffic"))
        kwargs = client.distance_matrix.call_args.kwargs
        self.assertEqual(kwargs["departure_time"], "now")

    def test_uses_plain_duration_without_traffic_data(self):
        client = mock.Mock()
        client.distance_matrix.return_value = {"rows": [element(500), element(200), element(700)]}
        self.assertEqual(dispatch.choose_ambulance(self.available, *CALL, api_key="", client=client).amb_id, 2)

    def test_falls_back_to_straight_line_when_api_fails(self):
        client = mock.Mock()
        client.distance_matrix.side_effect = ApiError("REQUEST_DENIED")
        with self.assertLogs("map.dispatch", level="ERROR"):
            choice = dispatch.choose_ambulance(self.available, *CALL, api_key="", client=client)
        self.assertEqual(choice, dispatch.Choice(1, None, "straight-line distance"))

    def test_falls_back_when_no_route_is_usable(self):
        client = mock.Mock()
        client.distance_matrix.return_value = {"rows": [element(status="NOT_FOUND")] * 3}
        self.assertEqual(dispatch.choose_ambulance(self.available, *CALL, api_key="", client=client).amb_id, 1)

    def test_without_api_key_uses_straight_line(self):
        self.assertEqual(dispatch.choose_ambulance(self.available, *CALL, api_key="").amb_id, 1)

    def test_no_available_ambulance(self):
        self.assertIsNone(dispatch.choose_ambulance([], *CALL, api_key="key"))

    def test_batches_origins(self):
        available = [(i, 37.70 + i / 1000, -122.45) for i in range(30)]
        client = mock.Mock()
        client.distance_matrix.side_effect = lambda origins, *a, **k: {
            "rows": [element(1000 - len(origins) * 10 - n) for n in range(len(origins))]
        }
        choice = dispatch.choose_ambulance(available, *CALL, api_key="", client=client)
        self.assertEqual(client.distance_matrix.call_count, 2)
        self.assertEqual([len(c.args[0]) for c in client.distance_matrix.call_args_list], [25, 5])
        self.assertEqual(choice.amb_id, 24)


class GeocodeTests(SimpleTestCase):
    def test_coordinates_need_no_api_key(self):
        self.assertEqual(dispatch.geocode(" 37.7793,-122.4193 ", api_key=""), CALL)

    def test_outside_service_area(self):
        with self.assertRaisesMessage(dispatch.GeocodingError, "outside the San Francisco service area"):
            dispatch.geocode("40.7128, -74.0060", api_key="")

    def test_address_without_api_key(self):
        with self.assertRaisesMessage(dispatch.GeocodingError, "GGL_API_KEY"):
            dispatch.geocode("1 Dr Carlton B Goodlett Pl", api_key="")

    def test_address_lookup(self):
        client = mock.Mock()
        client.geocode.return_value = [{"geometry": {"location": {"lat": CALL[0], "lng": CALL[1]}}}]
        self.assertEqual(dispatch.geocode("1 Dr Carlton B Goodlett Pl", api_key="", client=client), CALL)
        self.assertEqual(client.geocode.call_args.kwargs["bounds"], dispatch.SF_BOUNDS)

    def test_address_not_found(self):
        client = mock.Mock()
        client.geocode.return_value = []
        with self.assertRaisesMessage(dispatch.GeocodingError, "Couldn't find"):
            dispatch.geocode("nowhere", api_key="", client=client)

    def test_api_error(self):
        client = mock.Mock()
        client.geocode.side_effect = ApiError("OVER_QUERY_LIMIT")
        with self.assertLogs("map.dispatch", level="ERROR"), self.assertRaisesMessage(dispatch.GeocodingError, "failed"):
            dispatch.geocode("1 Market St", api_key="", client=client)
