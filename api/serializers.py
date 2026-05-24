# api/serializers.py
# Validates incoming request data before it touches the RAG engine.
# Think of this as the bouncer — bad requests never get past here.

from rest_framework import serializers


class ChatTurnSerializer(serializers.Serializer):
    question = serializers.CharField()
    answer = serializers.CharField()


class QuestionSerializer(serializers.Serializer):

    # The clinical question or conversational chat input.
    question = serializers.CharField(
        max_length=500,
        error_messages={
            "max_length": "Question is too long — please keep it under 500 characters.",
            "blank":      "Question cannot be empty.",
            "required":   "A question is required.",
        }
    )

    # Optional boolean — maps directly to the West Africa filter toggle in the UI.
    # Defaults to False so callers that don't send it get standard behaviour.
    west_africa_filter = serializers.BooleanField(default=False, required=False)

    # Optional boolean to search Wikipedia instead of PubMed.
    wikipedia_mode = serializers.BooleanField(default=False, required=False)

    # Optional list of previous conversation turns to provide memory.
    history = ChatTurnSerializer(many=True, required=False, default=[])