from django.contrib import admin

from .models import Current_ambulance, Current_emscall, EMS_Calls, Event_feed

admin.site.register(EMS_Calls)
admin.site.register(Current_emscall)
admin.site.register(Current_ambulance)
admin.site.register(Event_feed)
