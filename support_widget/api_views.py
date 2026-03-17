"""
support_widget/api_views.py

Mobile-ready REST API built with Django REST Framework.

Authentication:
  Visitors  — no Django account needed; identified by session_token UUID
              passed as either a header  X-Session-Token: <uuid>
              or as a query param        ?session_token=<uuid>

  Agents    — standard DRF auth (SessionAuthentication + TokenAuthentication
              + JWT).  The existing REST_FRAMEWORK settings in settings.py
              already cover this — no changes needed there.

Base URL: /api/support/   (add to tenant urls.py)
          /support/       (existing web endpoints — unchanged)

──────────────────────────────────────────────────────────────────────────
VISITOR ENDPOINTS  (no login required)
──────────────────────────────────────────────────────────────────────────
POST   /api/support/session/                  create session
GET    /api/support/session/<token>/          get session status
PATCH  /api/support/session/<token>/          update name / email
GET    /api/support/session/<token>/messages/ get message history
POST   /api/support/session/<token>/message/  send a message
POST   /api/support/session/<token>/request-agent/  escalate to human
POST   /api/support/session/<token>/typing/   send typing indicator

GET    /api/support/faq/                      list / search FAQs
GET    /api/support/config/                   widget configuration

POST   /api/support/call/create/              create WebRTC call session
POST   /api/support/call/<room_id>/consent/   record recording consent
POST   /api/support/call/<room_id>/end/       end call (visitor side)
POST   /api/support/call/<room_id>/recording/ upload recording file

──────────────────────────────────────────────────────────────────────────
AGENT ENDPOINTS  (JWT / Token / Session auth required)
──────────────────────────────────────────────────────────────────────────
GET    /api/support/agent/me/                 my agent profile
PUT    /api/support/agent/me/                 update profile
POST   /api/support/agent/status/             set online/busy/offline
GET    /api/support/agent/sessions/           open session queue
GET    /api/support/agent/session/<token>/    session detail + messages
POST   /api/support/agent/session/<token>/message/   send message
POST   /api/support/agent/session/<token>/resolve/   resolve session
POST   /api/support/agent/session/<token>/assign/    assign to self
GET    /api/support/agent/calls/              call history
GET    /api/support/agent/unread/             unread count badge
POST   /api/support/push-token/               register mobile push token
──────────────────────────────────────────────────────────────────────────
"""

import logging
from django.utils     import timezone
from django.db        import transaction

from rest_framework          import status
from rest_framework.views    import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers    import MultiPartParser, JSONParser

from .models import (
    SupportWidgetConfig, VisitorSession, ChatMessage,
    FAQ, AgentProfile, CallSession, CallRecording,
)
from .serializers import (
    WidgetConfigSerializer,
    VisitorSessionCreateSerializer, VisitorSessionUpdateSerializer,
    VisitorSessionSerializer,
    ChatMessageSerializer, SendMessageSerializer, AgentSendMessageSerializer,
    FAQSerializer,
    AgentProfileSerializer, AgentStatusSerializer, AgentSessionListSerializer,
    CallSessionSerializer, CallCreateSerializer,
    PushTokenSerializer,
)

logger = logging.getLogger(__name__)


# ─── Visitor auth helper ──────────────────────────────────────────────────────

