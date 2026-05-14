from django.urls import path

from .views import LiveLogStreamView

app_name = "netbox_live_log"

urlpatterns = [
    path("stream/<str:job_id>/", LiveLogStreamView.as_view(), name="stream"),
]
