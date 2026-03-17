"""
support_widget/serializers.py

DRF serializers for the mobile API.

Two personas:
  - Visitor  — identified by session_token (UUID), no Django user account required
  - Agent    — authenticated Django user with AgentProfile

All serializers are intentionally explicit (no ModelSerializer auto-magic
for sensitive fields) so the API surface is predictable for mobile clients.
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import (
    SupportWidgetConfig, VisitorSession, ChatMessage,
    FAQ, AgentProfile, CallSession, CallRecording,
)

User = get_user_model()


# ── Config ────────────────────────────────────────────────────────────────────

class WidgetConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model  = SupportWidgetConfig
        fields = [
            'greeting_message', 'widget_title', 'brand_color',
            'is_active', 'business_hours_message', 'call_recording_notice',
        ]


# ── Visitor Session ────────────────────────────────────────────────────────────

class VisitorSessionCreateSerializer(serializers.Serializer):
    """POST /api/support/session/ — start a new session"""
    referrer_url = serializers.URLField(required=False, allow_blank=True, max_length=500)
    user_agent   = serializers.CharField(required=False, allow_blank=True, max_length=500)
    platform     = serializers.ChoiceField(
        choices=['web', 'android', 'ios', 'desktop'],
        default='web',
        help_text="Client platform — used for analytics."
    )


class VisitorSessionUpdateSerializer(serializers.Serializer):
    """PATCH /api/support/session/<token>/ — set name/email"""
    name  = serializers.CharField(max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)


class VisitorSessionSerializer(serializers.ModelSerializer):
    agent_name = serializers.SerializerMethodField()

    class Meta:
        model  = VisitorSession
        fields = [
            'session_token', 'visitor_name', 'visitor_email',
            'status', 'agent_name', 'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_agent_name(self, obj):
        if obj.assigned_agent:
            return obj.assigned_agent.get_full_name() or obj.assigned_agent.username
        return None


# ── Chat Message ───────────────────────────────────────────────────────────────

class ChatMessageSerializer(serializers.ModelSerializer):
    agent_name = serializers.SerializerMethodField()

    class Meta:
        model  = ChatMessage
        fields = ['id', 'sender', 'agent_name', 'body', 'is_read', 'created_at']
        read_only_fields = fields

    def get_agent_name(self, obj):
        if obj.agent_user:
            return obj.agent_user.get_full_name() or obj.agent_user.username
        return None


class SendMessageSerializer(serializers.Serializer):
    """POST /api/support/session/<token>/message/ — visitor sends a message"""
    body = serializers.CharField(max_length=4000, trim_whitespace=True)


class AgentSendMessageSerializer(serializers.Serializer):
    """POST /api/support/agent/session/<token>/message/ — agent sends a message"""
    body = serializers.CharField(max_length=4000, trim_whitespace=True)


# ── FAQ ────────────────────────────────────────────────────────────────────────

class FAQSerializer(serializers.ModelSerializer):
    class Meta:
        model  = FAQ
        fields = ['id', 'question', 'answer', 'sort_order']


# ── Agent ──────────────────────────────────────────────────────────────────────

class AgentProfileSerializer(serializers.ModelSerializer):
    user_id      = serializers.IntegerField(source='user.pk', read_only=True)
    display_name = serializers.CharField()
    avatar_url   = serializers.SerializerMethodField()

    class Meta:
        model  = AgentProfile
        fields = ['user_id', 'display_name', 'avatar_url', 'status', 'accept_calls', 'last_seen']

    def get_avatar_url(self, obj):
        if obj.avatar:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.avatar.url) if request else obj.avatar.url
        return None


class AgentStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['online', 'busy', 'offline'])


class AgentSessionListSerializer(serializers.ModelSerializer):
    """Compact session row for the agent's queue list."""
    agent_name   = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model  = VisitorSession
        fields = [
            'session_token', 'visitor_name', 'visitor_email',
            'status', 'agent_name', 'unread_count', 'created_at',
        ]

    def get_agent_name(self, obj):
        if obj.assigned_agent:
            return obj.assigned_agent.get_full_name() or obj.assigned_agent.username
        return None

    def get_unread_count(self, obj):
        return obj.messages.filter(sender='visitor', is_read=False).count()


# ── Call ───────────────────────────────────────────────────────────────────────

class CallSessionSerializer(serializers.ModelSerializer):
    visitor_name = serializers.CharField(source='session.visitor_name', read_only=True)
    agent_name   = serializers.SerializerMethodField()
    has_recording = serializers.SerializerMethodField()

    class Meta:
        model  = CallSession
        fields = [
            'call_room_id', 'visitor_name', 'agent_name', 'status',
            'duration_secs', 'started_at', 'ended_at',
            'recording_consent_given', 'has_recording', 'created_at',
        ]

    def get_agent_name(self, obj):
        if obj.agent:
            return obj.agent.get_full_name() or obj.agent.username
        return None

    def get_has_recording(self, obj):
        return hasattr(obj, 'recording')


class CallCreateSerializer(serializers.Serializer):
    """POST /api/support/call/create/"""
    session_token = serializers.UUIDField()


# ── Push token (mobile) ────────────────────────────────────────────────────────

class PushTokenSerializer(serializers.Serializer):
    """
    POST /api/support/push-token/
    Registers a mobile push token so agents get FCM/APNs notifications
    when a new session or call arrives.
    """
    token    = serializers.CharField(max_length=512)
    platform = serializers.ChoiceField(choices=['fcm', 'apns'])