from django import forms

from .models import Current_ambulance, Current_emscall


class CurrentCallForm(forms.ModelForm):
    """Address (or "lat, long") of the current emergency call."""

    class Meta:
        model = Current_emscall
        fields = ("addr",)
        labels = {"addr": "Address"}


class CurrentAmbulanceForm(forms.Form):
    """Ambulance that is back in service. Only out-of-service units are offered."""

    amb_id = forms.TypedChoiceField(coerce=int, label="Ambulance ID")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inactive = Current_ambulance.objects.filter(AVAILABLE=0).order_by("amb_id").values_list("amb_id", flat=True)
        self.fields["amb_id"].choices = [(amb_id, amb_id) for amb_id in inactive]
