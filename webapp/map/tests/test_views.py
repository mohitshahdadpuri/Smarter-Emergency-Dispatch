import datetime
from io import StringIO
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from map import services
from map.models import Current_ambulance, Current_emscall, Current_predictions, EMS_Calls, Event_feed, Predictions

PACIFIC = ZoneInfo("America/Los_Angeles")
CITY_HALL = (37.7793, -122.4193)


def add_ambulances():
    # 1 is closest to City Hall, 2 is the other available unit, 3 is out of service.
    Current_ambulance.objects.create(amb_id=1, LAT=37.7800, LONG=-122.4200, AVAILABLE=1)
    Current_ambulance.objects.create(amb_id=2, LAT=37.7300, LONG=-122.4800, AVAILABLE=1)
    Current_ambulance.objects.create(amb_id=3, LAT=37.7600, LONG=-122.4400, AVAILABLE=0)


def post_call(client, address, **kwargs):
    return client.post(reverse("current_map"), {"call-addr": address, "call_submit": ""}, **kwargs)


class PredictionTests(TestCase):
    def test_generates_forecast_for_any_hour(self):
        services.ensure_current_predictions(datetime.datetime(2030, 7, 4, 15, 20, tzinfo=PACIFIC))
        rows = Current_predictions.objects.all()
        self.assertEqual(rows.count(), 27)
        row = rows.first()
        self.assertEqual((row.year, row.month, row.day_of_month, row.hour_of_day), (2030, 7, 4, 15))
        self.assertEqual((row.day_of_week, row.is_weekend, row.week_of_year), (3, False, 27))
        self.assertEqual(Predictions.objects.count(), 27)

    def test_uses_imported_predictions_and_refreshes_each_hour(self):
        Predictions.objects.create(
            zcta="94110", year=2030, month=1, day_of_month=1, hour_of_day=9, day_of_year=1,
            week_of_year=1, day_of_week=1, is_weekend=False, call_counts=42.0,
        )
        services.ensure_current_predictions(datetime.datetime(2030, 1, 1, 9, 5, tzinfo=PACIFIC))
        self.assertEqual(list(Current_predictions.objects.values_list("zcta", "call_counts")), [("94110", 42.0)])

        services.ensure_current_predictions(datetime.datetime(2030, 1, 1, 10, 5, tzinfo=PACIFIC))
        self.assertEqual(Current_predictions.objects.count(), 27)
        self.assertEqual(set(Current_predictions.objects.values_list("hour_of_day", flat=True)), {10})

    def test_uses_local_time(self):
        # 03:30 UTC on Jan 2 is 19:30 on Jan 1 in San Francisco.
        services.ensure_current_predictions(datetime.datetime(2030, 1, 2, 3, 30, tzinfo=datetime.timezone.utc))
        row = Current_predictions.objects.first()
        self.assertEqual((row.day_of_month, row.hour_of_day), (1, 19))


