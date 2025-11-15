from django.views import View
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from .tasks import track_event_async
import json
from django.views.generic import TemplateView
from django.db.models import Count, Avg, Sum, Q, F
from django.db import models
from django.db.models.functions import TruncDate, TruncHour
from django.utils import timezone
from django.http import JsonResponse
from datetime import timedelta, datetime
from .models import PageView, Event, Conversion, VisitorSession, DailyStats
import json
from django.shortcuts import redirect
from django.urls import reverse


class PublicStaffRequiredMixin:
    """Require public staff user authentication"""

    def dispatch(self, request, *args, **kwargs):
        if not hasattr(request, 'public_staff_user'):
            return redirect(reverse('public_admin:login') + f'?next={request.path}')
        return super().dispatch(request, *args, **kwargs)


class AnalyticsDashboardView(PublicStaffRequiredMixin, TemplateView):
    """Main analytics dashboard"""
    template_name = 'public_analytics/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Date range (default: last 30 days)
        days = int(self.request.GET.get('days', 30))
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        # Overview Stats
        context['overview'] = self.get_overview_stats(start_date, end_date)

        # Traffic trends
        context['traffic_trend'] = self.get_traffic_trend(start_date, end_date)

        # Top pages
        context['top_pages'] = self.get_top_pages(start_date, end_date, limit=10)

        # Top sources
        context['top_sources'] = self.get_top_sources(start_date, end_date, limit=10)

        # Recent conversions
        context['recent_conversions'] = Conversion.objects.all()[:10]

        # Device breakdown
        context['devices'] = self.get_device_breakdown(start_date, end_date)

        # Active filters
        context['days'] = days
        context['start_date'] = start_date
        context['end_date'] = end_date

        return context

    def get_overview_stats(self, start_date, end_date):
        """Get key metrics for overview cards"""

        # Calculate previous period for comparison
        period_length = (end_date - start_date).days
        prev_start = start_date - timedelta(days=period_length)
        prev_end = start_date

        current_stats = {
            'visitors': PageView.objects.filter(
                viewed_at__range=(start_date, end_date)
            ).values('visitor_id').distinct().count(),

            'pageviews': PageView.objects.filter(
                viewed_at__range=(start_date, end_date)
            ).count(),

            'sessions': VisitorSession.objects.filter(
                started_at__range=(start_date, end_date)
            ).count(),

            'conversions': Conversion.objects.filter(
                converted_at__range=(start_date, end_date)
            ).count(),

            'avg_session_duration': VisitorSession.objects.filter(
                started_at__range=(start_date, end_date),
                duration_seconds__isnull=False
            ).aggregate(avg=Avg('duration_seconds'))['avg'] or 0,

            'avg_pages_per_session': VisitorSession.objects.filter(
                started_at__range=(start_date, end_date)
            ).aggregate(avg=Avg('pages_viewed'))['avg'] or 0,
        }

        # Previous period stats for comparison
        prev_stats = {
            'visitors': PageView.objects.filter(
                viewed_at__range=(prev_start, prev_end)
            ).values('visitor_id').distinct().count(),

            'pageviews': PageView.objects.filter(
                viewed_at__range=(prev_start, prev_end)
            ).count(),

            'sessions': VisitorSession.objects.filter(
                started_at__range=(prev_start, prev_end)
            ).count(),

            'conversions': Conversion.objects.filter(
                converted_at__range=(prev_start, prev_end)
            ).count(),
        }

        # Calculate percentage changes
        for key in ['visitors', 'pageviews', 'sessions', 'conversions']:
            current = current_stats[key]
            previous = prev_stats[key]

            if previous > 0:
                change = ((current - previous) / previous) * 100
            else:
                change = 100 if current > 0 else 0

            current_stats[f'{key}_change'] = round(change, 1)

        # Conversion rate
        if current_stats['visitors'] > 0:
            current_stats['conversion_rate'] = round(
                (current_stats['conversions'] / current_stats['visitors']) * 100, 2
            )
        else:
            current_stats['conversion_rate'] = 0

        return current_stats

    def get_traffic_trend(self, start_date, end_date):
        """Get daily traffic trend data"""

        trend = PageView.objects.filter(
            viewed_at__range=(start_date, end_date)
        ).annotate(
            date=TruncDate('viewed_at')
        ).values('date').annotate(
            visitors=Count('visitor_id', distinct=True),
            pageviews=Count('id')
        ).order_by('date')

        return list(trend)

    def get_top_pages(self, start_date, end_date, limit=10):
        """Get most viewed pages"""

        return PageView.objects.filter(
            viewed_at__range=(start_date, end_date)
        ).values('url_path').annotate(
            views=Count('id'),
            unique_visitors=Count('visitor_id', distinct=True)
        ).order_by('-views')[:limit]

    def get_top_sources(self, start_date, end_date, limit=10):
        """Get top traffic sources"""

        sources = PageView.objects.filter(
            viewed_at__range=(start_date, end_date)
        ).exclude(
            utm_source=''
        ).values('utm_source', 'utm_medium', 'utm_campaign').annotate(
            visitors=Count('visitor_id', distinct=True),
            sessions=Count('session_id', distinct=True)
        ).order_by('-visitors')[:limit]

        return list(sources)

    def get_device_breakdown(self, start_date, end_date):
        """Get device type breakdown"""

        devices = PageView.objects.filter(
            viewed_at__range=(start_date, end_date)
        ).values('device_type').annotate(
            count=Count('visitor_id', distinct=True)
        ).order_by('-count')

        return list(devices)


