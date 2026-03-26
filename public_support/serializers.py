from rest_framework import serializers
from .models import SupportTicket


class SupportTicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportTicket
        fields = "__all__"
        read_only_fields = [
            "ticket_id",
            "ticket_number",
            "created_at",
            "updated_at",
            "first_response_at",
            "resolved_at",
            "closed_at",
            "response_time_minutes",
            "resolution_time_minutes",
        ]

class SupportTicketCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportTicket
        fields = [
            "name",
            "email",
            "phone",
            "company_name",
            "category",
            "subject",
            "message",
        ]