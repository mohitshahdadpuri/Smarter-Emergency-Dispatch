from django.db import models


class Event_feed(models.Model):
    """Entries shown in the "Recent Events" table of the dispatcher console."""

    event_type = models.CharField(max_length=10)
    event_desc = models.CharField(max_length=80)
    unit = models.IntegerField(null=True)
    LAT = models.FloatField(null=True)
    LONG = models.FloatField(null=True)
    time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.event_desc


class Predictions(models.Model):
    """Forecast calls per ZIP code and hour; doubles as a cache of model output."""

    zcta = models.CharField(max_length=5)
    year = models.IntegerField()
    month = models.IntegerField()
    day_of_month = models.IntegerField()
    hour_of_day = models.IntegerField()
    day_of_year = models.IntegerField()
    week_of_year = models.IntegerField()
    day_of_week = models.IntegerField()
    is_weekend = models.BooleanField()
    call_counts = models.FloatField()


class Ambulance(models.Model):
    """History of ambulance positions and statuses."""

    amb_id = models.IntegerField()
    LAT = models.FloatField()
    LONG = models.FloatField()
    AVAILABLE = models.IntegerField()
    time = models.DateTimeField(auto_now_add=True)


class EMS_Calls(models.Model):
    """Calls that are no longer the current call."""

    ems_id = models.IntegerField(primary_key=True)
    addr = models.CharField(max_length=200)
    LAT = models.FloatField()
    LONG = models.FloatField()
    time = models.DateTimeField()


class Current_predictions(models.Model):
    """Forecast for the current hour, one row per ZIP code."""

    zcta = models.CharField(max_length=5)
    year = models.IntegerField()
    month = models.IntegerField()
    day_of_month = models.IntegerField()
    hour_of_day = models.IntegerField()
    day_of_year = models.IntegerField()
    week_of_year = models.IntegerField()
    day_of_week = models.IntegerField()
    is_weekend = models.BooleanField()
    call_counts = models.FloatField()

    def __str__(self):
        return self.zcta + "_" + str(self.call_counts)


class Current_ambulance(models.Model):
    """Current position of each ambulance. ``AVAILABLE`` is 1 when in service and idle."""

    amb_id = models.IntegerField(primary_key=True)
    LAT = models.FloatField()
    LONG = models.FloatField()
    AVAILABLE = models.IntegerField()

    def __str__(self):
        return f"Ambulance {self.amb_id}"


class Current_emscall(models.Model):
    """The call currently being dispatched (at most one row)."""

    addr = models.CharField(max_length=200)
    LAT = models.FloatField()
    LONG = models.FloatField()
    time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.addr
