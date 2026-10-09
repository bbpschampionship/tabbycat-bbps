from django.urls import path

from . import admin_views as v

urlpatterns = [
    path('', v.OverviewView.as_view(), name='nsdcroom-admin'),
    path('batch/<int:room_id>/', v.BatchView.as_view(), name='nsdcroom-director-batch'),
    path('results/', v.ResultsView.as_view(), name='nsdcroom-director-results'),
    path('standings/', v.StandingsView.as_view(), name='nsdcroom-director-standings'),
    path('judges/', v.JudgesView.as_view(), name='nsdcroom-director-judges'),
    path('messages/', v.MessagesView.as_view(), name='nsdcroom-director-messages'),
    path('settings/', v.SettingsView.as_view(), name='nsdcroom-director-settings'),
]
