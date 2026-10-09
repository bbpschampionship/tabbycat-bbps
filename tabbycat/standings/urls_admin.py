from django.shortcuts import redirect
from django.urls import include, path

from . import views


def _nsdc_track_standings(request, tournament_slug, **kwargs):
    # NSDC: speakers only, split by track (Primary/Junior/Senior)
    return redirect('nsdcroom-public-standings', tournament_slug=tournament_slug)


urlpatterns = [
    path('round/<int:round_seq>/', include([
        path('',
            _nsdc_track_standings,
            name='standings-index'),
        path('team/',
            _nsdc_track_standings,
            name='standings-team'),
        path('team/<slug:category>/',
            views.BreakCategoryStandingsView.as_view(),
            name='standings-break-category'),

        path('email/',
            views.EmailTeamStandingsView.as_view(),
            name='progress-email'),

        path('speaker/',
            _nsdc_track_standings,
            name='standings-speaker'),
        path('speaker/<slug:category>/',
            views.SpeakerCategoryStandingsView.as_view(),
            name='standings-speaker-category'),
        path('reply/',
            views.ReplyStandingsView.as_view(),
            name='standings-reply'),

        path('diversity/',
            views.DiversityStandingsView.as_view(),
            name='standings-diversity'),
    ])),
]
