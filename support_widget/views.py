"""
support_widget/views.py

REST API endpoints consumed by the widget JS and the agent dashboard.

Public endpoints (no login required — visitor uses session token):
  POST /support/session/                  — create visitor session
  PATCH /support/session/<token>/         — update name/email
  GET  /support/faq/?q=<query>            — search FAQ
  POST /support/call/create/              — create WebRTC call session
  POST /support/call/<room_id>/recording/ — upload recording

Authenticated endpoints (agent/admin):
  GET  /support/agent/sessions/           — list open sessions
  POST /support/agent/status/             — toggle agent online/offline
  GET  /support/agent/calls/              — call history
"""

import logging
from django.http              import JsonResponse
from django.views.decorators.http  import require_POST, require_GET
from django.views.decorators.csrf  import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils             import timezone
from django.views.generic     import TemplateView

from .models import (
    SupportWidgetConfig, VisitorSession, ChatMessage,
    FAQ, AgentProfile, CallSession, CallRecording,
)

logger = logging.getLogger(__name__)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _json_error(msg, status=400):
    return JsonResponse({'ok': False, 'error': msg}, status=status)

def _json_ok(data=None):
    payload = {'ok': True}
    if data:
        payload.update(data)
    return JsonResponse(payload)

def _get_config():
    config, _ = SupportWidgetConfig.objects.get_or_create(pk=1)
    return config


# ═══════════════════════════════════════════════════════════════════════════════
# Visitor — Session
# ═══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@require_POST
def create_session(request):
    """
    POST /support/session/
    Body: { referrer_url, user_agent }   (optional)
    Returns: { session_token, greeting, widget_title, brand_color }
    """
    import json
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    config  = _get_config()
    session = VisitorSession.objects.create(
        referrer_url = data.get('referrer_url', '')[:500],
        user_agent   = (request.META.get('HTTP_USER_AGENT', ''))[:500],
    )

    return _json_ok({
        'session_token':  str(session.session_token),
        'greeting':       config.greeting_message,
        'widget_title':   config.widget_title,
        'brand_color':    config.brand_color,
    })


@csrf_exempt
def update_session(request, session_token):
    """
    PATCH /support/session/<token>/
    Body: { name, email }
    """
    import json
    if request.method not in ('PATCH', 'POST'):
        return _json_error('Method not allowed', 405)

    try:
        session = VisitorSession.objects.get(session_token=session_token)
    except VisitorSession.DoesNotExist:
        return _json_error('Session not found', 404)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return _json_error('Invalid payload')

    name  = (data.get('name')  or '').strip()
    email = (data.get('email') or '').strip()

    if name:
        session.visitor_name = name
    if email:
        session.visitor_email = email
    if session.status == 'onboarding' and name and email:
        session.status = 'faq'
    session.save()

    return _json_ok({'status': session.status})


# ═══════════════════════════════════════════════════════════════════════════════
# Visitor — FAQ
# ═══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@require_GET
def search_faq(request):
    """
    GET /support/faq/?q=<query>
    Returns top 5 matching FAQ entries.
    If no query, returns the first 5 active FAQs as defaults.
    """
    q = request.GET.get('q', '').strip()

    faqs = FAQ.objects.filter(is_active=True)

    if q:
        matched = [f for f in faqs if f.matches(q)][:5]
    else:
        matched = list(faqs[:5])

    return JsonResponse({
        'results': [
            {'id': f.pk, 'question': f.question, 'answer': f.answer}
            for f in matched
        ]
    })


