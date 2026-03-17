"""
support_widget/models.py

Tenant-scoped customer support chat widget with WebRTC voice calling.

Models:
  SupportWidgetConfig   — Per-tenant widget configuration
  VisitorSession        — A visitor's support session (name, email, token)
  ChatMessage           — Individual chat messages in a session
  FAQ                   — Tenant-managed FAQ entries shown to visitors
  AgentProfile          — Links a tenant user to agent settings/availability
  CallSession           — WebRTC voice call session between visitor and agent
  CallRecording         — Reference to a recorded call file
"""

import uuid
from django.db   import models
from django.conf import settings
from django.utils import timezone


# ── Widget Configuration (per tenant) ────────────────────────────────────────

class SupportWidgetConfig(models.Model):
    """One record per tenant — controls widget appearance and behaviour."""

    # Greeting & branding
    greeting_message  = models.CharField(
        max_length=255,
        default="👋 Hi there! How can we help you today?",
    )
    widget_title      = models.CharField(max_length=100, default="Support")
    brand_color       = models.CharField(max_length=7, default="#6366f1",
                                         help_text="Hex colour, e.g. #6366f1")
    logo              = models.ImageField(upload_to='support_widget/logos/', null=True, blank=True)

    # Availability
    is_active              = models.BooleanField(default=True)
    business_hours_message = models.CharField(
        max_length=255,
        default="Our agents are currently offline. Leave a message and we'll reply shortly.",
        blank=True,
    )
    offline_email         = models.EmailField(
        blank=True,
        help_text="Fallback email for offline messages.",
    )

    # Call recording consent text
    call_recording_notice = models.TextField(
        default=(
            "⚠️ This call is recorded for quality and training purposes. "
            "By continuing you consent to the recording."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Support Widget Config"

    def __str__(self):
        return f"Widget Config ({self.pk})"


# ── Visitor Session ────────────────────────────────────────────────────────────

class VisitorSession(models.Model):
    """
    One record per visitor conversation.
    The session_token is used in WebSocket URLs and API calls.
    It is deliberately not a ForeignKey to any user — visitors are anonymous
    until they provide their name/email.
    """

    STATUS_CHOICES = [
        ('onboarding',  'Onboarding'),       # collecting name/email
        ('faq',         'FAQ'),              # browsing FAQ suggestions
        ('chatting',    'Chatting'),         # live chat open
        ('escalated',   'Escalated'),        # waiting for agent
        ('in_call',     'In Call'),          # WebRTC call active
        ('resolved',    'Resolved'),         # session closed
    ]

    session_token  = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    visitor_name   = models.CharField(max_length=150, blank=True)
    visitor_email  = models.EmailField(blank=True)
    status         = models.CharField(max_length=20, choices=STATUS_CHOICES, default='onboarding')

    # Assigned agent (set when escalated)
    assigned_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='assigned_support_sessions',
    )

    # Page visitor was on when they opened the widget
    referrer_url   = models.URLField(blank=True, max_length=500)
    user_agent     = models.CharField(max_length=500, blank=True)

    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)
    resolved_at    = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Visitor Session"

    def __str__(self):
        name = self.visitor_name or "Anonymous"
        return f"{name} [{self.status}] — {self.session_token}"

    def resolve(self):
        self.status = 'resolved'
        self.resolved_at = timezone.now()
        self.save(update_fields=['status', 'resolved_at'])


# ── Chat Message ───────────────────────────────────────────────────────────────

class ChatMessage(models.Model):
    """A single message in a visitor session."""

    SENDER_CHOICES = [
        ('visitor', 'Visitor'),
        ('agent',   'Agent'),
        ('bot',     'Bot'),
        ('system',  'System'),
    ]

    session    = models.ForeignKey(VisitorSession, on_delete=models.CASCADE,
                                   related_name='messages')
    sender     = models.CharField(max_length=10, choices=SENDER_CHOICES)
    # For agent messages, link the user
    agent_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='sent_support_messages',
    )
    body       = models.TextField()
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = "Chat Message"

    def __str__(self):
        return f"[{self.sender}] {self.body[:60]}"


# ── FAQ ────────────────────────────────────────────────────────────────────────

