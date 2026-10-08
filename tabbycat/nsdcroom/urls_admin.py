from django.urls import path

from . import views

urlpatterns = [
    path('', views.AdminRoomsView.as_view(), name='nsdcroom-admin'),
]
