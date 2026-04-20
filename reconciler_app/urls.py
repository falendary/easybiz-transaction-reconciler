from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


class _AdminIndexRedirect(RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return "/admin/reconciler/transaction/dashboard/"


admin.site.__class__.index = lambda self, request, extra_context=None: _AdminIndexRedirect.as_view()(request)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/", include("reconciler.urls")),
]
