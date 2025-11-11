from django.db import models
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from django.core.validators import FileExtensionValidator
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import os
import base64
import json

User = get_user_model()

class SystemAnnouncement(models.Model):
    """
    System-wide announcements from SaaS admin to all tenants
    """
    ANNOUNCEMENT_TYPE = [
        ('info', 'Information'),
        ('warning', 'Warning'),
        ('maintenance', 'Maintenance'),
        ('update', 'Update'),
        ('feature', 'New Feature'),
        ('critical', 'Critical Alert'),
    ]

    PRIORITY = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    title = models.CharField(max_length=255)
    message = models.TextField()
    announcement_type = models.CharField(
        max_length=20,
        choices=ANNOUNCEMENT_TYPE,
        default='info'
    )
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY,
        default='medium'
    )

    # Targeting
    target_all_tenants = models.BooleanField(
        default=True,
        help_text="Send to all tenants"
    )
    target_tenant_ids = models.JSONField(
        default=list,
        help_text="Specific tenant IDs if not all"
    )
    target_user_roles = models.JSONField(
        default=list,
        help_text="Target specific roles: ['admin', 'manager', etc.]"
    )

    # Scheduling
    scheduled_for = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Schedule for future delivery"
    )
    is_sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)

    # Display settings
    show_in_app = models.BooleanField(
        default=True,
        help_text="Show as in-app notification"
    )
    send_email = models.BooleanField(
        default=False,
        help_text="Send email notification"
    )
    is_dismissible = models.BooleanField(
        default=True,
        help_text="Users can dismiss this announcement"
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Auto-hide after this date"
    )

    # Metadata
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_announcements'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Action button (optional)
    action_text = models.CharField(
        max_length=100,
        blank=True,
        help_text="Button text (e.g., 'Learn More')"
    )
    action_url = models.URLField(
        blank=True,
        help_text="URL for action button"
    )

    class Meta:
        db_table = 'messaging_system_announcements'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_sent', 'scheduled_for']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_announcement_type_display()})"

    def mark_as_sent(self):
        """Mark announcement as sent"""
        self.is_sent = True
        self.sent_at = timezone.now()
        self.save()


class AnnouncementRead(models.Model):
    """
    Track which users have read/dismissed announcements
    """
    announcement = models.ForeignKey(
        SystemAnnouncement,
        on_delete=models.CASCADE,
        related_name='reads'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='announcement_reads'
    )
    read_at = models.DateTimeField(auto_now_add=True)
    is_dismissed = models.BooleanField(default=False)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'messaging_announcement_reads'
        unique_together = [['announcement', 'user']]
        indexes = [
            models.Index(fields=['user', 'is_dismissed']),
        ]


class MessageAuditLog(models.Model):
    """
    Audit log for admin monitoring
    Stores metadata only, not actual message content (for privacy)
    """
    ACTION_TYPES = [
        ('created', 'Message Created'),
        ('edited', 'Message Edited'),
        ('deleted', 'Message Deleted'),
        ('conversation_created', 'Conversation Created'),
        ('participant_added', 'Participant Added'),
        ('participant_removed', 'Participant Removed'),
    ]

    action_type = models.CharField(
        max_length=30,
        choices=ACTION_TYPES
    )

    # User who performed action
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='message_actions'
    )

    # Related objects (nullable for flexibility)
    conversation = models.ForeignKey(
        'Conversation',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    message = models.ForeignKey(
        'Message',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # Metadata (no actual message content)
    metadata = models.JSONField(
        default=dict,
        help_text="Additional context (participant count, file count, etc.)"
    )

    # Tenant info (for multi-tenant tracking)
    tenant_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="Tenant ID from django-tenants"
    )
    tenant_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Tenant schema name"
    )

    # Request info
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)

    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'messaging_audit_log'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['action_type', 'timestamp']),
            models.Index(fields=['tenant_id', 'timestamp']),
        ]


