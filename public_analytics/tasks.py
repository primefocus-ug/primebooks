from celery import shared_task
from django.utils import timezone
from django.db import models
from .models import PageView, Event, Conversion, VisitorSession
import user_agents
import logging

logger = logging.getLogger(__name__)


@shared_task
def track_pageview_async(url_path, visitor_id, session_id, request_meta, get_params):
    """Asynchronously track page view"""

    try:
        # Parse user agent
        user_agent_string = request_meta.get('HTTP_USER_AGENT', '')
        ua = user_agents.parse(user_agent_string)

        # Determine device type
        if ua.is_bot:
            device_type = 'bot'
        elif ua.is_mobile:
            device_type = 'mobile'
        elif ua.is_tablet:
            device_type = 'tablet'
        else:
            device_type = 'desktop'

        # Extract UTM parameters
        utm_params = {
            'utm_source': get_params.get('utm_source', ''),
            'utm_medium': get_params.get('utm_medium', ''),
            'utm_campaign': get_params.get('utm_campaign', ''),
            'utm_term': get_params.get('utm_term', ''),
            'utm_content': get_params.get('utm_content', ''),
        }

        # Create page view
        PageView.objects.create(
            url_path=url_path,
            visitor_id=visitor_id,
            session_id=session_id,
            ip_address=request_meta.get('REMOTE_ADDR', '127.0.0.1'),
            user_agent=user_agent_string[:500],
            browser=ua.browser.family,
            os=ua.os.family,
            device_type=device_type,
            referrer=request_meta.get('HTTP_REFERER', '')[:500],
            **utm_params
        )

        # Update session
        update_visitor_session(visitor_id, session_id, url_path, utm_params)

        logger.info(f"Tracked pageview: {url_path} for visitor {visitor_id[:8]}...")

    except Exception as e:
        logger.error(f"Failed to track pageview: {str(e)}", exc_info=True)


def update_visitor_session(visitor_id, session_id, current_page, utm_params):
    """Update or create visitor session"""

    # Only use UTM params that exist in VisitorSession model
    session_utm_params = {
        'utm_source': utm_params.get('utm_source', ''),
        'utm_medium': utm_params.get('utm_medium', ''),
        'utm_campaign': utm_params.get('utm_campaign', ''),
        'utm_term': utm_params.get('utm_term', ''),  # Include if you added the field
        'utm_content': utm_params.get('utm_content', ''),  # Include if you added the field
    }

    session, created = VisitorSession.objects.get_or_create(
        session_id=session_id,
        defaults={
            'visitor_id': visitor_id,
            'entry_page': current_page,
            **session_utm_params
        }
    )

    if not created:
        session.last_activity_at = timezone.now()
        session.exit_page = current_page
        session.pages_viewed += 1
        session.save(update_fields=['last_activity_at', 'exit_page', 'pages_viewed'])


@shared_task
def track_event_async(category, action, visitor_id, session_id, **kwargs):
    """Asynchronously track custom event"""

    try:
        Event.objects.create(
            category=category,
            action=action,
            visitor_id=visitor_id,
            session_id=session_id,
            **kwargs
        )

        # Update session event count
        VisitorSession.objects.filter(session_id=session_id).update(
            events_count=models.F('events_count') + 1
        )

        logger.info(f"Tracked event: {category} - {action}")

    except Exception as e:
        logger.error(f"Failed to track event: {str(e)}", exc_info=True)


@shared_task
def track_conversion_async(conversion_type, visitor_id, session_id, **kwargs):
    """Asynchronously track conversion"""

    try:
        Conversion.objects.create(
            conversion_type=conversion_type,
            visitor_id=visitor_id,
            session_id=session_id,
            **kwargs
        )

        # Mark session as converted
        VisitorSession.objects.filter(session_id=session_id).update(converted=True)

        logger.info(f"Tracked conversion: {conversion_type}")

    except Exception as e:
        logger.error(f"Failed to track conversion: {str(e)}", exc_info=True)


@shared_task
def generate_daily_stats(date=None):
    """
    Generate daily statistics.
    Run via Celery Beat daily at midnight.
    """
    from django.db.models import Count, Avg, Q
    from datetime import timedelta

    if date is None:
        date = timezone.now().date() - timedelta(days=1)  # Yesterday

    start = timezone.make_aware(timezone.datetime.combine(date, timezone.datetime.min.time()))
    end = start + timedelta(days=1)

    # Traffic stats
    unique_visitors = PageView.objects.filter(
        viewed_at__range=(start, end)
    ).values('visitor_id').distinct().count()

    total_pageviews = PageView.objects.filter(
        viewed_at__range=(start, end)
    ).count()

    total_sessions = VisitorSession.objects.filter(
        started_at__range=(start, end)
    ).count()

    # Engagement stats
    sessions_with_duration = VisitorSession.objects.filter(
        started_at__range=(start, end),
        duration_seconds__isnull=False
    )

    avg_session_duration = sessions_with_duration.aggregate(
        avg=Avg('duration_seconds')
    )['avg'] or 0

    avg_pages_per_session = VisitorSession.objects.filter(
        started_at__range=(start, end)
    ).aggregate(avg=Avg('pages_viewed'))['avg'] or 0

    # Bounce rate (sessions with only 1 page view)
    bounced_sessions = VisitorSession.objects.filter(
        started_at__range=(start, end),
        pages_viewed=1
    ).count()

    bounce_rate = (bounced_sessions / total_sessions * 100) if total_sessions > 0 else 0

    # Conversions
    signups_started = Conversion.objects.filter(
        converted_at__range=(start, end),
        conversion_type='SIGNUP_STARTED'
    ).count()

    signups_completed = Conversion.objects.filter(
        converted_at__range=(start, end),
        conversion_type='SIGNUP_COMPLETED'
    ).count()

    conversion_rate = (signups_completed / unique_visitors * 100) if unique_visitors > 0 else 0

    # Top pages
    top_pages = list(
        PageView.objects.filter(viewed_at__range=(start, end))
        .values('url_path')
        .annotate(views=Count('id'))
        .order_by('-views')[:10]
    )

    # Top sources
    top_sources = list(
        PageView.objects.filter(
            viewed_at__range=(start, end),
            utm_source__isnull=False
        )
        .exclude(utm_source='')
        .values('utm_source')
        .annotate(visits=Count('visitor_id', distinct=True))
        .order_by('-visits')[:10]
    )

    # Top campaigns
    top_campaigns = list(
        PageView.objects.filter(
            viewed_at__range=(start, end),
            utm_campaign__isnull=False
        )
        .exclude(utm_campaign='')
        .values('utm_campaign')
        .annotate(visits=Count('visitor_id', distinct=True))
        .order_by('-visits')[:10]
    )

    # Create or update daily stats
    from .models import DailyStats
    DailyStats.objects.update_or_create(
        date=date,
        defaults={
            'unique_visitors': unique_visitors,
            'total_pageviews': total_pageviews,
            'total_sessions': total_sessions,
            'avg_session_duration': avg_session_duration,
            'avg_pages_per_session': avg_pages_per_session,
            'bounce_rate': bounce_rate,
            'signups_started': signups_started,
            'signups_completed': signups_completed,
            'conversion_rate': conversion_rate,
            'top_pages': top_pages,
            'top_sources': top_sources,
            'top_campaigns': top_campaigns,
        }
    )

    logger.info(f"Generated daily stats for {date}")