class RealtimeAnalyticsView(PublicStaffRequiredMixin, TemplateView):
    """Real-time analytics view"""
    template_name = 'public_analytics/realtime.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Last 30 minutes
        time_threshold = timezone.now() - timedelta(minutes=30)

        # Active visitors (viewed in last 5 minutes)
        active_threshold = timezone.now() - timedelta(minutes=5)
        context['active_visitors'] = PageView.objects.filter(
            viewed_at__gte=active_threshold
        ).values('visitor_id').distinct().count()

        # Recent pageviews
        context['recent_pageviews'] = PageView.objects.filter(
            viewed_at__gte=time_threshold
        ).select_related().order_by('-viewed_at')[:50]

        # Active pages
        context['active_pages'] = PageView.objects.filter(
            viewed_at__gte=time_threshold
        ).values('url_path').annotate(
            views=Count('id')
        ).order_by('-views')[:10]

        # Minute-by-minute traffic
        context['minute_traffic'] = self.get_minute_traffic(time_threshold)

        return context

    def get_minute_traffic(self, start_time):
        """Get traffic for each minute"""

        traffic = PageView.objects.filter(
            viewed_at__gte=start_time
        ).annotate(
            minute=TruncHour('viewed_at')  # Can use TruncMinute if available
        ).values('minute').annotate(
            views=Count('id')
        ).order_by('minute')

        return list(traffic)


class ConversionsView(PublicStaffRequiredMixin, TemplateView):
    """Conversion tracking and funnel analysis"""
    template_name = 'public_analytics/conversions.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        days = int(self.request.GET.get('days', 30))
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        # Conversion overview
        context['total_conversions'] = Conversion.objects.filter(
            converted_at__range=(start_date, end_date)
        ).count()

        # Conversions by type
        context['conversions_by_type'] = Conversion.objects.filter(
            converted_at__range=(start_date, end_date)
        ).values('conversion_type').annotate(
            count=Count('id')
        ).order_by('-count')

        # Conversion trend
        context['conversion_trend'] = Conversion.objects.filter(
            converted_at__range=(start_date, end_date)
        ).annotate(
            date=TruncDate('converted_at')
        ).values('date').annotate(
            conversions=Count('id')
        ).order_by('date')

        # Recent conversions
        context['recent_conversions'] = Conversion.objects.filter(
            converted_at__range=(start_date, end_date)
        ).order_by('-converted_at')[:50]

        # Top converting sources
        context['top_sources'] = Conversion.objects.filter(
            converted_at__range=(start_date, end_date)
        ).exclude(utm_source='').values('utm_source', 'utm_campaign').annotate(
            conversions=Count('id')
        ).order_by('-conversions')[:10]

        # Conversion rate by source
        total_visitors = PageView.objects.filter(
            viewed_at__range=(start_date, end_date)
        ).values('visitor_id').distinct().count()

        context['conversion_rate'] = round(
            (context['total_conversions'] / total_visitors * 100) if total_visitors > 0 else 0,
            2
        )

        context['days'] = days
        context['start_date'] = start_date
        context['end_date'] = end_date

        return context


