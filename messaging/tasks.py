from celery import shared_task
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from company.models import Company
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from django_tenants.utils import schema_context
from django_tenants.utils import schema_context, get_tenant_model
from .models import (
    Message, Conversation, ConversationParticipant,
    MessageSearchIndex
)
from django.contrib.auth import get_user_model
from asgiref.sync import async_to_sync
from django.db.models import Count, Sum
from django.utils import timezone
from celery import shared_task
from django_tenants.utils import schema_context
from django.utils import timezone
from datetime import timedelta
import logging


# ✅ Import your real tenant model here
from company.models import Company       # <-- change to your real model

# ✅ Import messaging models outside the task (Celery will load faster)
from messaging.models import Message, Conversation
from django.core.cache import cache




User = get_user_model()
logger = logging.getLogger(__name__)


@shared_task
def send_message_notifications(message_id, schema_name=None):
    if not schema_name:
        from django.db import connection
        schema_name = connection.schema_name

    if not schema_name or schema_name == 'public':
        logger.error(f"Cannot send notifications for message {message_id}: No tenant schema provided")
        return

    try:
        with schema_context(schema_name):
            from messaging.models import Message, ConversationParticipant
            from django.core.cache import cache
            from messaging.tasks import send_message_email_notification, send_push_notification

            message = Message.objects.select_related('sender', 'conversation').get(id=message_id)

            participants = ConversationParticipant.objects.filter(
                conversation=message.conversation,
                is_active=True
            ).exclude(user=message.sender).select_related('user')

            for participant in participants:
                # Skip online users
                cache_key = f'user_online_{schema_name}_{participant.user.id}'
                if cache.get(cache_key):
                    continue

                if participant.email_notifications:
                    send_message_email_notification.delay(participant.user.id, message.id, schema_name)

                if participant.push_notifications:
                    send_push_notification.delay(participant.user.id, message.id, schema_name)

            logger.info(f"Sent notifications for message {message_id} in tenant {schema_name}")

    except Exception as e:
        logger.error(f"Error sending notifications for message {message_id}: {e}", exc_info=True)


@shared_task
def send_message_email_notification(user_id, message_id, schema_name):
    try:
        from django.core.mail import send_mail
        from django.template.loader import render_to_string
        from django.conf import settings
        from django_tenants.utils import schema_context, get_tenant_model

        with schema_context(schema_name):

            from accounts.models import CustomUser
            from messaging.models import Message

            user = CustomUser.objects.get(id=user_id)
            message = Message.objects.select_related('sender', 'conversation').get(id=message_id)

            # Conversation name
            conv_name = (
                message.conversation.name or
                f"Chat with {message.sender.get_full_name() or message.sender.username}"
            )

            # Company name for branding
            company_name = (
                getattr(user, 'company', None).display_name
                if hasattr(user, 'company')
                else settings.SITE_NAME
            )

            # ✅ Get tenant domain dynamically
            TenantModel = get_tenant_model()
            tenant = TenantModel.objects.get(schema_name=schema_name)

            # ✅ Preferred: Tenant has a "domain_url" field (recommended)
            if hasattr(tenant, "domain_url") and tenant.domain_url:
                tenant_url = tenant.domain_url

            # ✅ Fallback: Get from domain model (common in django-tenants projects)
            elif hasattr(tenant, "domains") and tenant.domains.exists():
                tenant_url = tenant.domains.first().domain  # e.g. carol.localhost
                tenant_url = f"https://{tenant_url}"

            # ✅ Last fallback
            else:
                tenant_url = settings.SITE_URL  # Avoid breaks

            # Build URL for the user
            view_url = f"{tenant_url}/messaging/{message.conversation.id}"

            html_message = render_to_string('messaging/email/new_message.html', {
                'user': user,
                'sender': message.sender,
                'conversation': message.conversation,
                'conversation_name': conv_name,
                'message_preview': '[Encrypted message - view in app]',
                'company_name': company_name,
                'view_url': view_url
            })

            send_mail(
                subject=f'New message from {message.sender.get_full_name() or message.sender.username}',
                message='',
                html_message=html_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,
            )

            logger.info(f"Sent email notification to {user.email} for message {message_id}")

    except Exception as e:
        logger.error(f"Error sending email notification: {e}", exc_info=True)