class MessagingStatistics(models.Model):
    """
    Daily statistics for admin dashboard
    """
    date = models.DateField()
    tenant_id = models.CharField(max_length=50)
    tenant_name = models.CharField(max_length=255, blank=True)

    # Message stats
    total_messages = models.IntegerField(default=0)
    total_conversations = models.IntegerField(default=0)
    active_users = models.IntegerField(default=0)

    # Conversation breakdown
    direct_conversations = models.IntegerField(default=0)
    group_conversations = models.IntegerField(default=0)

    # File stats
    files_shared = models.IntegerField(default=0)
    total_storage_mb = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'messaging_statistics'
        unique_together = [['date', 'tenant_id']]
        ordering = ['-date']
        indexes = [
            models.Index(fields=['date', 'tenant_id']),
        ]



class EncryptionKeyManager(models.Model):
    """
    Stores user encryption keys (RSA key pairs)

    TENANT-AWARE: Keys stored per tenant schema
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='encryption_keys'
    )
    public_key = models.TextField(
        help_text="RSA public key (PEM format)"
    )
    encrypted_private_key = models.TextField(
        help_text="RSA private key encrypted with user password"
    )
    key_created_at = models.DateTimeField(auto_now_add=True)
    key_version = models.IntegerField(default=1)

    class Meta:
        db_table = 'messaging_encryption_keys'
        indexes = [
            models.Index(fields=['user']),
        ]

    def __str__(self):
        return f"Keys for {self.user.username}"

    @staticmethod
    def generate_rsa_keys():
        """Generate RSA key pair (2048-bit)"""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        public_key = private_key.public_key()

        # Serialize to PEM format
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )

        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        return private_pem.decode(), public_pem.decode()

    def get_public_key_object(self):
        """Load public key object for encryption"""
        return serialization.load_pem_public_key(
            self.public_key.encode(),
            backend=default_backend()
        )


class ConversationType(models.TextChoices):
    """Types of conversations supported"""
    DIRECT = 'direct', 'Direct Message'
    GROUP = 'group', 'Group Chat'
    CHANNEL = 'channel', 'Channel'
    DEPARTMENT = 'department', 'Department'
    BROADCAST = 'broadcast', 'Broadcast'  # NEW: One-way announcements


class Conversation(models.Model):
    """
    Main conversation container

    TENANT-AWARE: Conversations exist within tenant schemas
    CROSS-TENANT: SaaS admins can create cross-tenant conversations
    """
    conversation_type = models.CharField(
        max_length=20,
        choices=ConversationType.choices,
        default=ConversationType.DIRECT
    )
    name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Name for groups/channels only"
    )
    description = models.TextField(blank=True, null=True)

    # Encryption
    encrypted_symmetric_key = models.TextField(
        help_text="AES key encrypted for each participant"
    )

    # Metadata
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_conversations'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Soft delete
    is_active = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    # Cross-tenant support (for SaaS admin only)
    is_cross_tenant = models.BooleanField(
        default=False,
        help_text="Can include users from multiple tenants (SaaS admin only)"
    )

    # Store schemas/companies involved in cross-tenant conversations
    tenant_schemas = models.JSONField(
        default=list,
        help_text="List of tenant schemas involved (for cross-tenant only)"
    )

    # Message retention
    message_retention_days = models.IntegerField(
        default=365,
        help_text="Auto-delete messages older than this (0 = never)"
    )

    class Meta:
        db_table = 'messaging_conversations'
        indexes = [
            models.Index(fields=['conversation_type', 'is_active']),
            models.Index(fields=['created_at']),
            models.Index(fields=['is_cross_tenant']),
            models.Index(fields=['created_by']),
        ]
        ordering = ['-updated_at']

    def __str__(self):
        if self.name:
            prefix = "🌐 " if self.is_cross_tenant else ""
            return f"{prefix}{self.name}"
        return f"{self.get_conversation_type_display()} - {self.id}"

    def generate_symmetric_key(self):
        """Generate AES-256 key for this conversation"""
        return os.urandom(32)  # 256 bits

    def encrypt_key_for_user(self, symmetric_key, user):
        """Encrypt symmetric key with user's public key"""
        public_key = user.encryption_keys.get_public_key_object()

        encrypted_key = public_key.encrypt(
            symmetric_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        return base64.b64encode(encrypted_key).decode()

    @property
    def participant_count(self):
        """Count active participants"""
        return self.participants.filter(is_active=True).count()

    @property
    def message_count(self):
        """Count non-deleted messages"""
        return self.messages.filter(is_deleted=False).count()

    def can_user_access(self, user):
        """Check if user can access this conversation"""
        return self.participants.filter(
            user=user,
            is_active=True
        ).exists()


class ConversationParticipant(models.Model):
    """
    Links users to conversations with permissions

    TENANT-AWARE: Participants within tenant schema
    """
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='participants'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='conversation_memberships'
    )

    # Encrypted conversation key for this user
    encrypted_conversation_key = models.TextField(
        help_text="Conversation symmetric key encrypted with user's public key"
    )

    # Permissions
    can_send_messages = models.BooleanField(default=True)
    can_add_participants = models.BooleanField(default=False)
    can_remove_participants = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False)

    # Status
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(default=timezone.now)
    is_muted = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    left_at = models.DateTimeField(null=True, blank=True)

    # Notifications
    email_notifications = models.BooleanField(default=True)
    push_notifications = models.BooleanField(default=True)

    # Custom display name (optional)
    display_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Custom name for this user in this conversation"
    )

    class Meta:
        db_table = 'messaging_participants'
        unique_together = [['conversation', 'user']]
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['conversation', 'is_active']),
            models.Index(fields=['last_read_at']),
        ]

    def __str__(self):
        return f"{self.user.username} in {self.conversation}"

    def get_unread_count(self):
        """Count unread messages"""
        return self.conversation.messages.filter(
            created_at__gt=self.last_read_at,
            is_deleted=False
        ).exclude(sender=self.user).count()

    def mark_all_as_read(self):
        """Mark all messages as read"""
        self.last_read_at = timezone.now()
        self.save(update_fields=['last_read_at'])


