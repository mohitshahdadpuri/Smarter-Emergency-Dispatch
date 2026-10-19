import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from map.models import Current_ambulance, Predictions

DEFAULT_AMBULANCES = Path(__file__).resolve().parents[2] / "data" / "ambulances.csv"
INT_COLUMNS = (
    "year",
    "month",
    "day_of_month",
    "hour_of_day",
    "day_of_year",
    "week_of_year",
    "day_of_week",
)


def _rows(path):
    try:
        with open(path, newline="") as f:
            yield from csv.DictReader(f)
    except FileNotFoundError:
        raise CommandError(f"File not found: {path}")


class Command(BaseCommand):
    help = "Load ambulance positions and, optionally, precomputed hourly predictions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--ambulances",
            default=DEFAULT_AMBULANCES,
            help="CSV with AMB_ID, LAT, LONG and AVAILABLE columns (default: %(default)s)",
        )
        parser.add_argument(
            "--predictions",
            help="CSV in the format of data/ems_calls_predict_mod2.csv. Hours it covers are shown "
            "instead of the trained model's forecast.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        ambulances = 0
        for row in _rows(options["ambulances"]):
            Current_ambulance.objects.update_or_create(
                amb_id=int(row["AMB_ID"]),
                defaults={"LAT": float(row["LAT"]), "LONG": float(row["LONG"]), "AVAILABLE": int(row["AVAILABLE"])},
            )
            ambulances += 1
        self.stdout.write(f"Loaded {ambulances} ambulances")

        if options["predictions"]:
            batch = []
            for row in _rows(options["predictions"]):
                fields = {column: int(row[column]) for column in INT_COLUMNS}
                calls = row.get("call_counts", row.get("Call_counts"))
                batch.append(
                    Predictions(
                        zcta=row["zcta"],
                        is_weekend=row["is_weekend"].strip().lower() in ("true", "1", "t"),
                        call_counts=float(calls),
                        **fields,
                    )
                )
            # Replace any rows already stored for the hours in the file.
            hours = {(p.year, p.month, p.day_of_month, p.hour_of_day) for p in batch}
            for year, month, day, hour in hours:
                Predictions.objects.filter(year=year, month=month, day_of_month=day, hour_of_day=hour).delete()
            Predictions.objects.bulk_create(batch, batch_size=1000)
            self.stdout.write(f"Loaded {len(batch)} predictions")
