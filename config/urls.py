from django.conf import settings
from django.contrib import admin
from django.shortcuts import render
from django.urls import include, path

from drf_yasg import openapi
from drf_yasg.views import get_schema_view

from elections import helpers


def index(request):
    return render(
        request,
        'index.html',
        {'BASE_URL': settings.BASE_URL, 'BASE_DOMAIN': settings.BASE_DOMAIN},
    )


schema_view = get_schema_view(
    openapi.Info(
        title="Michigan Elections API",
        default_version='0',
        description="Voter registration status and ballots for Michigan.",
    ),
    url=settings.BASE_URL,
)


urlpatterns = [
    path('api/', include('elections.urls')),
    path('admin/', admin.site.urls),
    path('grappelli/', include('grappelli.urls')),
    path('docs/', schema_view.with_ui('swagger')),
    path('', index),
]


if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [
        path('__debug__/', include(debug_toolbar.urls))
    ] + urlpatterns


if settings.REQUESTS_CACHE_EXPIRE_AFTER:
    helpers.enable_requests_cache(settings.REQUESTS_CACHE_EXPIRE_AFTER)
