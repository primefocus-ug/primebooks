from django.db import connection
from django_tenants.utils import get_public_schema_name
import logging

logger = logging.getLogger(__name__)


def messaging_context(request):
    """
    Add messaging-related context to all templates.
    CRITICAL: Only queries tenant-specific models when in a tenant schema.
    """
    public_schema = get_public_schema_name()
    current_schema = connection.schema_name

    # Default context
    context = {
        'unread_messages_count': 0,
        'has_unread_messages': False,
    }

    # Only query tenant data if we're NOT in public schema
    if not current_schema or current_schema == public_schema:
        return context

    # We're in a tenant schema - safe to query Message model
    if request.user.is_authenticated:
        try:
            from messaging.models import Message

            # Get unread count
            unread_count = Message.objects.filter(
                conversation__participants__user=request.user,
                conversation__participants__is_active=True,
                is_deleted=False
            ).exclude(
                sender=request.user
            ).exclude(
                read_receipts__user=request.user
            ).count()

            context['unread_messages_count'] = unread_count
            context['has_unread_messages'] = unread_count > 0

        except Exception as e:
            logger.warning(
                f"Error in messaging context processor for schema '{current_schema}': {e}"
            )

    return context