class EventsView(PublicStaffRequiredMixin, TemplateView):
    """Event tracking view"""
    template_name = 'public_analytics/events.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        days = int(self.request.GET.get('days', 30))
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        # Total events
        context['total_events'] = Event.objects.filter(
            occurred_at__range=(start_date, end_date)
        ).count()

        # Events by category
        context['events_by_category'] = Event.objects.filter(
            occurred_at__range=(start_date, end_date)
        ).values('category').annotate(
            count=Count('id')
        ).order_by('-count')

        # Top events
        context['top_events'] = Event.objects.filter(
            occurred_at__range=(start_date, end_date)
        ).values('category', 'action').annotate(
            count=Count('id')
        ).order_by('-count')[:20]

        # Event trend
        context['event_trend'] = Event.objects.filter(
            occurred_at__range=(start_date, end_date)
        ).annotate(
            date=TruncDate('occurred_at')
        ).values('date').annotate(
            events=Count('id')
        ).order_by('date')

        # Recent events
        context['recent_events'] = Event.objects.filter(
            occurred_at__range=(start_date, end_date)
        ).order_by('-occurred_at')[:50]

        context['days'] = days
        context['start_date'] = start_date
        context['end_date'] = end_date

        return context


class SourcesView(PublicStaffRequiredMixin, TemplateView):
    """Traffic sources and campaigns view"""
    template_name = 'public_analytics/sources.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        days = int(self.request.GET.get('days', 30))
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        # UTM Sources
        context['utm_sources'] = PageView.objects.filter(
            viewed_at__range=(start_date, end_date)
        ).exclude(utm_source='').values('utm_source', 'utm_medium').annotate(
            visitors=Count('visitor_id', distinct=True),
            pageviews=Count('id'),
            sessions=Count('session_id', distinct=True)
        ).order_by('-visitors')

        # Campaigns
        context['campaigns'] = PageView.objects.filter(
            viewed_at__range=(start_date, end_date)
        ).exclude(utm_campaign='').values(
            'utm_campaign', 'utm_source', 'utm_medium'
        ).annotate(
            visitors=Count('visitor_id', distinct=True),
            pageviews=Count('id'),
            sessions=Count('session_id', distinct=True)
        ).order_by('-visitors')

        # Referrers (non-UTM)
        context['referrers'] = PageView.objects.filter(
            viewed_at__range=(start_date, end_date),
            utm_source=''
        ).exclude(referrer='').values('referrer').annotate(
            visitors=Count('visitor_id', distinct=True),
            pageviews=Count('id')
        ).order_by('-visitors')[:20]

        # Direct traffic
        context['direct_traffic'] = PageView.objects.filter(
            viewed_at__range=(start_date, end_date),
            utm_source='',
            referrer=''
        ).values('visitor_id').distinct().count()

        context['days'] = days
        context['start_date'] = start_date
        context['end_date'] = end_date

        return context


class PagesView(PublicStaffRequiredMixin, TemplateView):
    """Page performance view"""
    template_name = 'public_analytics/pages.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        days = int(self.request.GET.get('days', 30))
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        # All pages performance
        context['pages'] = PageView.objects.filter(
            viewed_at__range=(start_date, end_date)
        ).values('url_path').annotate(
            pageviews=Count('id'),
            unique_visitors=Count('visitor_id', distinct=True),
            avg_time=Avg('time_on_page_seconds')
        ).order_by('-pageviews')

        # Entry pages with bounce rate calculation
        from django.db.models import Case, When, FloatField

        context['entry_pages'] = VisitorSession.objects.filter(
            started_at__range=(start_date, end_date)
        ).values('entry_page').annotate(
            sessions=Count('id'),
            bounces=Count(Case(
                When(pages_viewed=1, then=1),
                output_field=models.IntegerField()
            ))
        ).annotate(
            bounce_rate=Case(
                When(sessions__gt=0, then=(
                        models.F('bounces') * 100.0 / models.F('sessions')
                )),
                default=0,
                output_field=FloatField()
            )
        ).order_by('-sessions')[:20]

        # Exit pages
        context['exit_pages'] = VisitorSession.objects.filter(
            started_at__range=(start_date, end_date)
        ).exclude(exit_page='').values('exit_page').annotate(
            exits=Count('id')
        ).order_by('-exits')[:20]

        context['days'] = days
        context['start_date'] = start_date
        context['end_date'] = end_date

        return context

