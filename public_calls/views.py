"""
public_support/views.py

A SaaS-admin support dashboard that lives in the PUBLIC schema
but can query and respond to visitor sessions in ANY tenant schema.

Access:  https://primebooks.sale/saas-support/
         http://localhost:8000/saas-support/

Who can use this:
  - SaaS admins (public_accounts.PublicUser with is_staff=True)
  - Any user in the PUBLIC schema with is_staff=True

How it works:
  - Uses django_tenants schema_context() to switch into a tenant schema
    for every DB query — no need to log into the tenant
  - All responses are JSON so the dashboard is a single-page app
  - WebSocket connections go through the existing SupportChatConsumer
    (same ws/support/{token}/ endpoint — agents join the same room)
"""

import logging
from functools                   import wraps
from django.shortcuts            import render, redirect
from django.http                 import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils                import timezone
from django.db                   import connection
from datetime                    import timedelta

from django_tenants.utils        import schema_context, get_tenant_model

logger = logging.getLogger(__name__)

# ── Public-schema login URL ────────────────────────────────────────────────────
# This is the login page on the PUBLIC schema (not the tenant login).
# Matches your public_urls.py → public-admin/ route.
PUBLIC_LOGIN_URL = '/public-admin/login/'


# ── Auth decorator for public-schema staff views ──────────────────────────────