class Message(models.Model):
    """
    Individual encrypted messages

    TENANT-AWARE: Messages stored in tenant schema
    """
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sent_messages'
    )

    # Encrypted content
    encrypted_content = models.TextField(
        help_text="Message encrypted with conversation's symmetric key"
    )
    encrypted_iv = models.CharField(
        max_length=255,
        help_text="Initialization vector for AES encryption"
    )

    # Metadata
    message_hash = models.CharField(
        max_length=255,
        help_text="SHA-256 hash for integrity verification"
    )

    # Message type
    MESSAGE_TYPES = [
        ('text', 'Text'),
        ('file', 'File'),
        ('system', 'System'),
        ('announcement', 'Announcement'),
    ]
    message_type = models.CharField(
        max_length=20,
        choices=MESSAGE_TYPES,
        default='text'
    )

    # Editing
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    original_hash = models.CharField(max_length=255, blank=True, null=True)
    edit_history = models.JSONField(
        default=list,
        help_text="History of edits (timestamps only, not content)"
    )

    # Deletion
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deleted_messages'
    )

    # Reply/Thread
    reply_to = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replies'
    )

    # Pinned message
    is_pinned = models.BooleanField(default=False)
    pinned_at = models.DateTimeField(null=True, blank=True)
    pinned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pinned_messages'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    # Mentions
    mentioned_users = models.ManyToManyField(
        User,
        related_name='message_mentions',
        blank=True
    )

    class Meta:
        db_table = 'messaging_messages'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['sender', 'created_at']),
            models.Index(fields=['is_deleted', 'created_at']),
            models.Index(fields=['is_pinned']),
        ]

    def __str__(self):
        return f"Message {self.id} from {self.sender.username}"

    @staticmethod
    def encrypt_message(content, symmetric_key):
        """
        Encrypt message using AES-256-CBC
        Returns: (encrypted_content, iv)
        """
        iv = os.urandom(16)
        cipher = Cipher(
            algorithms.AES(symmetric_key),
            modes.CBC(iv),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()

        content_bytes = content.encode('utf-8')
        padding_length = 16 - (len(content_bytes) % 16)
        padded_content = content_bytes + bytes([padding_length] * padding_length)

        encrypted = encryptor.update(padded_content) + encryptor.finalize()

        return (
            base64.b64encode(encrypted).decode(),
            base64.b64encode(iv).decode()
        )

    @staticmethod
    def decrypt_message(encrypted_content, iv, symmetric_key):
        """Decrypt message using AES-256-CBC"""
        encrypted_bytes = base64.b64decode(encrypted_content)
        iv_bytes = base64.b64decode(iv)

        cipher = Cipher(
            algorithms.AES(symmetric_key),
            modes.CBC(iv_bytes),
            backend=default_backend()
        )
        decryptor = cipher.decryptor()

        decrypted_padded = decryptor.update(encrypted_bytes) + decryptor.finalize()
        padding_length = decrypted_padded[-1]
        decrypted = decrypted_padded[:-padding_length]

        return decrypted.decode('utf-8')

    @staticmethod
    def calculate_hash(content):
        """Calculate SHA-256 hash of content"""
        digest = hashes.Hash(hashes.SHA256(), backend=default_backend())
        digest.update(content.encode('utf-8'))
        return base64.b64encode(digest.finalize()).decode()


class MessageAttachment(models.Model):
    """
    File attachments for messages

    TENANT-AWARE: Files stored per tenant
    """
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name='attachments'
    )

    # Encrypted file
    encrypted_file = models.FileField(
        upload_to='messaging/attachments/%Y/%m/%d/',
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    'pdf', 'doc', 'docx', 'xls', 'xlsx',
                    'jpg', 'jpeg', 'png', 'gif', 'webp',
                    'zip', 'rar', 'txt', 'csv', 'mp4', 'mp3'
                ]
            )
        ]
    )

    # Metadata (encrypted)
    encrypted_filename = models.CharField(max_length=500)
    encrypted_file_size = models.CharField(max_length=255)
    file_type = models.CharField(max_length=100)
    encrypted_iv = models.CharField(max_length=255)

    # Thumbnails for images
    thumbnail = models.ImageField(
        upload_to='messaging/thumbnails/%Y/%m/%d/',
        null=True,
        blank=True
    )

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'messaging_attachments'
        indexes = [
            models.Index(fields=['message']),
            models.Index(fields=['uploaded_at']),
        ]

    def __str__(self):
        return f"Attachment {self.id} for message {self.message_id}"


