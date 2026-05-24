"""
CanvasSession model — anonymous session-based (no User FK).
Tracks clinical context built up during a conversation.
"""
import uuid
from django.db import models


class CanvasSession(models.Model):
    session_key = models.CharField(max_length=40, db_index=True)
    session_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # Patient context: {age, weight, condition}
    patient = models.JSONField(default=dict)

    # Drugs mentioned across the conversation
    drugs = models.JSONField(default=list)

    # Contraindications flagged by the agent
    contraindications = models.JSONField(default=list)

    # Dosing decisions made
    decisions = models.JSONField(default=list)

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Canvas[{str(self.session_id)[:8]}]"

    def to_dict(self):
        return {
            "session_id": str(self.session_id),
            "patient": self.patient,
            "drugs": self.drugs,
            "contraindications": self.contraindications,
            "decisions": self.decisions,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