def public_staff_required(view_func):
    """
    Replacement for @login_required that redirects to the PUBLIC schema
    login page instead of the tenant /accounts/login/ URL.
    Only allows users who are authenticated AND is_staff=True.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'{PUBLIC_LOGIN_URL}?next={request.path}')
        if not request.user.is_staff:
            return JsonResponse({'error': 'Staff access required.'}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper


# ── Helpers ────────────────────────────────────────────────────────────────────

def _require_staff(request):
    """Return an error response if the user is not staff, else None."""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'error': 'Staff access required.'}, status=403)
    return None


def _get_all_tenant_schemas():
    """Return list of (schema_name, company_name) for all active tenants."""
    TenantModel = get_tenant_model()
    tenants = TenantModel.objects.exclude(
        schema_name='public'
    ).values('schema_name', 'name').order_by('name')
    return list(tenants)


def _push_to_chat_room(session_token, payload):
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync    import async_to_sync
        layer = get_channel_layer()
        async_to_sync(layer.group_send)(f"support_chat_{session_token}", payload)
    except Exception as e:
        logger.warning("channels push failed: %s", e)


# ── Main dashboard view ────────────────────────────────────────────────────────

@public_staff_required
def saas_support_dashboard(request):
    """
    The main SaaS support dashboard page.
    Renders a template; all data loaded via JS + AJAX.
    """
    err = _require_staff(request)
    if err: return err

    tenants = _get_all_tenant_schemas()
    return render(request, 'public_calls/dashboard.html', {
        'tenants': tenants,
        'user': request.user,
    })


# ── API: list sessions across all tenants ──────────────────────────────────────

@public_staff_required
@require_GET
def all_sessions(request):
    """
    GET /saas-support/api/sessions/
    GET /saas-support/api/sessions/?schema=rem   (filter to one tenant)

    Returns active support sessions across all tenant schemas.
    """
    err = _require_staff(request)
    if err: return err

    filter_schema = request.GET.get('schema', '').strip()
    cutoff        = timezone.now() - timedelta(hours=4)

    results = []

    schemas = (
        [{'schema_name': filter_schema, 'name': filter_schema}]
        if filter_schema
        else _get_all_tenant_schemas()
    )

    for tenant in schemas:
        schema = tenant['schema_name']
        try:
            with schema_context(schema):
                from support_widget.models import VisitorSession

                sessions = VisitorSession.objects.filter(
                    status__in=['onboarding', 'faq', 'chatting', 'escalated', 'in_call'],
                    updated_at__gte=cutoff,
                ).select_related('assigned_agent').prefetch_related('messages').order_by('-updated_at')[:50]

                for s in sessions:
                    unread   = s.messages.filter(sender='visitor', is_read=False).count()
                    last_msg = s.messages.order_by('-created_at').first()
                    results.append({
                        'schema':        schema,
                        'tenant_name':   tenant.get('name', schema),
                        'token':         str(s.session_token),
                        'name':          s.visitor_name or 'Anonymous',
                        'email':         s.visitor_email,
                        'status':        s.status,
                        'created':       s.created_at.isoformat(),
                        'updated':       s.updated_at.isoformat(),
                        'agent':         s.assigned_agent.get_full_name() if s.assigned_agent else None,
                        'unread_count':  unread,
                        'last_message':  last_msg.body[:100] if last_msg else None,
                        'last_sender':   last_msg.sender if last_msg else None,
                    })
        except Exception as e:
            logger.warning("Failed to query sessions for schema=%s: %s", schema, e)

    # Sort all results by updated_at descending
    results.sort(key=lambda x: x['updated'], reverse=True)
    return JsonResponse({'sessions': results, 'total': len(results)})


# ── API: get messages for a session ───────────────────────────────────────────

@public_staff_required
@require_GET
def session_messages(request, schema, session_token):
    """
    GET /saas-support/api/session/<schema>/<token>/messages/
    Returns full message history for a session in a specific tenant schema.
    """
    err = _require_staff(request)
    if err: return err

    try:
        with schema_context(schema):
            from support_widget.models import VisitorSession, ChatMessage

            session  = VisitorSession.objects.get(session_token=session_token)
            messages = session.messages.select_related('agent_user').order_by('created_at')

            # Mark visitor messages as read
            session.messages.filter(sender='visitor', is_read=False).update(is_read=True)

            return JsonResponse({
                'session': {
                    'schema':  schema,
                    'token':   str(session.session_token),
                    'name':    session.visitor_name or 'Anonymous',
                    'email':   session.visitor_email,
                    'status':  session.status,
                    'created': session.created_at.isoformat(),
                    'agent':   session.assigned_agent.get_full_name() if session.assigned_agent else None,
                },
                'messages': [
                    {
                        'id':         m.pk,
                        'sender':     m.sender,
                        'agent_name': m.agent_user.get_full_name() if m.agent_user else None,
                        'body':       m.body,
                        'is_read':    m.is_read,
                        'timestamp':  m.created_at.isoformat(),
                    }
                    for m in messages
                ]
            })
    except Exception as e:
        logger.error("session_messages failed schema=%s token=%s: %s", schema, session_token, e)
        return JsonResponse({'error': str(e)}, status=404)


# ── API: send message as SaaS agent ───────────────────────────────────────────

@public_staff_required
@require_POST
def send_message(request, schema, session_token):
    """
    POST /saas-support/api/session/<schema>/<token>/message/
    Body: { "body": "..." }
    Sends a message as a SaaS support agent into a tenant session.
    """
    err = _require_staff(request)
    if err: return err

    import json
    try:
        data = json.loads(request.body)
        body = (data.get('body') or '').strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not body:
        return JsonResponse({'error': 'Message body is required.'}, status=400)

    try:
        with schema_context(schema):
            from support_widget.models import VisitorSession, ChatMessage

            session = VisitorSession.objects.get(session_token=session_token)

            if session.status == 'resolved':
                return JsonResponse({'error': 'Session is resolved.'}, status=400)

            # Save message — agent_user is None because SaaS admin has no tenant user
            # We use the agent_user field as None and mark sender as 'agent'
            msg = ChatMessage.objects.create(
                session=session,
                sender='agent',
                body=body,
                agent_user=None,  # SaaS admin has no tenant account
            )

            # Promote session if it was waiting
            if session.status in ('onboarding', 'faq', 'escalated'):
                session.status = 'chatting'
                session.save(update_fields=['status'])

        # Push via Channels so the visitor's widget updates in real time
        agent_label = request.user.get_full_name() or request.user.username
        _push_to_chat_room(session_token, {
            'type':       'chat.message',
            'message_id': msg.pk,
            'sender':     'agent',
            'body':       body,
            'timestamp':  msg.created_at.isoformat(),
        })

        return JsonResponse({
            'id':        msg.pk,
            'sender':    'agent',
            'body':      body,
            'timestamp': msg.created_at.isoformat(),
        })

    except Exception as e:
        logger.error("send_message failed schema=%s token=%s: %s", schema, session_token, e)
        return JsonResponse({'error': str(e)}, status=500)


# ── API: resolve session ───────────────────────────────────────────────────────

@public_staff_required
@require_POST
def resolve_session(request, schema, session_token):
    """POST /saas-support/api/session/<schema>/<token>/resolve/"""
    err = _require_staff(request)
    if err: return err

    try:
        with schema_context(schema):
            from support_widget.models import VisitorSession, ChatMessage
            session = VisitorSession.objects.get(session_token=session_token)
            session.resolve()
            ChatMessage.objects.create(
                session=session, sender='system',
                body='This conversation has been resolved. Thank you for contacting us!',
            )

        _push_to_chat_room(session_token, {
            'type':      'chat.message',
            'message_id': None,
            'sender':    'system',
            'body':      'This conversation has been resolved. Thank you for contacting us!',
            'timestamp': timezone.now().isoformat(),
        })

        # Notify agent queue for this schema
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync    import async_to_sync
            layer = get_channel_layer()
            async_to_sync(layer.group_send)(f"agent_queue_{schema}", {
                'type':          'agent.session_resolved',
                'session_token': str(session_token),
            })
        except Exception:
            pass

        return JsonResponse({'ok': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ── API: get tenant list ───────────────────────────────────────────────────────

@public_staff_required
@require_POST
def initiate_call(request, schema, session_token):
    """
    POST /saas-support/api/session/<schema>/<token>/call/
    SaaS admin initiates a WebRTC call with a visitor in a tenant schema.
    Creates the CallSession in the tenant schema, pushes the call invitation
    to the visitor's widget via Channels, opens the call room for the admin.
    """
    err = _require_staff(request)
    if err: return err

    try:
        with schema_context(schema):
            from support_widget.models import VisitorSession, CallSession, SupportWidgetConfig

            session = VisitorSession.objects.get(session_token=session_token)
            config, _ = SupportWidgetConfig.objects.get_or_create(pk=1)
            recording_notice = config.call_recording_notice  # read inside schema_context

            if session.status == 'resolved':
                return JsonResponse({'error': 'Session is already resolved.'}, status=400)

            # Create the call session inside the tenant schema
            call = CallSession.objects.create(session=session)

            session.status = 'in_call'
            session.save(update_fields=['status'])

        # Push call invitation to visitor's widget via Channels
        _push_to_chat_room(session_token, {
            'type':             'chat.start_call',
            'call_room_id':     str(call.call_room_id),
            'recording_notice': recording_notice,
        })

        # Also alert tenant agent queue
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync    import async_to_sync
            layer = get_channel_layer()
            async_to_sync(layer.group_send)(f"agent_queue_{schema}", {
                'type':          'agent.incoming_call',
                'call_room_id':  str(call.call_room_id),
                'session_token': str(session_token),
                'visitor_name':  session.visitor_name or 'Anonymous',
            })
        except Exception:
            pass

        return JsonResponse({
            'ok':               True,
            'call_room_id':     str(call.call_room_id),
            'recording_notice': recording_notice,
        })

    except VisitorSession.DoesNotExist:
        return JsonResponse({'error': 'Session not found.'}, status=404)
    except Exception as e:
        logger.error("initiate_call failed schema=%s token=%s: %s", schema, session_token, e)
        return JsonResponse({'error': str(e)}, status=500)



@public_staff_required
def saas_call_room(request, call_room_id):
    from django.shortcuts import render as _render
    return _render(request, 'support_widget/call_room.html', {
        'call_room_id': call_room_id,
        'is_agent':     True,
    })


@public_staff_required
@require_GET
def tenant_list(request):
    """GET /saas-support/api/tenants/"""
    err = _require_staff(request)
    if err: return err
    return JsonResponse({'tenants': _get_all_tenant_schemas()})


# ── Public schema agent queue WebSocket ───────────────────────────────────────
# The SaaS dashboard needs to receive notifications from ALL tenant schemas.
# We add a special public-schema consumer route that proxies agent_queue_{schema}.

def saas_agent_queue_config(request):
    """
    GET /saas-support/api/queue-config/
    Returns the list of schemas the SaaS agent should subscribe to,
    so the JS can open one AgentQueueConsumer WS per active tenant.
    """
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'error': 'Staff only.'}, status=403)
    schemas = [t['schema_name'] for t in _get_all_tenant_schemas()]
    return JsonResponse({'schemas': schemas})