"""
Canvas API views.
GET    /api/canvas/<session_id>/   — return canvas state
PATCH  /api/canvas/<session_id>/   — update canvas fields
DELETE /api/canvas/<session_id>/   — clear canvas

Also: POST /api/canvas/init/  — create or retrieve canvas for current session
"""
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import CanvasSession

ALLOWED_FIELDS = {"patient", "drugs", "contraindications", "decisions"}


def _ensure_session(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


class CanvasInitView(APIView):
    """POST /api/canvas/init/ — get or create a canvas for this session."""

    def post(self, request):
        session_key = _ensure_session(request)
        canvas, created = CanvasSession.objects.get_or_create(
            session_key=session_key,
            defaults={},
        )
        return Response(canvas.to_dict(), status=status.HTTP_200_OK)


class CanvasDetailView(APIView):

    def get(self, request, session_id):
        canvas = get_object_or_404(CanvasSession, session_id=session_id)
        return Response(canvas.to_dict(), status=status.HTTP_200_OK)

    def patch(self, request, session_id):
        canvas = get_object_or_404(CanvasSession, session_id=session_id)
        updated = False

        for field in ALLOWED_FIELDS:
            if field in request.data:
                setattr(canvas, field, request.data[field])
                updated = True

        if updated:
            canvas.save()

        return Response(canvas.to_dict(), status=status.HTTP_200_OK)

    def delete(self, request, session_id):
        canvas = get_object_or_404(CanvasSession, session_id=session_id)
        canvas.patient = {}
        canvas.drugs = []
        canvas.contraindications = []
        canvas.decisions = []
        canvas.save()
        return Response({"status": "cleared"}, status=status.HTTP_200_OK)
