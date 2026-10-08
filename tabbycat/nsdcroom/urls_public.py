from django.urls import path

from . import views

urlpatterns = [
    path('', views.PublicBatchesView.as_view(), name='nsdcroom-public-batches'),
    path('standings/', views.PublicStandingsView.as_view(), name='nsdcroom-public-standings'),
    path('<int:room_id>/', views.PublicBatchView.as_view(), name='nsdcroom-public-batch'),
]