# ═══════════════════════════════════════════════════════════════════════════════
# Visitor — Call
# ═══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@require_POST
def create_call(request):
    """
    POST /support/call/create/
    Body: { session_token }
    Returns: { call_room_id, recording_notice }
    """
    import json
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return _json_error('Invalid payload')

    token = (data.get('session_token') or '').strip()
    if not token:
        return _json_error('session_token required')

    try:
        session = VisitorSession.objects.get(session_token=token)
    except VisitorSession.DoesNotExist:
        return _json_error('Session not found', 404)

    config = _get_config()
    call   = CallSession.objects.create(session=session)

    # 1. Push call invitation to the VISITOR's chat widget
    # 2. Notify all ONLINE AGENTS via the agent queue broadcast group
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync    import async_to_sync
        from django.db       import connection

        schema = connection.schema_name
        layer  = get_channel_layer()

        # Push to the visitor's chat room so the widget shows consent + call button
        async_to_sync(layer.group_send)(
            f"support_chat_{session.session_token}",
            {
                'type':             'chat.start_call',
                'call_room_id':     str(call.call_room_id),
                'recording_notice': config.call_recording_notice,
            }
        )

        # Alert all online agents so any available one can join
        async_to_sync(layer.group_send)(
            f"agent_queue_{schema}",
            {
                'type':          'agent.incoming_call',
                'call_room_id':  str(call.call_room_id),
                'session_token': str(session.session_token),
                'visitor_name':  session.visitor_name or 'Anonymous',
            }
        )
    except Exception as e:
        logger.warning("Could not notify channels of new call: %s", e)

    session.status = 'in_call'
    session.save(update_fields=['status'])

    return _json_ok({
        'call_room_id':     str(call.call_room_id),
        'recording_notice': config.call_recording_notice,
    })


@csrf_exempt
@require_POST
def upload_recording(request, call_room_id):
    """
    POST /support/call/<call_room_id>/recording/
    multipart/form-data: file=<audio file>
    """
    try:
        call = CallSession.objects.get(call_room_id=call_room_id)
    except CallSession.DoesNotExist:
        return _json_error('Call not found', 404)

    audio_file = request.FILES.get('file')
    if not audio_file:
        return _json_error('No file provided')

    recording, created = CallRecording.objects.update_or_create(
        call=call,
        defaults={
            'file':      audio_file,
            'file_size': audio_file.size,
        }
    )
    return _json_ok({'recording_id': recording.pk})


# ═══════════════════════════════════════════════════════════════════════════════
# Agent — Dashboard data
# ═══════════════════════════════════════════════════════════════════════════════

@login_required
@require_GET
def agent_sessions(request):
    """GET /support/agent/sessions/ — open/escalated/in_call sessions for the agent."""
    sessions = VisitorSession.objects.filter(
        status__in=['escalated', 'chatting', 'in_call']
    ).prefetch_related('messages').select_related('assigned_agent').order_by('-created_at')[:50]

    result = []
    for s in sessions:
        unread = s.messages.filter(sender='visitor', is_read=False).count()
        result.append({
            'token':        str(s.session_token),
            'name':         s.visitor_name or 'Anonymous',
            'email':        s.visitor_email,
            'status':       s.status,
            'created':      s.created_at.isoformat(),
            'agent':        s.assigned_agent.get_full_name() if s.assigned_agent else None,
            'unread_count': unread,
        })

    return JsonResponse({'sessions': result})


@login_required
@require_POST
def agent_set_status(request):
    """
    POST /support/agent/status/
    Body: { status: 'online' | 'offline' | 'busy' }
    """
    import json
    try:
        data   = json.loads(request.body)
        status = data.get('status', 'offline')
    except json.JSONDecodeError:
        return _json_error('Invalid payload')

    if status not in ('online', 'offline', 'busy'):
        return _json_error('Invalid status')

    profile, _ = AgentProfile.objects.get_or_create(
        user=request.user,
        defaults={'display_name': request.user.get_full_name() or request.user.username}
    )
    profile.status    = status
    profile.last_seen = timezone.now()
    profile.save(update_fields=['status', 'last_seen'])

    return _json_ok({'status': profile.status})


@login_required
@require_GET
def agent_calls(request):
    """GET /support/agent/calls/ — call history for the agent."""
    calls = CallSession.objects.filter(
        agent=request.user
    ).select_related('session').order_by('-created_at')[:30]

    return JsonResponse({
        'calls': [
            {
                'call_room_id': str(c.call_room_id),
                'visitor':      c.session.visitor_name or 'Anonymous',
                'status':       c.status,
                'duration':     c.duration_display,
                'started_at':   c.started_at.isoformat() if c.started_at else None,
                'has_recording': hasattr(c, 'recording'),
            }
            for c in calls
        ]
    })


