from django.urls import path

from . import views

urlpatterns = [
    path('<slug:url_key>/', views.JudgeRoomView.as_view(), name='nsdcroom-judge'),
]