class FAQ(models.Model):
    """Tenant-managed FAQ entries surfaced in the widget."""

    question   = models.CharField(max_length=300)
    answer     = models.TextField()
    keywords   = models.CharField(
        max_length=500, blank=True,
        help_text="Comma-separated keywords to improve search matching.",
    )
    is_active  = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'question']
        verbose_name = "FAQ"

    def __str__(self):
        return self.question[:80]

    def matches(self, query: str) -> bool:
        """Simple keyword / question match for FAQ suggestion."""
        q = query.lower()
        if q in self.question.lower():
            return True
        for kw in self.keywords.split(','):
            if kw.strip() and kw.strip().lower() in q:
                return True
        return False


# ── Agent Profile ──────────────────────────────────────────────────────────────

class AgentProfile(models.Model):
    """Links a tenant user to their support agent settings."""

    STATUS_CHOICES = [
        ('online',  'Online'),
        ('busy',    'Busy'),
        ('offline', 'Offline'),
    ]

    user            = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='agent_profile',
    )
    display_name    = models.CharField(max_length=150, blank=True)
    avatar          = models.ImageField(upload_to='support_widget/avatars/', null=True, blank=True)
    status          = models.CharField(max_length=10, choices=STATUS_CHOICES, default='offline')
    accept_calls    = models.BooleanField(default=True,
                                          help_text="Allow incoming WebRTC calls.")
    last_seen       = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Agent Profile"

    def __str__(self):
        return f"Agent: {self.display_name or self.user}"

    def go_online(self):
        self.status = 'online'
        self.last_seen = timezone.now()
        self.save(update_fields=['status', 'last_seen'])

    def go_offline(self):
        self.status = 'offline'
        self.last_seen = timezone.now()
        self.save(update_fields=['status', 'last_seen'])

    @classmethod
    def available_agents(cls):
        return cls.objects.filter(status='online', accept_calls=True)


# ── Call Session ───────────────────────────────────────────────────────────────

class CallSession(models.Model):
    """
    A WebRTC voice call session.
    The call_room_id is the shared room identifier passed to both sides.
    Signaling (SDP offer/answer + ICE candidates) flows through Django Channels.
    """

    CALL_STATUS = [
        ('pending',   'Pending'),      # created, waiting for agent to accept
        ('ringing',   'Ringing'),      # agent notified
        ('active',    'Active'),       # both sides connected
        ('ended',     'Ended'),
        ('missed',    'Missed'),       # agent did not answer
        ('rejected',  'Rejected'),
    ]

    call_room_id   = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    session        = models.ForeignKey(VisitorSession, on_delete=models.CASCADE,
                                       related_name='calls')
    agent          = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='handled_calls',
    )
    status         = models.CharField(max_length=10, choices=CALL_STATUS, default='pending')
    started_at     = models.DateTimeField(null=True, blank=True)
    ended_at       = models.DateTimeField(null=True, blank=True)
    duration_secs  = models.PositiveIntegerField(default=0)

    # Whether consent banner was acknowledged
    recording_consent_given = models.BooleanField(default=False)

    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Call Session"

    def __str__(self):
        return f"Call {self.call_room_id} [{self.status}]"

    @property
    def duration_display(self):
        m, s = divmod(self.duration_secs, 60)
        return f"{m}m {s}s"

    def end_call(self):
        self.ended_at = timezone.now()
        if self.started_at:
            self.duration_secs = int((self.ended_at - self.started_at).total_seconds())
        self.status = 'ended'
        self.save(update_fields=['status', 'ended_at', 'duration_secs'])


# ── Call Recording ─────────────────────────────────────────────────────────────

class CallRecording(models.Model):
    """File reference for a recorded call (uploaded after call ends)."""

    call      = models.OneToOneField(CallSession, on_delete=models.CASCADE,
                                     related_name='recording')
    file      = models.FileField(upload_to='support_widget/recordings/%Y/%m/')
    file_size = models.PositiveIntegerField(default=0, help_text="Bytes")
    duration  = models.PositiveIntegerField(default=0, help_text="Seconds")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Call Recording"

    def __str__(self):
        return f"Recording for Call {self.call.call_room_id}"