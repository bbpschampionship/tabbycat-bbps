from django.urls import path

from . import views

from django.shortcuts import redirect


def _nsdc_batch_rounds(request, tournament_slug, **kwargs):
    # NSDC: draws are browsed batch by batch
    return redirect('nsdcroom-public-rounds', tournament_slug=tournament_slug)


urlpatterns = [
    path('',
        _nsdc_batch_rounds,
        name='draw-public-current-rounds'),
    path('round/<int:round_seq>/',
        _nsdc_batch_rounds,
        name='draw-public-for-round'),
    path('sides/',
        views.PublicSideAllocationsView.as_view(),
        name='draw-public-side-allocations'),
]
