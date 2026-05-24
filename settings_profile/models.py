"""
EvidanceSettings model — anonymous session-based (no User FK).
One settings record per Django session key.
"""
from django.db import models


class EvidanceSettings(models.Model):
    session_key = models.CharField(max_length=40, unique=True, db_index=True)

    # Source toggles — list of active source names
    active_sources = models.JSONField(default=list)

    # Disease focus multi-select
    disease_focus = models.JSONField(default=list)

    # Region: 'west_africa' | 'subsaharan' | 'pan_africa' | 'global'
    region = models.CharField(max_length=20, default="west_africa")

    # Export format: 'pdf' | 'link'
    export_format = models.CharField(max_length=10, default="pdf")

    # Whether canvas persists across sessions
    canvas_persist = models.BooleanField(default=True)

    # Theme: 'dark' | 'light'
    theme = models.CharField(max_length=10, default="dark")

    # Whether to show confidence display
    show_confidence = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "EvidAnce Settings"
        verbose_name_plural = "EvidAnce Settings"

    def __str__(self):
        return f"Settings[{self.session_key[:8]}...]"

    def to_dict(self):
        return {
            "active_sources": self.active_sources or _default_sources(),
            "disease_focus": self.disease_focus,
            "region": self.region,
            "export_format": self.export_format,
            "canvas_persist": self.canvas_persist,
            "theme": self.theme,
            "show_confidence": self.show_confidence,
        }


def _default_sources():
    return ["pubmed", "europepmc", "semanticscholar", "openalex"]
