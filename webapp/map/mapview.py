"""Render the dispatcher map: predicted demand, ambulances and the current call."""
import folium
import pandas as pd
from branca.colormap import linear

from . import placement
from .models import Current_ambulance, Current_emscall
from .services import current_predictions, local_hour

SF_CENTER = [37.7556, -122.4399]


def build_map():
    """Return the map as a complete HTML document."""
    predictions = current_predictions()
    regions = placement.load_regions().merge(predictions, on="zcta", how="left")
    regions["call_counts"] = pd.to_numeric(regions["call_counts"], errors="coerce").fillna(0.0).round(2)

    low, high = regions["call_counts"].min(), regions["call_counts"].max()
    colormap = linear.OrRd_09.scale(low, high if high > low else low + 1)
    colormap.caption = f"Predicted EMS calls per ZIP code, {local_hour():%m/%d/%Y %H:00 %Z}"

    sfmap = folium.Map(location=SF_CENTER, zoom_start=12)
    folium.GeoJson(
        regions.to_json(),
        name="Predicted calls",
        style_function=lambda feature: {
            "color": "black",
            "weight": 1.5,
            "fillColor": colormap(feature["properties"]["call_counts"]),
            "fillOpacity": 0.6,
        },
        tooltip=folium.GeoJsonTooltip(fields=["zcta", "call_counts"], aliases=["ZIP code", "Predicted calls"]),
    ).add_to(sfmap)
    colormap.add_to(sfmap)

    for ambulance in Current_ambulance.objects.all():
        if not (ambulance.LAT and ambulance.LONG):
            continue
        in_service = ambulance.AVAILABLE == 1
        folium.Marker(
            [ambulance.LAT, ambulance.LONG],
            icon=folium.Icon(icon="plus", color="blue" if in_service else "gray"),
            popup=f"Amb #: {ambulance.amb_id}",
            tooltip=f"Ambulance {ambulance.amb_id} ({'available' if in_service else 'out of service'})",
        ).add_to(sfmap)

    for call in Current_emscall.objects.all():
        folium.RegularPolygonMarker(
            [call.LAT, call.LONG], popup=f"EMS #: {call.id}", fill_color="red", number_of_sides=5, radius=10
        ).add_to(sfmap)

    folium.LayerControl().add_to(sfmap)
    return sfmap.get_root().render()