class MessageReadReceipt(models.Model):
    """
    Track who has read which messages
    """
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name='read_receipts'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='message_reads'
    )
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'messaging_read_receipts'
        unique_together = [['message', 'user']]
        indexes = [
            models.Index(fields=['message', 'user']),
            models.Index(fields=['user', 'read_at']),
        ]

    def __str__(self):
        return f"{self.user.username} read message {self.message_id}"


class MessageReaction(models.Model):
    """
    Emoji reactions to messages
    """
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name='reactions'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='message_reactions'
    )
    emoji = models.CharField(
        max_length=10,
        help_text="Emoji unicode or shortcode"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'messaging_reactions'
        unique_together = [['message', 'user', 'emoji']]
        indexes = [
            models.Index(fields=['message']),
            models.Index(fields=['user']),
        ]

    def __str__(self):
        return f"{self.user.username} reacted {self.emoji} to message {self.message_id}"


class TypingIndicator(models.Model):
    """
    Temporary storage for typing indicators
    Uses Redis in production, this is DB fallback
    """
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='typing_indicators'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )
    started_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'messaging_typing_indicators'
        unique_together = [['conversation', 'user']]
        indexes = [
            models.Index(fields=['conversation', 'started_at']),
        ]

    def __str__(self):
        return f"{self.user.username} typing in {self.conversation_id}"