@shared_task
def send_push_notification(user_id, message_id, schema_name):
    try:
        with schema_context(schema_name):
            from accounts.models import CustomUser
            from messaging.models import Message

            user = CustomUser.objects.get(id=user_id)
            message = Message.objects.select_related('sender', 'conversation').get(id=message_id)

            notification_data = {
                'title': f'New message from {message.sender.get_full_name() or message.sender.username}',
                'body': 'You have a new message',
                'data': {
                    'type': 'new_message',
                    'conversation_id': message.conversation.id,
                    'message_id': message.id,
                    'tenant': schema_name
                }
            }

            # TODO: replace this with your real push service
            logger.info(f"Would send push notification to {user.email}: {notification_data}")

    except Exception as e:
        logger.error(f"Error sending push notification: {e}", exc_info=True)


@shared_task
def update_search_index(message_id, decrypted_content, schema_name=None):
    try:
        from messaging.models import Message, MessageSearchIndex

        if not schema_name:
            message = Message.objects.select_related('conversation').get(id=message_id)
            schema_name = getattr(message.conversation, 'tenant', None)
            schema_name = schema_name.schema_name if schema_name else 'public'

        with schema_context(schema_name):
            message = Message.objects.select_related('sender', 'conversation').get(id=message_id)

            # Extract keywords
            words = decrypted_content.lower().split()
            stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for'}
            keywords = ' '.join({w for w in words if len(w) > 3 and w not in stop_words})

            MessageSearchIndex.objects.update_or_create(
                message=message,
                defaults={
                    'keywords': keywords[:1000],
                    'sender_name': message.sender.username,
                    'conversation_id': message.conversation.id,
                    'created_at': message.created_at
                }
            )

            logger.debug(f"Updated search index for message {message_id} in tenant {schema_name}")

    except Exception as e:
        logger.error(f"Error updating search index for message {message_id}: {e}", exc_info=True)


@shared_task
def cleanup_old_typing_indicators():
    from django.utils import timezone
    from datetime import timedelta
    from messaging.models import TypingIndicator
    from django_tenants.utils import get_tenant_model

    cutoff = timezone.now() - timedelta(seconds=10)
    Company = get_tenant_model()
    total_deleted = 0

    for company in Company.objects.filter(is_active=True):
        try:
            with schema_context(company.schema_name):
                deleted_count = TypingIndicator.objects.filter(
                    started_at__lt=cutoff
                ).delete()[0]
                total_deleted += deleted_count
        except Exception as e:
            logger.error(f"Error cleaning typing indicators in tenant {company.schema_name}: {e}", exc_info=True)

    logger.info(f"Cleaned up {total_deleted} expired typing indicators across all tenants")


@shared_task
def generate_message_analytics():
    today = timezone.now().date()
    yesterday = today - timedelta(days=1)

    # ✅ iterate through all active tenants
    for company in Company.objects.filter(is_active=True):
        try:
            # ✅ apply schema context per tenant
            with schema_context(company.schema_name):

                message_count = Message.objects.filter(
                    created_at__date=yesterday
                ).count()

                active_conversations = Conversation.objects.filter(
                    messages__created_at__date=yesterday
                ).distinct().count()

                active_users = Message.objects.filter(
                    created_at__date=yesterday
                ).values('sender').distinct().count()

                analytics = {
                    'messages': message_count,
                    'conversations': active_conversations,
                    'users': active_users,
                    'date': yesterday.isoformat(),
                }

                # ✅ Log analytics
                logger.info(
                    f"[{company.schema_name}] Analytics for {yesterday}: "
                    f"{message_count} messages – {active_conversations} conversations – "
                    f"{active_users} users"
                )

                # ✅ Store in cache using schema_name to isolate tenants
                cache.set(
                    f'messaging_analytics_{company.schema_name}_{yesterday}',
                    analytics,
                    timeout=86400 * 30  # store for 30 days
                )

        except Exception as e:
            logger.error(
                f"Error generating analytics for tenant {company.schema_name}: {e}",
                exc_info=True
            )



@shared_task
def archive_old_messages(days=365):
    cutoff_date = timezone.now() - timedelta(days=days)
    total_archived = 0

    for company in Company.objects.filter(is_active=True):
        try:
            with schema_context(company.schema_name):

                # ✅ Only archive conversations with retention policy
                conversations = Conversation.objects.filter(
                    message_retention_days__gt=0
                )

                tenant_archived = 0

                for conv in conversations:
                    conv_cutoff = timezone.now() - timedelta(days=conv.message_retention_days)

                    old_messages = Message.objects.filter(
                        conversation=conv,
                        created_at__lt=conv_cutoff,
                        is_deleted=False
                    )

                    archived_count = old_messages.count()

                    if archived_count > 0:
                        old_messages.update(
                            is_deleted=True,
                            deleted_at=timezone.now()
                        )
                        tenant_archived += archived_count
                        total_archived += archived_count

                logger.info(
                    f"[{company.schema_name}] Archived {tenant_archived} messages"
                )

        except Exception as e:
            logger.error(
                f"Error archiving messages for tenant {company.schema_name}: {e}",
                exc_info=True
            )

    logger.info(f"Archived {total_archived} messages across all tenants")



