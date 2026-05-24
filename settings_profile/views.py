"""
EvidanceSettings API views.
GET  /api/settings/  — return current session's settings (create defaults if none)
PATCH /api/settings/ — update one or more fields immediately (no Save button)
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import EvidanceSettings

ALLOWED_FIELDS = {
    "active_sources", "disease_focus", "region",
    "export_format", "canvas_persist", "theme", "show_confidence",
}


def _get_or_create_settings(request):
    """Get or create settings for the current anonymous session."""
    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key
    obj, _ = EvidanceSettings.objects.get_or_create(
        session_key=session_key,
        defaults={"active_sources": ["pubmed", "europepmc", "semanticscholar", "openalex"]},
    )
    return obj


class SettingsView(APIView):

    def get(self, request):
        obj = _get_or_create_settings(request)
        return Response(obj.to_dict(), status=status.HTTP_200_OK)

    def patch(self, request):
        obj = _get_or_create_settings(request)
        updated = False

        for field in ALLOWED_FIELDS:
            if field in request.data:
                setattr(obj, field, request.data[field])
                updated = True

        if updated:
            obj.save()

        return Response(obj.to_dict(), status=status.HTTP_200_OK)