class MessageSearchIndex(models.Model):
    """
    Decrypted search index (stored separately for security)
    Only stores hash and keywords, not full content

    TENANT-AWARE: Search index per tenant
    """
    message = models.OneToOneField(
        Message,
        on_delete=models.CASCADE,
        related_name='search_index'
    )
    keywords = models.TextField(
        help_text="Extracted keywords for search (not full content)"
    )
    sender_name = models.CharField(max_length=255)
    conversation_id = models.IntegerField()
    created_at = models.DateTimeField()

    class Meta:
        db_table = 'messaging_search_index'
        indexes = [
            models.Index(fields=['conversation_id', 'created_at']),
            models.Index(fields=['sender_name']),
        ]

    def __str__(self):
        return f"Search index for message {self.message_id}"



class LegalAccessRequest(models.Model):
    """
    Track legal/law enforcement access requests
    For compliance with legal requirements
    """
    REQUEST_STATUS = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('denied', 'Denied'),
        ('fulfilled', 'Fulfilled'),
        ('archived', 'Archived'),
    ]

    REQUEST_TYPE = [
        ('court_order', 'Court Order'),
        ('subpoena', 'Subpoena'),
        ('warrant', 'Search Warrant'),
        ('law_enforcement', 'Law Enforcement Request'),
        ('regulatory', 'Regulatory Investigation'),
    ]

    # Request details
    request_number = models.CharField(
        max_length=100,
        unique=True,
        help_text="Official case/request number"
    )
    request_type = models.CharField(
        max_length=30,
        choices=REQUEST_TYPE
    )
    status = models.CharField(
        max_length=20,
        choices=REQUEST_STATUS,
        default='pending'
    )

    # Requesting authority
    authority_name = models.CharField(
        max_length=255,
        help_text="Name of requesting authority"
    )
    authority_contact = models.EmailField(
        help_text="Contact email"
    )
    badge_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Badge/ID number of requesting officer"
    )

    # Scope of request
    target_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='legal_access_requests'
    )
    target_conversation = models.ForeignKey(
        'Conversation',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    date_range_start = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Start date for messages to retrieve"
    )
    date_range_end = models.DateTimeField(
        null=True,
        blank=True,
        help_text="End date for messages to retrieve"
    )

    # Documentation
    legal_document = models.FileField(
        upload_to='legal_requests/%Y/%m/',
        help_text="Upload court order/warrant/subpoena"
    )
    request_description = models.TextField(
        help_text="Description of what is being requested"
    )

    # Processing
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_legal_requests'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    denial_reason = models.TextField(blank=True)

    # Export details
    export_file = models.FileField(
        upload_to='legal_exports/%Y/%m/',
        null=True,
        blank=True,
        help_text="Exported decrypted messages"
    )
    export_password = models.CharField(
        max_length=255,
        blank=True,
        help_text="Password for encrypted export (store securely!)"
    )
    exported_at = models.DateTimeField(null=True, blank=True)
    exported_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='exported_legal_requests'
    )

    # Audit trail
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Compliance
    retention_until = models.DateField(
        help_text="Delete exported data after this date"
    )
    accessed_count = models.IntegerField(
        default=0,
        help_text="Number of times export was accessed"
    )

    class Meta:
        db_table = 'messaging_legal_access_requests'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['request_number']),
        ]

    def __str__(self):
        return f"{self.request_number} - {self.authority_name}"


class LegalAccessLog(models.Model):
    """
    Audit log for legal access operations
    """
    request = models.ForeignKey(
        LegalAccessRequest,
        on_delete=models.CASCADE,
        related_name='access_logs'
    )
    action = models.CharField(
        max_length=100,
        help_text="Action performed (viewed, exported, downloaded, etc.)"
    )
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True
    )
    ip_address = models.GenericIPAddressField()
    user_agent = models.CharField(max_length=500)
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.JSONField(default=dict)

    class Meta:
        db_table = 'messaging_legal_access_logs'
        ordering = ['-timestamp']


