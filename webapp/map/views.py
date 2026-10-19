from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.clickjacking import xframe_options_sameorigin

from . import mapview, services
from .dispatch import GeocodingError
from .forms import CurrentAmbulanceForm, CurrentCallForm
from .models import Event_feed


@xframe_options_sameorigin
def current_map(request):
    """Dispatcher console: enter calls, reactivate ambulances, see recent events."""
    form = CurrentCallForm(prefix="call")
    form2 = CurrentAmbulanceForm(prefix="amb")

    if request.method == "POST" and "call_submit" in request.POST:
        form = CurrentCallForm(request.POST, prefix="call")
        if form.is_valid():
            try:
                messages.add_message(request, *services.handle_call(form.cleaned_data["addr"]))
            except GeocodingError as error:
                form.add_error("addr", str(error))
            else:
                return redirect("current_map")
    elif request.method == "POST" and "amb_submit" in request.POST:
        form2 = CurrentAmbulanceForm(request.POST, prefix="amb")
        if form2.is_valid():
            messages.success(request, services.activate_ambulance(form2.cleaned_data["amb_id"]))
            return redirect("current_map")

    recent_events_query = Event_feed.objects.order_by("-time")[:10]
    return render(
        request, "map/current_state.html", {"form": form, "form2": form2, "recent_events_query": recent_events_query}
    )


@xframe_options_sameorigin
def map_frame(request):
    """The folium map on its own, embedded by the console in an iframe."""
    return HttpResponse(mapview.build_map())