class ConsoleTests(TestCase):
    def setUp(self):
        add_ambulances()

    def test_console_and_map_render(self):
        response = self.client.get(reverse("current_map"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")
        self.assertContains(response, reverse("map_frame"))
        # Only out-of-service units can be reactivated.
        self.assertEqual([c[0] for c in response.context["form2"].fields["amb_id"].choices], [3])

        frame = self.client.get(reverse("map_frame"))
        self.assertEqual(frame.status_code, 200)
        self.assertContains(frame, "Predicted EMS calls per ZIP code")

    def test_map_marker_colors_follow_availability(self):
        html = self.client.get(reverse("map_frame")).content.decode()
        self.assertEqual(html.count('"markerColor": "blue"'), 2)
        self.assertEqual(html.count('"markerColor": "gray"'), 1)

    def test_site_pages(self):
        for name in ["sb_admin_main", "sb_admin_map", "sb_admin_charts", "sb_admin_about"]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_blank_address_is_rejected(self):
        response = post_call(self.client, "")
        self.assertContains(response, "This field is required")
        self.assertFalse(Current_emscall.objects.exists())

    def test_unknown_address_without_api_key_shows_error(self):
        response = post_call(self.client, "1 Market St")
        self.assertContains(response, "GGL_API_KEY")
        self.assertFalse(Current_emscall.objects.exists())

    def test_dispatches_nearest_ambulance_from_coordinates(self):
        response = post_call(self.client, "37.7793, -122.4193", follow=True)
        self.assertRedirects(response, reverse("current_map"))
        self.assertContains(response, "Ambulance #1 dispatched")
        self.assertContains(response, "alert-success")

        sent = Current_ambulance.objects.get(amb_id=1)
        self.assertEqual((sent.AVAILABLE, sent.LAT, sent.LONG), (0, *CITY_HALL))
        call = Current_emscall.objects.get()
        self.assertEqual((call.LAT, call.LONG), CITY_HALL)
        self.assertEqual(
            set(Event_feed.objects.values_list("event_type", flat=True)), {"Event", "Dispatch", "Positions"}
        )

    def test_previous_call_is_archived(self):
        post_call(self.client, "37.7793, -122.4193")
        first = Current_emscall.objects.get()
        post_call(self.client, "37.7600, -122.4400")
        self.assertEqual(list(EMS_Calls.objects.values_list("ems_id", flat=True)), [first.id])
        self.assertEqual(Current_emscall.objects.count(), 1)

    @override_settings(GGL_API_KEY="AIza-test-key")
    def test_dispatch_uses_google_drive_times(self):
        client = mock.Mock()
        client.geocode.return_value = [{"geometry": {"location": {"lat": CITY_HALL[0], "lng": CITY_HALL[1]}}}]
        # The farther ambulance (2) is quicker in traffic, so it should be sent.
        client.distance_matrix.return_value = {
            "rows": [
                {"elements": [{"status": "OK", "duration_in_traffic": {"value": 900}}]},
                {"elements": [{"status": "OK", "duration_in_traffic": {"value": 300}}]},
            ]
        }
        with mock.patch("map.dispatch.googlemaps.Client", return_value=client):
            response = post_call(self.client, "1 Dr Carlton B Goodlett Pl", follow=True)
        self.assertContains(response, "Ambulance #2 dispatched")
        self.assertContains(response, "ETA 5 min")
        self.assertEqual(Current_ambulance.objects.get(amb_id=2).AVAILABLE, 0)

    def test_no_available_ambulance(self):
        Current_ambulance.objects.update(AVAILABLE=0)
        response = post_call(self.client, "37.7793, -122.4193", follow=True)
        self.assertContains(response, "no ambulance is available")
        self.assertContains(response, "alert-warning")
        self.assertTrue(Current_emscall.objects.exists())

    def test_reactivate_ambulance(self):
        response = self.client.post(reverse("current_map"), {"amb-amb_id": "3", "amb_submit": ""}, follow=True)
        self.assertContains(response, "Ambulance #3 is back in service")
        self.assertEqual(Current_ambulance.objects.get(amb_id=3).AVAILABLE, 1)

    def test_cannot_reactivate_ambulance_in_service(self):
        response = self.client.post(reverse("current_map"), {"amb-amb_id": "1", "amb_submit": ""})
        self.assertContains(response, "Select a valid choice")


class LoadDataTests(TestCase):
    def test_loads_bundled_ambulances(self):
        out = StringIO()
        call_command("load_data", stdout=out)
        call_command("load_data", stdout=out)  # idempotent
        self.assertEqual(Current_ambulance.objects.count(), 10)
        self.assertIn("Loaded 10 ambulances", out.getvalue())

    def test_loading_predictions_twice_does_not_duplicate(self):
        path = Path(__file__).resolve().parents[3] / "data" / "ems_calls_predict_mod2.csv"
        call_command("load_data", predictions=str(path), stdout=StringIO())
        count = Predictions.objects.count()
        call_command("load_data", predictions=str(path), stdout=StringIO())
        self.assertEqual(Predictions.objects.count(), count)
        self.assertGreater(count, 0)
