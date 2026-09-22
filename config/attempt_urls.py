from django.urls import path

from apps.attempts import views

app_name = "attempts"

urlpatterns = [
    path("", views.start, name="start"),
    path("mine/", views.my_attempts, name="mine"),
    path("claim/", views.claim, name="claim"),
    path("<int:pk>/answers/", views.save, name="save"),
    path("<int:pk>/submit/", views.submit, name="submit"),
    path("<int:pk>/review/", views.review, name="review"),
]
