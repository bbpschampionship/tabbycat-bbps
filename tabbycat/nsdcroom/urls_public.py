from django.urls import path

from . import views

urlpatterns = [
    path('', views.PublicHomeView.as_view(), name='nsdcroom-public-batches'),
    path('all/', views.PublicBatchesView.as_view(mode='batches'), name='nsdcroom-public-batch-list'),
    path('rounds/', views.PublicBatchesView.as_view(mode='rounds'), name='nsdcroom-public-rounds'),
    path('results/', views.PublicBatchesView.as_view(mode='results'), name='nsdcroom-public-results'),
    path('students/', views.PublicStudentsView.as_view(), name='nsdcroom-public-students'),
    path('judges/', views.PublicJudgesView.as_view(), name='nsdcroom-public-judges'),
    path('standings/', views.PublicStandingsView.as_view(), name='nsdcroom-public-standings'),
    path('students/<int:team_id>/', views.PublicStudentView.as_view(), name='nsdcroom-public-student'),
    path('<int:room_id>/', views.PublicBatchView.as_view(), name='nsdcroom-public-batch'),
]
