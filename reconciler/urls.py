from django.urls import path
from reconciler.views import health_check

urlpatterns = [
    path("health/", health_check, name="health"),
]