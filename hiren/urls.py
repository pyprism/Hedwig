from django.urls import path, re_path, include
from django.conf import settings

urls = [
    path(
        "api-auth/", include("rest_framework.urls")
    ),  # For DRF's browsable API login/logout
]

if settings.DEBUG:
    import debug_toolbar

    dj_toolbar = [re_path(r"^__debug__/", include(debug_toolbar.urls))]
    urlpatterns = dj_toolbar + urls
else:
    urlpatterns = urls
