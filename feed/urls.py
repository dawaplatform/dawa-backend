from django.urls import path

from feed import views

urlpatterns = [
    path("home/", views.home_feed),
]