def search_messages(user_id, search_params, schema_name=None):
    from django.contrib.auth import get_user_model
    from messaging.models import ConversationParticipant, MessageSearchIndex
    from django_tenants.utils import schema_context

    User = get_user_model()

    def _search():
        user = User.objects.get(id=user_id)
        query = search_params['query'].lower()

        accessible_conversations = ConversationParticipant.objects.filter(
            user=user,
            is_active=True
        ).values_list('conversation_id', flat=True)

        search_queryset = MessageSearchIndex.objects.filter(
            conversation_id__in=accessible_conversations,
            keywords__icontains=query
        )

        if search_params.get('conversation_id'):
            search_queryset = search_queryset.filter(conversation_id=search_params['conversation_id'])
        if search_params.get('from_date'):
            search_queryset = search_queryset.filter(created_at__gte=search_params['from_date'])
        if search_params.get('to_date'):
            search_queryset = search_queryset.filter(created_at__lte=search_params['to_date'])
        if search_params.get('sender_id'):
            sender = User.objects.get(id=search_params['sender_id'])
            search_queryset = search_queryset.filter(sender_name=sender.username)

        return list(search_queryset.values_list('message_id', flat=True)[:100])

    if schema_name:
        with schema_context(schema_name):
            return _search()
    else:
        return _search()


@shared_task
def cleanup_deleted_attachments():
    """
    Clean up file attachments for deleted messages

    TENANT-AWARE: Cleans files across all tenants

    Run weekly
    """
    from django.utils import timezone
    from datetime import timedelta
    from .models import MessageAttachment
    import os

    # Delete attachments for messages deleted > 30 days ago
    cutoff_date = timezone.now() - timedelta(days=30)
    Company = get_tenant_model()
    total_deleted = 0

    for company in Company.objects.filter(is_active=True):
        try:
            with schema_context(company.schema_name):
                # Find attachments for deleted messages
                attachments = MessageAttachment.objects.filter(
                    message__is_deleted=True,
                    message__deleted_at__lt=cutoff_date
                )

                count = 0
                for attachment in attachments:
                    # Delete physical file
                    try:
                        if attachment.encrypted_file:
                            attachment.encrypted_file.delete(save=False)
                        if attachment.thumbnail:
                            attachment.thumbnail.delete(save=False)
                        attachment.delete()
                        count += 1
                    except Exception as e:
                        logger.error(f"Error deleting attachment {attachment.id}: {e}")

                total_deleted += count
                logger.info(f"Deleted {count} attachments for tenant {company.schema_name}")

        except Exception as e:
            logger.error(f"Error cleaning attachments for tenant {company.schema_name}: {e}")

    logger.info(f"Deleted {total_deleted} attachments across all tenants")



@shared_task
def broadcast_announcement(announcement_id):
    """
    Broadcast system announcement to all targeted users

    Handles:
    - In-app notifications via WebSocket
    - Email notifications
    - Cross-tenant broadcasting
    """
    from .models import SystemAnnouncement, AnnouncementRead

    try:
        announcement = SystemAnnouncement.objects.get(id=announcement_id)
    except SystemAnnouncement.DoesNotExist:
        logger.error(f"Announcement {announcement_id} not found")
        return

    # Get target users
    users = User.objects.filter(is_active=True)

    # Filter by roles if specified
    if announcement.target_user_roles:
        role_filter = Q()
        for role in announcement.target_user_roles:
            role_filter |= Q(role=role)
        users = users.filter(role_filter)

    # Get channel layer for WebSocket
    channel_layer = get_channel_layer()

    # Track sent count
    sent_count = 0
    email_sent_count = 0

    for user in users:
        try:
            # Send in-app notification via WebSocket
            if announcement.show_in_app:
                async_to_sync(channel_layer.group_send)(
                    f'user_{user.id}',
                    {
                        'type': 'system_announcement',
                        'announcement': {
                            'id': announcement.id,
                            'title': announcement.title,
                            'message': announcement.message,
                            'announcement_type': announcement.announcement_type,
                            'priority': announcement.priority,
                            'is_dismissible': announcement.is_dismissible,
                            'action_text': announcement.action_text,
                            'action_url': announcement.action_url,
                        }
                    }
                )
                sent_count += 1

            # Send email notification
            if announcement.send_email and user.email:
                send_announcement_email.delay(announcement.id, user.id)
                email_sent_count += 1

        except Exception as e:
            logger.error(f"Error sending announcement to user {user.id}: {e}")
            continue

    # Mark as sent
    announcement.mark_as_sent()

    logger.info(
        f"Announcement {announcement.id} sent to {sent_count} users "
        f"({email_sent_count} emails queued)"
    )

    return {
        'announcement_id': announcement_id,
        'users_notified': sent_count,
        'emails_queued': email_sent_count
    }


