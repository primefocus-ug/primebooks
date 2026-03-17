"""
support_widget/consumers.py

Three WebSocket consumers:
  1. SupportChatConsumer   — ws://<host>/ws/support/<session_token>/
     Handles visitor ↔ agent chat, typing, agent assignment, call initiation.

  2. SignalingConsumer      — ws://<host>/ws/support/call/<call_room_id>/
     Handles WebRTC SDP + ICE signaling between visitor and agent.

  3. AgentQueueConsumer    — ws://<host>/ws/support/agent/<user_id>/
     Per-agent notification channel. Receives new_session and incoming_call
     alerts pushed by group_send from the other consumers and from views.py.

All consumers are tenant-aware: they resolve the schema from scope['tenant']
(set by django_tenants TenantMainMiddleware) and pass it to schema_context()
so every DB query runs against the correct PostgreSQL schema.
"""

import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db                import database_sync_to_async
from django.utils               import timezone
from django_tenants.utils       import schema_context

logger = logging.getLogger(__name__)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _get_schema_from_scope(scope):
    """
    Extract the active tenant schema name from the ASGI scope.
    django_tenants sets scope['tenant'] via TenantMainMiddleware.
    Falls back to 'public' so the consumer never crashes on missing key.
    """
    tenant = scope.get('tenant')
    if tenant:
        return tenant.schema_name
    return 'public'


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Chat Consumer
# ═══════════════════════════════════════════════════════════════════════════════

class SupportChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for live support chat.

    Groups:
      - visitor_{session_token}  — the visitor's private channel
      - agent_queue              — all online agents receive new session alerts
      - agent_{user_id}          — the assigned agent's private channel
    """

    async def connect(self):
        self.session_token = self.scope['url_route']['kwargs']['session_token']
        self.schema_name   = _get_schema_from_scope(self.scope)
        self.room_group    = f"support_chat_{self.session_token}"
        self.agent_queue   = f"agent_queue_{self.schema_name}"

        await self.channel_layer.group_add(self.room_group, self.channel_name)
        await self.accept()
        logger.info("SupportChat connected: %s schema=%s", self.session_token, self.schema_name)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        msg_type = data.get('type')

        if msg_type == 'chat_message':
            await self._handle_chat_message(data)

        elif msg_type == 'session_update':
            await self._handle_session_update(data)

        elif msg_type == 'request_agent':
            await self._handle_request_agent(data)

        elif msg_type == 'typing':
            # Broadcast typing indicator to the room (exclude self via group send)
            await self.channel_layer.group_send(self.room_group, {
                'type':   'chat.typing',
                'sender': data.get('sender', 'visitor'),
            })

    # ── Incoming message handlers ─────────────────────────────────────────────

    async def _handle_chat_message(self, data):
        body       = (data.get('body') or '').strip()
        sender     = data.get('sender', 'visitor')   # 'visitor' | 'agent'
        agent_id   = data.get('agent_id')

        if not body:
            return

        # Persist message
        msg = await self._save_message(sender, body, agent_id)

        # Broadcast to everyone in the room
        await self.channel_layer.group_send(self.room_group, {
            'type':       'chat.message',
            'message_id': msg.pk,
            'sender':     sender,
            'body':       body,
            'timestamp':  msg.created_at.isoformat(),
        })

    async def _handle_session_update(self, data):
        """Visitor submitted name/email."""
        name  = (data.get('name')  or '').strip()
        email = (data.get('email') or '').strip()
        await self._update_session_info(name, email)
        await self.send(text_data=json.dumps({
            'type':   'session_updated',
            'name':   name,
            'email':  email,
        }))

    async def _handle_request_agent(self, data):
        """Visitor clicked 'Talk to an Agent'."""
        session = await self._escalate_session()
        agent   = await self._assign_available_agent(session)

        # Always broadcast to ALL online agents so the session appears in every dashboard
        await self.channel_layer.group_send(
            self.agent_queue,
            {
                'type':          'agent.new_session',
                'session_token': str(self.session_token),
                'visitor_name':  session.visitor_name or 'Anonymous',
                'visitor_email': session.visitor_email,
            }
        )

        if agent:
            # Also send directly to the specifically assigned agent
            await self.channel_layer.group_send(
                f"agent_{agent.pk}",
                {
                    'type':          'agent.new_session',
                    'session_token': str(self.session_token),
                    'visitor_name':  session.visitor_name or 'Anonymous',
                    'visitor_email': session.visitor_email,
                }
            )
            agent_name = getattr(agent, 'get_full_name', lambda: '')() or agent.username
            await self.channel_layer.group_send(self.room_group, {
                'type':       'chat.message',
                'message_id': None,
                'sender':     'system',
                'body':       f"✅ {agent_name} has joined the conversation.",
                'timestamp':  timezone.now().isoformat(),
            })
        else:
            # No agent available — notify visitor
            await self.send(text_data=json.dumps({
                'type':    'no_agent_available',
                'message': "All our agents are busy right now. We'll email you a reply shortly.",
            }))
            saved_msg = await self._save_message(
                'system', 'No agent available. We will follow up via email.', None
            )
            # Fire Celery task to send a follow-up email to the visitor
            await self._trigger_offline_email(saved_msg.session_id)

    # ── Channel layer event handlers (sent BY group_send, received HERE) ──────

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type':       'chat_message',
            'message_id': event.get('message_id'),
            'sender':     event['sender'],
            'body':       event['body'],
            'timestamp':  event['timestamp'],
        }))

    async def chat_typing(self, event):
        await self.send(text_data=json.dumps({
            'type':   'typing',
            'sender': event['sender'],
        }))

    async def agent_new_session(self, event):
        await self.send(text_data=json.dumps(event))

    async def chat_start_call(self, event):
        """
        Push an incoming call invitation to the visitor's widget.
        Triggered by group_send from views.create_call() after agent
        initiates a call from the dashboard.
        """
        await self.send(text_data=json.dumps({
            'type':             'start_call',
            'call_room_id':     event['call_room_id'],
            'recording_notice': event['recording_notice'],
        }))

    # ── DB helpers (run synchronously in thread pool) ─────────────────────────

    @database_sync_to_async
    def _save_message(self, sender, body, agent_id):
        from .models import ChatMessage, VisitorSession
        with schema_context(self.schema_name):
            session = VisitorSession.objects.get(session_token=self.session_token)
            agent_user = None
            if agent_id:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                try:
                    agent_user = User.objects.get(pk=agent_id)
                except User.DoesNotExist:
                    pass
            return ChatMessage.objects.create(
                session=session, sender=sender, body=body, agent_user=agent_user
            )

    @database_sync_to_async
    def _update_session_info(self, name, email):
        from .models import VisitorSession
        with schema_context(self.schema_name):
            VisitorSession.objects.filter(
                session_token=self.session_token
            ).update(visitor_name=name, visitor_email=email, status='faq')

    @database_sync_to_async
    def _escalate_session(self):
        from .models import VisitorSession
        with schema_context(self.schema_name):
            session = VisitorSession.objects.get(session_token=self.session_token)
            session.status = 'escalated'
            session.save(update_fields=['status'])
            return session

    @database_sync_to_async
    def _assign_available_agent(self, session):
        from .models import AgentProfile
        with schema_context(self.schema_name):
            profile = AgentProfile.available_agents().first()
            if not profile:
                return None
            session.assigned_agent = profile.user
            session.status = 'chatting'
            session.save(update_fields=['assigned_agent', 'status'])
            return profile.user

    @database_sync_to_async
    def _trigger_offline_email(self, session_id):
        """Queue a Celery task to email the visitor a follow-up."""
        try:
            from .tasks import send_offline_followup_email
            send_offline_followup_email.delay(self.schema_name, session_id)
        except Exception as e:
            logger.warning("sw: could not queue offline email task: %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. WebRTC Signaling Consumer
# ═══════════════════════════════════════════════════════════════════════════════

class SignalingConsumer(AsyncWebsocketConsumer):
    """
    Minimal WebRTC signaling relay.
    Both the visitor and the assigned agent join room_<call_room_id>.
    Messages are forwarded to all other members of the room.

    Expected message types from clients:
      offer       { type, sdp }
      answer      { type, sdp }
      ice         { type, candidate }
      call_ended  { type }
    """

    async def connect(self):
        self.call_room_id = self.scope['url_route']['kwargs']['call_room_id']
        self.schema_name  = _get_schema_from_scope(self.scope)
        self.room_group   = f"webrtc_call_{self.call_room_id}"

        await self.channel_layer.group_add(self.room_group, self.channel_name)
        await self.accept()
        logger.info("SignalingConsumer connected: call=%s", self.call_room_id)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        msg_type = data.get('type')

        if msg_type in ('offer', 'answer', 'ice'):
            # Relay to all other peers in the room
            await self.channel_layer.group_send(self.room_group, {
                'type':    'signal.relay',
                'payload': data,
                'origin':  self.channel_name,
            })

        elif msg_type == 'call_ended':
            await self._mark_call_ended()
            await self.channel_layer.group_send(self.room_group, {
                'type':    'signal.relay',
                'payload': {'type': 'call_ended'},
                'origin':  self.channel_name,
            })

        elif msg_type == 'consent_given':
            await self._record_consent()

    async def signal_relay(self, event):
        # Don't echo back to sender
        if event.get('origin') == self.channel_name:
            return
        await self.send(text_data=json.dumps(event['payload']))

    @database_sync_to_async
    def _mark_call_ended(self):
        from .models import CallSession
        with schema_context(self.schema_name):
            CallSession.objects.filter(
                call_room_id=self.call_room_id,
                status='active',
            ).first()
            # end_call() handles duration calculation
            call = CallSession.objects.filter(call_room_id=self.call_room_id).first()
            if call:
                call.end_call()

    @database_sync_to_async
    def _record_consent(self):
        from .models import CallSession
        with schema_context(self.schema_name):
            CallSession.objects.filter(
                call_room_id=self.call_room_id
            ).update(recording_consent_given=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Agent Queue Consumer
# ═══════════════════════════════════════════════════════════════════════════════

class AgentQueueConsumer(AsyncWebsocketConsumer):
    """
    Each logged-in agent opens one of these connections from the dashboard.
    It joins the group  agent_{user_id}  so that:
      - SupportChatConsumer._handle_request_agent() can push new_session alerts
      - views.create_call() can push incoming_call alerts

    It ALSO joins  agent_queue_{schema_name}  so broadcast messages
    (e.g. "any agent online, there's a new visitor") reach every agent.

    The consumer is read-only from the agent's perspective — agents only
    receive, they never send on this channel (they send on the chat WS).
    """

    async def connect(self):
        self.user_id     = self.scope['url_route']['kwargs']['user_id']
        self.schema_name = _get_schema_from_scope(self.scope)

        # Private group for this specific agent
        self.private_group  = f"agent_{self.user_id}"
        # Broadcast group for ALL agents on this tenant
        self.broadcast_group = f"agent_queue_{self.schema_name}"

        await self.channel_layer.group_add(self.private_group,   self.channel_name)
        await self.channel_layer.group_add(self.broadcast_group, self.channel_name)

        # Mark agent as having an active dashboard connection
        await self._set_last_seen()
        await self.accept()
        logger.info("AgentQueue connected: user=%s schema=%s", self.user_id, self.schema_name)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.private_group,   self.channel_name)
        await self.channel_layer.group_discard(self.broadcast_group, self.channel_name)
        logger.info("AgentQueue disconnected: user=%s", self.user_id)

    async def receive(self, text_data):
        """
        Agents can optionally send a heartbeat to keep the connection alive
        and update their last_seen timestamp.
        { "type": "heartbeat" }
        """
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return
        if data.get('type') == 'heartbeat':
            await self._set_last_seen()
            await self.send(text_data=json.dumps({'type': 'heartbeat_ack'}))

    # ── Channel layer event handlers ──────────────────────────────────────────

    async def agent_new_session(self, event):
        """New visitor requested a human agent."""
        await self.send(text_data=json.dumps({
            'type':          'new_session',
            'session_token': event['session_token'],
            'visitor_name':  event.get('visitor_name', 'Anonymous'),
            'visitor_email': event.get('visitor_email', ''),
        }))

    async def agent_incoming_call(self, event):
        """Visitor triggered a WebRTC call — alert all available agents."""
        await self.send(text_data=json.dumps({
            'type':          'incoming_call',
            'call_room_id':  event['call_room_id'],
            'session_token': event['session_token'],
            'visitor_name':  event.get('visitor_name', 'Anonymous'),
        }))

    async def agent_session_resolved(self, event):
        """A session was closed — agents can remove it from their list."""
        await self.send(text_data=json.dumps({
            'type':          'session_resolved',
            'session_token': event['session_token'],
        }))

    # ── DB helper ──────────────────────────────────────────────────────────────

    @database_sync_to_async
    def _set_last_seen(self):
        from .models import AgentProfile
        with schema_context(self.schema_name):
            AgentProfile.objects.filter(
                user_id=self.user_id
            ).update(last_seen=timezone.now())