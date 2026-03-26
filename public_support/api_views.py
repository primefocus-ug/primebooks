from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action

from .models import SupportTicket
from .serializers import (
    SupportTicketSerializer,
    SupportTicketCreateSerializer
)


class SupportTicketViewSet(viewsets.ModelViewSet):
    queryset = SupportTicket.objects.all().order_by("-created_at")

    def get_serializer_class(self):
        if self.action == "create":
            return SupportTicketCreateSerializer
        return SupportTicketSerializer

    def perform_create(self, serializer):
        request = self.request

        ticket = serializer.save(
            ip_address=self.get_client_ip(),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            referrer=request.META.get("HTTP_REFERER", ""),
        )

        # Optional: email notification
        # send_ticket_notification.delay(ticket.ticket_id)

    def create(self, request, *args, **kwargs):
        """
        Override to match Django messages + return ticket number
        """
        response = super().create(request, *args, **kwargs)

        return Response({
            "message": "Support ticket created successfully",
            "ticket_number": response.data.get("ticket_number"),
            "data": response.data
        }, status=status.HTTP_201_CREATED)

    def get_client_ip(self):
        x_forwarded_for = self.request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0]
        return self.request.META.get("REMOTE_ADDR")

    # ✅ Extra actions (like buttons in admin)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        ticket = self.get_object()
        ticket.mark_resolved()
        return Response({"status": "resolved"})

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        ticket = self.get_object()
        ticket.mark_closed()
        return Response({"status": "closed"})