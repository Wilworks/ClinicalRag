from django.urls import path
from .views import RetrievalQueryView, RetrievalRerunView

urlpatterns = [
    path("query/", RetrievalQueryView.as_view(), name="retrieval-query"),
    path("rerun/", RetrievalRerunView.as_view(), name="retrieval-rerun"),
]
