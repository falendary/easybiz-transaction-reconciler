from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import path, include, reverse
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


def _admin_index(request, extra_context=None):
    return HttpResponseRedirect(reverse("admin:reconciler-dashboard"))


admin.site.index = _admin_index

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/", include("reconciler.urls")),
]