# ═══════════════════════════════════════════════════════════════════════════════
# Widget Config (admin sets via Django admin or this view)
# ═══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@require_GET
def widget_config(request):
    """GET /support/config/ — public config used by the widget loader."""
    config = _get_config()
    return JsonResponse({
        'greeting':     config.greeting_message,
        'title':        config.widget_title,
        'brand_color':  config.brand_color,
        'is_active':    config.is_active,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# Template Views
# ═══════════════════════════════════════════════════════════════════════════════

class AgentDashboardView(TemplateView):
    template_name = 'support_widget/agent_dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        return super().dispatch(request, *args, **kwargs)


class CallRoomView(TemplateView):
    """
    The page a visitor lands on when they click the call link.
    Also used by the agent (different role detected by query param / session).
    """
    template_name = 'support_widget/call_room.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['call_room_id'] = self.kwargs['call_room_id']
        # Determine role: visitor (has session_token) or agent (is authenticated)
        ctx['is_agent']     = self.request.user.is_authenticated
        return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# Agent — Session detail helpers
# ═══════════════════════════════════════════════════════════════════════════════

@login_required
@require_GET
def session_messages(request, session_token):
    """
    GET /support/agent/session/<token>/messages/
    Returns the full message history for a session so the agent dashboard
    can populate the chat pane when opening a session.
    """
    try:
        session = VisitorSession.objects.get(session_token=session_token)
    except VisitorSession.DoesNotExist:
        return _json_error('Session not found', 404)

    msgs = session.messages.select_related('agent_user').order_by('created_at')
    return JsonResponse({
        'session': {
            'token':   str(session.session_token),
            'name':    session.visitor_name or 'Anonymous',
            'email':   session.visitor_email,
            'status':  session.status,
            'created': session.created_at.isoformat(),
        },
        'messages': [
            {
                'id':        m.pk,
                'sender':    m.sender,
                'body':      m.body,
                'timestamp': m.created_at.isoformat(),
                'agent':     m.agent_user.get_full_name() if m.agent_user else None,
            }
            for m in msgs
        ]
    })


@login_required
@require_POST
def resolve_session(request, session_token):
    """
    POST /support/agent/session/<token>/resolve/
    Marks a session as resolved and notifies all connected WS clients.
    """
    try:
        session = VisitorSession.objects.get(session_token=session_token)
    except VisitorSession.DoesNotExist:
        return _json_error('Session not found', 404)

    session.resolve()

    # Save a system message so the visitor's widget also reflects closure
    ChatMessage.objects.create(
        session=session,
        sender='system',
        body='This conversation has been resolved. Thanks for contacting us!',
    )

    # Notify via Channels: close the visitor's chat and update agent queues
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync    import async_to_sync
        from django.db       import connection

        schema = connection.schema_name
        layer  = get_channel_layer()

        # Tell the visitor's widget the chat is resolved
        async_to_sync(layer.group_send)(
            f"support_chat_{session_token}",
            {
                'type':    'chat.message',
                'message_id': None,
                'sender':  'system',
                'body':    'This conversation has been resolved. Thanks for contacting us!',
                'timestamp': timezone.now().isoformat(),
            }
        )
        # Tell all agent dashboards to remove this session from their list
        async_to_sync(layer.group_send)(
            f"agent_queue_{schema}",
            {
                'type':          'agent.session_resolved',
                'session_token': str(session_token),
            }
        )
    except Exception as e:
        logger.warning("Could not notify channels of session resolution: %s", e)

    return _json_ok({'status': 'resolved'})


@login_required
@require_GET
def agent_unread_count(request):
    """
    GET /support/agent/unread/
    Returns count of escalated/open sessions with unread visitor messages.
    Used by the agent dashboard badge in the nav.
    """
    unread = VisitorSession.objects.filter(
        status__in=['escalated', 'chatting'],
    ).count()
    return JsonResponse({'unread': unread})