# API Views for AJAX requests

class AnalyticsAPIView(PublicStaffRequiredMixin, View):
    """API endpoint for dashboard data"""

    def get(self, request):
        metric = request.GET.get('metric')
        days = int(request.GET.get('days', 30))

        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

        if metric == 'traffic_trend':
            data = self.get_traffic_trend(start_date, end_date)
        elif metric == 'device_breakdown':
            data = self.get_device_breakdown(start_date, end_date)
        elif metric == 'top_pages':
            data = self.get_top_pages(start_date, end_date)
        elif metric == 'realtime':
            data = self.get_realtime_data()
        else:
            return JsonResponse({'error': 'Invalid metric'}, status=400)

        return JsonResponse(data, safe=False)

    def get_traffic_trend(self, start_date, end_date):
        trend = PageView.objects.filter(
            viewed_at__range=(start_date, end_date)
        ).annotate(
            date=TruncDate('viewed_at')
        ).values('date').annotate(
            visitors=Count('visitor_id', distinct=True),
            pageviews=Count('id')
        ).order_by('date')

        return [{
            'date': item['date'].isoformat(),
            'visitors': item['visitors'],
            'pageviews': item['pageviews']
        } for item in trend]

    def get_device_breakdown(self, start_date, end_date):
        devices = PageView.objects.filter(
            viewed_at__range=(start_date, end_date)
        ).values('device_type').annotate(
            count=Count('visitor_id', distinct=True)
        ).order_by('-count')

        return list(devices)

    def get_top_pages(self, start_date, end_date):
        pages = PageView.objects.filter(
            viewed_at__range=(start_date, end_date)
        ).values('url_path').annotate(
            views=Count('id'),
            unique_visitors=Count('visitor_id', distinct=True)
        ).order_by('-views')[:10]

        return list(pages)

    def get_realtime_data(self):
        # Last 5 minutes
        threshold = timezone.now() - timedelta(minutes=5)

        active_visitors = PageView.objects.filter(
            viewed_at__gte=threshold
        ).values('visitor_id').distinct().count()

        recent_views = PageView.objects.filter(
            viewed_at__gte=threshold
        ).count()

        return {
            'active_visitors': active_visitors,
            'recent_views': recent_views,
            'timestamp': timezone.now().isoformat()
        }

@method_decorator(csrf_exempt, name='dispatch')
class TrackEventView(View):
    """
    AJAX endpoint to track custom events.
    Usage: POST /analytics/event/
    """

    def post(self, request):
        try:
            data = json.loads(request.body)

            category = data.get('category')
            action = data.get('action')
            label = data.get('label', '')
            value = data.get('value')

            if not category or not action:
                return JsonResponse({
                    'error': 'category and action are required'
                }, status=400)

            # Get visitor and session IDs
            visitor_id = getattr(request, 'visitor_id', None)
            session_id = getattr(request, 'session_id', None)

            if not visitor_id or not session_id:
                return JsonResponse({
                    'error': 'Missing tracking identifiers'
                }, status=400)

            # Track event asynchronously
            track_event_async.delay(
                category=category,
                action=action,
                visitor_id=visitor_id,
                session_id=session_id,
                label=label,
                value=value,
                url_path=data.get('url_path', request.path),
                page_title=data.get('page_title', ''),
                metadata=data.get('metadata', {})
            )

            return JsonResponse({'success': True})

        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)