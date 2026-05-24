from django.urls import path
from .views import CanvasInitView, CanvasDetailView

urlpatterns = [
    path("init/", CanvasInitView.as_view(), name="canvas-init"),
    path("<uuid:session_id>/", CanvasDetailView.as_view(), name="canvas-detail"),
]