@shared_task
def send_announcement_email(announcement_id, user_id):
    """
    Send announcement email to specific user
    """
    from .models import SystemAnnouncement

    try:
        announcement = SystemAnnouncement.objects.get(id=announcement_id)
        user = User.objects.get(id=user_id)

        if not user.email:
            return

        # Render email
        subject = f"[{announcement.get_announcement_type_display()}] {announcement.title}"

        html_message = render_to_string('messaging/email/announcement.html', {
            'user': user,
            'announcement': announcement,
            'site_url': settings.SITE_URL if hasattr(settings, 'SITE_URL') else 'http://localhost:8000'
        })

        send_mail(
            subject=subject,
            message=announcement.message,  # Plain text fallback
            html_message=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True
        )

        logger.info(f"Announcement email sent to {user.email}")

    except Exception as e:
        logger.error(f"Error sending announcement email: {e}")


@shared_task
def process_scheduled_announcements():
    """
    Check for scheduled announcements and send them
    Run this task every 5 minutes via Celery Beat
    """
    from .models import SystemAnnouncement
    from django.utils import timezone

    now = timezone.now()

    # Get announcements scheduled for now or past that haven't been sent
    announcements = SystemAnnouncement.objects.filter(
        scheduled_for__lte=now,
        is_sent=False
    )

    for announcement in announcements:
        broadcast_announcement.delay(announcement.id)
        logger.info(f"Triggered scheduled announcement: {announcement.id}")

    return f"Processed {announcements.count()} scheduled announcements"



@shared_task
def cleanup_old_statistics(days=90):
    """
    Clean up old statistics records for each tenant.
    Keep only last `days` days (default 90 days).
    """
    from .models import MessagingStatistics
    cutoff_date = timezone.now().date() - timedelta(days=days)
    TenantModel = get_tenant_model()

    for tenant in TenantModel.objects.exclude(schema_name='public'):
        try:
            with schema_context(tenant.schema_name):
                deleted_count = MessagingStatistics.objects.filter(
                    date__lt=cutoff_date
                ).delete()[0]

                logger.info(f"[{tenant.schema_name}] Cleaned up {deleted_count} old statistics records")
        except Exception as e:
            logger.error(f"[{tenant.schema_name}] Error cleaning up statistics: {e}")

    return f"Cleanup completed for all tenants older than {cutoff_date}"

@shared_task
def send_admin_digest_email(admin_user_id):
    yesterday = timezone.now().date() - timedelta(days=1)

    # Loop through all tenant schemas
    for company in Company.objects.exclude(schema_name='public'):
        with schema_context(company.schema_name):
            try:
                from accounts.models import CustomUser
                from messaging.models import MessagingStatistics, Conversation

                # Fetch tenant-specific admin user
                admin = CustomUser.objects.get(id=admin_user_id)
                if not admin.email:
                    continue

                # Get yesterday's stats
                stats = MessagingStatistics.objects.filter(
                    date=yesterday,
                    tenant_id=company.company_id
                ).first()

                # Recent conversations
                recent_conversations = Conversation.objects.filter(
                    created_at__date=yesterday
                ).select_related('created_by')[:10]

                html_message = render_to_string('messaging/email/admin_digest.html', {
                    'admin': admin,
                    'stats': stats,
                    'yesterday': yesterday,
                    'recent_conversations': recent_conversations,
                    'site_url': getattr(settings, 'SITE_URL', 'http://localhost:8000'),
                    'company': company,
                })

                send_mail(
                    subject=f"Messaging Digest - {yesterday.strftime('%B %d, %Y')}",
                    message=f"Daily messaging digest for {yesterday}",
                    html_message=html_message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[admin.email],
                    fail_silently=True
                )

                logger.info(f"Admin digest sent for {company.schema_name} to {admin.email}")

            except Exception as e:
                logger.error(f"Error sending digest for {company.schema_name}: {e}", exc_info=True)


