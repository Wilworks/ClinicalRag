
# Registers every endpoint this API exposes.

from django.urls import path
from .views import ClinicalRAGView, ClinicalRAGStreamView, HealthCheckView
from .views import HealthCheckView, PDFExportView

urlpatterns = [
    # Standard REST endpoint — returns complete JSON when pipeline finishes.
   
    path("ask/", ClinicalRAGView.as_view(), name="ask"),

    # SSE streaming endpoint — powers the live progress UI.
    # Emits events as each pipeline stage completes.
    path("ask/stream/", ClinicalRAGStreamView.as_view(), name="ask-stream"),

    # Health check — HF Spaces pings this to verify the app is running.
    # Also useful to confirm the RAG engine loaded correctly at startup.
    path("health/", HealthCheckView.as_view(), name="health"),
    path("pdf/", PDFExportView.as_view(), name="pdf-export"),
]