def _get_session(request, token_from_url=None):
    """
    Resolve a VisitorSession from:
      1. URL kwarg (passed as token_from_url)
      2. X-Session-Token header
      3. ?session_token= query param
    Returns (session, None) or (None, Response error).
    """
    token = (
        token_from_url
        or request.META.get('HTTP_X_SESSION_TOKEN')
        or request.query_params.get('session_token')
        or (request.data.get('session_token') if hasattr(request, 'data') else None)
    )
    if not token:
        return None, Response(
            {'detail': 'session_token is required (header X-Session-Token or query param).'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        session = VisitorSession.objects.get(session_token=token)
        return session, None
    except VisitorSession.DoesNotExist:
        return None, Response({'detail': 'Session not found.'}, status=status.HTTP_404_NOT_FOUND)


def _push_to_chat_room(session_token, payload):
    """Send a message to a chat room group via Django Channels."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync    import async_to_sync
        layer = get_channel_layer()
        async_to_sync(layer.group_send)(f"support_chat_{session_token}", payload)
    except Exception as e:
        logger.warning("channels push failed: %s", e)


def _push_to_agent_queue(schema_name, payload):
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync    import async_to_sync
        layer = get_channel_layer()
        async_to_sync(layer.group_send)(f"agent_queue_{schema_name}", payload)
    except Exception as e:
        logger.warning("agent queue push failed: %s", e)


def _schema_name():
    from django.db import connection
    return getattr(connection, 'schema_name', 'public')


# ═══════════════════════════════════════════════════════════════════════════════
# VISITOR — Widget config
# ═══════════════════════════════════════════════════════════════════════════════

class APIWidgetConfig(APIView):
    """GET /api/support/config/"""
    permission_classes = [AllowAny]

    def get(self, request):
        config, _ = SupportWidgetConfig.objects.get_or_create(pk=1)
        return Response(WidgetConfigSerializer(config).data)


# ═══════════════════════════════════════════════════════════════════════════════
# VISITOR — Session lifecycle
# ═══════════════════════════════════════════════════════════════════════════════

class APISessionCreate(APIView):
    """POST /api/support/session/"""
    permission_classes = [AllowAny]

    def post(self, request):
        ser = VisitorSessionCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        config, _ = SupportWidgetConfig.objects.get_or_create(pk=1)
        if not config.is_active:
            return Response({'detail': 'Support is currently unavailable.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        session = VisitorSession.objects.create(
            referrer_url = d.get('referrer_url', '')[:500],
            user_agent   = (
                d.get('user_agent') or request.META.get('HTTP_USER_AGENT', '')
            )[:500],
        )

        return Response({
            'session_token':    str(session.session_token),
            'greeting':         config.greeting_message,
            'widget_title':     config.widget_title,
            'brand_color':      config.brand_color,
            'status':           session.status,
        }, status=status.HTTP_201_CREATED)


class APISessionDetail(APIView):
    """GET / PATCH /api/support/session/<token>/"""
    permission_classes = [AllowAny]

    def get(self, request, session_token):
        session, err = _get_session(request, session_token)
        if err: return err
        return Response(VisitorSessionSerializer(session).data)

    def patch(self, request, session_token):
        session, err = _get_session(request, session_token)
        if err: return err

        ser = VisitorSessionUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        changed = False
        if d.get('name'):
            session.visitor_name  = d['name']
            changed = True
        if d.get('email'):
            session.visitor_email = d['email']
            changed = True
        if changed:
            if session.status == 'onboarding' and session.visitor_name and session.visitor_email:
                session.status = 'faq'
            session.save()

        return Response(VisitorSessionSerializer(session).data)


# ═══════════════════════════════════════════════════════════════════════════════
# VISITOR — Messages
# ═══════════════════════════════════════════════════════════════════════════════

class APISessionMessages(APIView):
    """GET /api/support/session/<token>/messages/"""
    permission_classes = [AllowAny]

    def get(self, request, session_token):
        session, err = _get_session(request, session_token)
        if err: return err

        # Mark all agent/bot messages as read when visitor fetches history
        session.messages.filter(
            sender__in=['agent', 'bot', 'system'], is_read=False
        ).update(is_read=True)

        messages = session.messages.select_related('agent_user').order_by('created_at')
        return Response({
            'session':  VisitorSessionSerializer(session).data,
            'messages': ChatMessageSerializer(messages, many=True).data,
        })


class APIVisitorSendMessage(APIView):
    """POST /api/support/session/<token>/message/"""
    permission_classes = [AllowAny]

    def post(self, request, session_token):
        session, err = _get_session(request, session_token)
        if err: return err

        if session.status == 'resolved':
            return Response({'detail': 'This session is resolved.'}, status=status.HTTP_400_BAD_REQUEST)

        ser = SendMessageSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        body = ser.validated_data['body']

        msg = ChatMessage.objects.create(session=session, sender='visitor', body=body)

        if session.status in ('onboarding', 'faq'):
            session.status = 'chatting'
            session.save(update_fields=['status'])

        # Push to chat room so the agent dashboard / widget updates in real time
        _push_to_chat_room(session_token, {
            'type':       'chat.message',
            'message_id': msg.pk,
            'sender':     'visitor',
            'body':       body,
            'timestamp':  msg.created_at.isoformat(),
        })

        return Response(ChatMessageSerializer(msg).data, status=status.HTTP_201_CREATED)


class APIVisitorTyping(APIView):
    """POST /api/support/session/<token>/typing/"""
    permission_classes = [AllowAny]

    def post(self, request, session_token):
        session, err = _get_session(request, session_token)
        if err: return err
        _push_to_chat_room(session_token, {'type': 'chat.typing', 'sender': 'visitor'})
        return Response({'ok': True})


# ═══════════════════════════════════════════════════════════════════════════════
# VISITOR — Request agent
# ═══════════════════════════════════════════════════════════════════════════════

class APIRequestAgent(APIView):
    """POST /api/support/session/<token>/request-agent/"""
    permission_classes = [AllowAny]

    def post(self, request, session_token):
        session, err = _get_session(request, session_token)
        if err: return err

        if session.status == 'resolved':
            return Response({'detail': 'Session is resolved.'}, status=400)

        # Find available agent
        profile = AgentProfile.available_agents().first()

        if profile:
            session.assigned_agent = profile.user
            session.status = 'chatting'
            session.save(update_fields=['assigned_agent', 'status'])

            agent_name = profile.user.get_full_name() or profile.user.username

            # System message to visitor
            sys_msg = ChatMessage.objects.create(
                session=session, sender='system',
                body=f"✅ {agent_name} has joined the conversation.",
            )
            _push_to_chat_room(session_token, {
                'type': 'chat.message', 'message_id': sys_msg.pk,
                'sender': 'system', 'body': sys_msg.body,
                'timestamp': sys_msg.created_at.isoformat(),
            })

            # Notify the agent
            _push_to_agent_queue(_schema_name(), {
                'type':          'agent.new_session',
                'session_token': str(session_token),
                'visitor_name':  session.visitor_name or 'Anonymous',
                'visitor_email': session.visitor_email,
            })

            return Response({
                'ok':         True,
                'agent_name': agent_name,
                'status':     session.status,
            })

        else:
            # No agent available
            session.status = 'escalated'
            session.save(update_fields=['status'])

            sys_msg = ChatMessage.objects.create(
                session=session, sender='system',
                body="All our agents are busy right now. We'll email you a reply shortly.",
            )
            _push_to_chat_room(session_token, {
                'type': 'chat.message', 'message_id': sys_msg.pk,
                'sender': 'system', 'body': sys_msg.body,
                'timestamp': sys_msg.created_at.isoformat(),
            })

            # Fire offline follow-up email
            try:
                from .tasks import send_offline_followup_email
                send_offline_followup_email.delay(_schema_name(), session.pk)
            except Exception as e:
                logger.warning("offline email task failed: %s", e)

            return Response({
                'ok':     False,
                'detail': 'No agents available. You will receive an email follow-up.',
                'status': session.status,
            }, status=status.HTTP_200_OK)


# ═══════════════════════════════════════════════════════════════════════════════
# VISITOR — FAQ
# ═══════════════════════════════════════════════════════════════════════════════

class APIFAQList(APIView):
    """GET /api/support/faq/?q=<query>"""
    permission_classes = [AllowAny]

    def get(self, request):
        q    = request.query_params.get('q', '').strip()
        faqs = FAQ.objects.filter(is_active=True)
        if q:
            matched = [f for f in faqs if f.matches(q)][:6]
        else:
            matched = list(faqs[:6])
        return Response(FAQSerializer(matched, many=True).data)


# ═══════════════════════════════════════════════════════════════════════════════
# VISITOR — Calls
# ═══════════════════════════════════════════════════════════════════════════════

class APICallCreate(APIView):
    """POST /api/support/call/create/"""
    permission_classes = [AllowAny]

    def post(self, request):
        ser = CallCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            session = VisitorSession.objects.get(
                session_token=ser.validated_data['session_token']
            )
        except VisitorSession.DoesNotExist:
            return Response({'detail': 'Session not found.'}, status=404)

        config, _ = SupportWidgetConfig.objects.get_or_create(pk=1)
        call = CallSession.objects.create(session=session)

        session.status = 'in_call'
        session.save(update_fields=['status'])

        schema = _schema_name()

        # Push call invitation to visitor's chat room
        _push_to_chat_room(str(session.session_token), {
            'type':             'chat.start_call',
            'call_room_id':     str(call.call_room_id),
            'recording_notice': config.call_recording_notice,
        })

        # Alert all online agents
        _push_to_agent_queue(schema, {
            'type':          'agent.incoming_call',
            'call_room_id':  str(call.call_room_id),
            'session_token': str(session.session_token),
            'visitor_name':  session.visitor_name or 'Anonymous',
        })

        return Response({
            'call_room_id':     str(call.call_room_id),
            'ws_url':           f'wss://{{host}}/ws/support/call/{call.call_room_id}/',
            'recording_notice': config.call_recording_notice,
            'status':           call.status,
        }, status=status.HTTP_201_CREATED)


class APICallConsent(APIView):
    """POST /api/support/call/<room_id>/consent/"""
    permission_classes = [AllowAny]

    def post(self, request, call_room_id):
        try:
            call = CallSession.objects.get(call_room_id=call_room_id)
        except CallSession.DoesNotExist:
            return Response({'detail': 'Call not found.'}, status=404)
        call.recording_consent_given = True
        call.save(update_fields=['recording_consent_given'])
        return Response({'ok': True})


class APICallEnd(APIView):
    """POST /api/support/call/<room_id>/end/"""
    permission_classes = [AllowAny]

    def post(self, request, call_room_id):
        try:
            call = CallSession.objects.get(call_room_id=call_room_id)
        except CallSession.DoesNotExist:
            return Response({'detail': 'Call not found.'}, status=404)
        if call.status not in ('ended', 'missed', 'rejected'):
            call.end_call()
        # Notify all signaling room peers
        _push_to_chat_room(str(call.session.session_token), {
            'type':    'chat.message',
            'message_id': None,
            'sender':  'system',
            'body':    f'Call ended. Duration: {call.duration_display}',
            'timestamp': timezone.now().isoformat(),
        })
        return Response(CallSessionSerializer(call).data)


class APICallRecordingUpload(APIView):
    """POST /api/support/call/<room_id>/recording/"""
    permission_classes = [AllowAny]
    parser_classes     = [MultiPartParser]

    def post(self, request, call_room_id):
        try:
            call = CallSession.objects.get(call_room_id=call_room_id)
        except CallSession.DoesNotExist:
            return Response({'detail': 'Call not found.'}, status=404)

        audio_file = request.FILES.get('file')
        if not audio_file:
            return Response({'detail': 'No file provided.'}, status=400)

        recording, _ = CallRecording.objects.update_or_create(
            call=call,
            defaults={'file': audio_file, 'file_size': audio_file.size},
        )
        return Response({'recording_id': recording.pk}, status=status.HTTP_201_CREATED)


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT — Profile
# ═══════════════════════════════════════════════════════════════════════════════

class APIAgentMe(APIView):
    """GET / PUT /api/support/agent/me/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, _ = AgentProfile.objects.get_or_create(
            user=request.user,
            defaults={'display_name': request.user.get_full_name() or request.user.username},
        )
        return Response(AgentProfileSerializer(profile, context={'request': request}).data)

    def put(self, request):
        profile, _ = AgentProfile.objects.get_or_create(user=request.user)
        ser = AgentProfileSerializer(profile, data=request.data, partial=True,
                                     context={'request': request})
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(AgentProfileSerializer(profile, context={'request': request}).data)


class APIAgentSetStatus(APIView):
    """POST /api/support/agent/status/"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = AgentStatusSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        s = ser.validated_data['status']

        profile, _ = AgentProfile.objects.get_or_create(
            user=request.user,
            defaults={'display_name': request.user.get_full_name() or request.user.username},
        )
        profile.status    = s
        profile.last_seen = timezone.now()
        profile.save(update_fields=['status', 'last_seen'])

        return Response({'status': profile.status, 'last_seen': profile.last_seen})


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT — Session queue
# ═══════════════════════════════════════════════════════════════════════════════

class APIAgentSessions(APIView):
    """GET /api/support/agent/sessions/?status=chatting,escalated"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        filter_status = request.query_params.get('status', 'chatting,escalated')
        statuses = [s.strip() for s in filter_status.split(',')]

        sessions = VisitorSession.objects.filter(
            status__in=statuses
        ).select_related('assigned_agent').order_by('-created_at')[:100]

        return Response(AgentSessionListSerializer(sessions, many=True).data)


class APIAgentSessionDetail(APIView):
    """GET /api/support/agent/session/<token>/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, session_token):
        try:
            session = VisitorSession.objects.get(session_token=session_token)
        except VisitorSession.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)

        # Mark visitor messages as read
        session.messages.filter(sender='visitor', is_read=False).update(is_read=True)

        messages = session.messages.select_related('agent_user').order_by('created_at')
        return Response({
            'session':  AgentSessionListSerializer(session).data,
            'messages': ChatMessageSerializer(messages, many=True).data,
        })


class APIAgentSendMessage(APIView):
    """POST /api/support/agent/session/<token>/message/"""
    permission_classes = [IsAuthenticated]

    def post(self, request, session_token):
        try:
            session = VisitorSession.objects.get(session_token=session_token)
        except VisitorSession.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)

        if session.status == 'resolved':
            return Response({'detail': 'Session is resolved.'}, status=400)

        ser = AgentSendMessageSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        body = ser.validated_data['body']

        msg = ChatMessage.objects.create(
            session=session, sender='agent',
            agent_user=request.user, body=body,
        )

        # Assign this agent if session is unassigned
        if not session.assigned_agent:
            session.assigned_agent = request.user
            session.status = 'chatting'
            session.save(update_fields=['assigned_agent', 'status'])

        # Push to visitor widget / mobile via Channels
        _push_to_chat_room(str(session_token), {
            'type':       'chat.message',
            'message_id': msg.pk,
            'sender':     'agent',
            'body':       body,
            'timestamp':  msg.created_at.isoformat(),
        })

        return Response(ChatMessageSerializer(msg).data, status=status.HTTP_201_CREATED)


class APIAgentTyping(APIView):
    """POST /api/support/agent/session/<token>/typing/"""
    permission_classes = [IsAuthenticated]

    def post(self, request, session_token):
        _push_to_chat_room(str(session_token), {'type': 'chat.typing', 'sender': 'agent'})
        return Response({'ok': True})


class APIAgentResolveSession(APIView):
    """POST /api/support/agent/session/<token>/resolve/"""
    permission_classes = [IsAuthenticated]

    def post(self, request, session_token):
        try:
            session = VisitorSession.objects.get(session_token=session_token)
        except VisitorSession.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)

        session.resolve()
        sys_msg = ChatMessage.objects.create(
            session=session, sender='system',
            body='This conversation has been resolved. Thank you for contacting us!',
        )

        _push_to_chat_room(str(session_token), {
            'type': 'chat.message', 'message_id': sys_msg.pk,
            'sender': 'system', 'body': sys_msg.body,
            'timestamp': sys_msg.created_at.isoformat(),
        })
        _push_to_agent_queue(_schema_name(), {
            'type':          'agent.session_resolved',
            'session_token': str(session_token),
        })

        return Response({'ok': True, 'status': 'resolved'})


class APIAgentAssignSession(APIView):
    """POST /api/support/agent/session/<token>/assign/"""
    permission_classes = [IsAuthenticated]

    def post(self, request, session_token):
        try:
            session = VisitorSession.objects.get(session_token=session_token)
        except VisitorSession.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)

        session.assigned_agent = request.user
        if session.status == 'escalated':
            session.status = 'chatting'
        session.save(update_fields=['assigned_agent', 'status'])

        agent_name = request.user.get_full_name() or request.user.username
        sys_msg = ChatMessage.objects.create(
            session=session, sender='system',
            body=f"✅ {agent_name} has taken over this conversation.",
        )
        _push_to_chat_room(str(session_token), {
            'type': 'chat.message', 'message_id': sys_msg.pk,
            'sender': 'system', 'body': sys_msg.body,
            'timestamp': sys_msg.created_at.isoformat(),
        })

        return Response({'ok': True, 'agent': agent_name, 'status': session.status})


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT — Calls
# ═══════════════════════════════════════════════════════════════════════════════

class APIAgentCalls(APIView):
    """GET /api/support/agent/calls/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        calls = CallSession.objects.filter(
            agent=request.user
        ).select_related('session').order_by('-created_at')[:50]
        return Response(CallSessionSerializer(calls, many=True).data)


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT — Unread badge
# ═══════════════════════════════════════════════════════════════════════════════

class APIAgentUnread(APIView):
    """GET /api/support/agent/unread/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sessions_with_unread = VisitorSession.objects.filter(
            status__in=['escalated', 'chatting'],
            messages__sender='visitor',
            messages__is_read=False,
        ).distinct().count()
        return Response({'unread_sessions': sessions_with_unread})


# ═══════════════════════════════════════════════════════════════════════════════
# MOBILE — Push notification token registration
# ═══════════════════════════════════════════════════════════════════════════════

class APIPushToken(APIView):
    """
    POST /api/support/push-token/
    Stores an FCM / APNs device token for the authenticated agent so that
    push notifications can be sent when new sessions or calls arrive even
    when the app is not in the foreground.

    Requires a MobilePushToken model (see note in serializers.py).
    This view stores the token in the cache if no model is configured,
    so it is safe to call immediately — add the model later for persistence.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = PushTokenSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        token    = ser.validated_data['token']
        platform = ser.validated_data['platform']

        # Store in Django cache as a fallback (no extra model needed)
        from django.core.cache import cache
        cache_key = f"push_token_{request.user.pk}_{platform}"
        cache.set(cache_key, token, timeout=60 * 60 * 24 * 30)  # 30 days

        # TODO: persist in a MobilePushToken model for production reliability
        # MobilePushToken.objects.update_or_create(
        #     user=request.user, platform=platform,
        #     defaults={'token': token}
        # )

        return Response({'ok': True, 'platform': platform})


# ═══════════════════════════════════════════════════════════════════════════════
# API — ICE config for WebRTC (STUN/TURN)
# ═══════════════════════════════════════════════════════════════════════════════

class APIIceConfig(APIView):
    """
    GET /api/support/ice-config/
    Returns STUN/TURN server credentials for WebRTC.
    Mobile apps call this once per call session to get ICE servers.

    Configure TURN_SERVERS in settings.py:
      TURN_SERVERS = [
          {
              'urls': 'turn:your.turn.server:3478',
              'username': 'user',
              'credential': 'pass',
          }
      ]
    """
    permission_classes = [AllowAny]

    def get(self, request):
        from django.conf import settings

        ice_servers = [
            {'urls': 'stun:stun.l.google.com:19302'},
            {'urls': 'stun:stun1.l.google.com:19302'},
        ]

        # Append configured TURN servers if present
        turn = getattr(settings, 'TURN_SERVERS', [])
        ice_servers.extend(turn)

        return Response({'ice_servers': ice_servers})