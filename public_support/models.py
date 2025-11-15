from django.db import models
from django.utils import timezone
import uuid


class SupportTicket(models.Model):
    """Pre-sales support tickets"""

    STATUS_CHOICES = [
        ('NEW', 'New'),
        ('OPEN', 'Open'),
        ('PENDING', 'Pending'),
        ('RESOLVED', 'Resolved'),
        ('CLOSED', 'Closed'),
    ]

    PRIORITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('URGENT', 'Urgent'),
    ]

    CATEGORY_CHOICES = [
        ('SALES', 'Sales Inquiry'),
        ('DEMO', 'Demo Request'),
        ('PRICING', 'Pricing Question'),
        ('TECHNICAL', 'Technical Question'),
        ('FEATURE', 'Feature Request'),
        ('OTHER', 'Other'),
    ]

    # Ticket Info
    ticket_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        primary_key=True
    )
    ticket_number = models.CharField(max_length=20, unique=True, db_index=True)

    # Customer Info
    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    company_name = models.CharField(max_length=255, blank=True)

    # Ticket Details
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    subject = models.CharField(max_length=255)
    message = models.TextField()

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='NEW')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='MEDIUM')

    # Assignment
    assigned_to_email = models.EmailField(blank=True, null=True)

    # Tracking
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    referrer = models.CharField(max_length=500, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # Metrics
    response_time_minutes = models.PositiveIntegerField(null=True, blank=True)
    resolution_time_minutes = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = 'public_support_tickets'
        verbose_name = 'Support Ticket'
        verbose_name_plural = 'Support Tickets'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['email']),
            models.Index(fields=['ticket_number']),
        ]

    def __str__(self):
        return f"{self.ticket_number} - {self.subject}"

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            # Generate ticket number: SUP-YYYYMMDD-XXXX
            today = timezone.now().strftime('%Y%m%d')
            last_ticket = SupportTicket.objects.filter(
                ticket_number__startswith=f'SUP-{today}-'
            ).order_by('-ticket_number').first()

            if last_ticket:
                last_num = int(last_ticket.ticket_number.split('-')[-1])
                new_num = last_num + 1
            else:
                new_num = 1

            self.ticket_number = f'SUP-{today}-{new_num:04d}'

        super().save(*args, **kwargs)

    def mark_resolved(self):
        """Mark ticket as resolved"""
        self.status = 'RESOLVED'
        self.resolved_at = timezone.now()

        # Calculate resolution time
        if self.created_at:
            delta = self.resolved_at - self.created_at
            self.resolution_time_minutes = int(delta.total_seconds() / 60)

        self.save()

    def mark_closed(self):
        """Mark ticket as closed"""
        self.status = 'CLOSED'
        self.closed_at = timezone.now()
        self.save()


class TicketReply(models.Model):
    """Replies to support tickets"""

    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name='replies'
    )

    # Reply Info
    message = models.TextField()
    is_internal_note = models.BooleanField(
        default=False,
        help_text="Internal note (not visible to customer)"
    )

    # Sender Info
    sender_name = models.CharField(max_length=100)
    sender_email = models.EmailField()
    is_staff = models.BooleanField(default=False)

    # Attachments
    has_attachments = models.BooleanField(default=False)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'public_support_replies'
        verbose_name = 'Ticket Reply'
        verbose_name_plural = 'Ticket Replies'
        ordering = ['created_at']

    def __str__(self):
        return f"Reply to {self.ticket.ticket_number} by {self.sender_name}"

    def save(self, *args, **kwargs):
        # Update first response time if this is first staff reply
        if self.is_staff and not self.ticket.first_response_at:
            self.ticket.first_response_at = timezone.now()
            delta = self.ticket.first_response_at - self.ticket.created_at
            self.ticket.response_time_minutes = int(delta.total_seconds() / 60)
            self.ticket.save()

        super().save(*args, **kwargs)


class FAQ(models.Model):
    """Frequently Asked Questions"""

    CATEGORY_CHOICES = [
        ('GENERAL', 'General'),
        ('PRICING', 'Pricing & Plans'),
        ('FEATURES', 'Features'),
        ('TECHNICAL', 'Technical'),
        ('BILLING', 'Billing'),
        ('SECURITY', 'Security & Privacy'),
    ]

    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    question = models.CharField(max_length=255)
    answer = models.TextField()

    # SEO
    slug = models.SlugField(max_length=255, unique=True)
    meta_description = models.CharField(max_length=160, blank=True)

    # Display
    order = models.PositiveIntegerField(default=0)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    # Stats
    view_count = models.PositiveIntegerField(default=0)
    helpful_count = models.PositiveIntegerField(default=0)
    not_helpful_count = models.PositiveIntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'public_support_faq'
        verbose_name = 'FAQ'
        verbose_name_plural = 'FAQs'
        ordering = ['order', '-is_featured', 'question']

    def __str__(self):
        return self.question

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.question)
        super().save(*args, **kwargs)

    def increment_views(self):
        """Increment view count"""
        self.view_count += 1
        self.save(update_fields=['view_count'])

    def mark_helpful(self):
        """Mark as helpful"""
        self.helpful_count += 1
        self.save(update_fields=['helpful_count'])

    def mark_not_helpful(self):
        """Mark as not helpful"""
        self.not_helpful_count += 1
        self.save(update_fields=['not_helpful_count'])


class ContactRequest(models.Model):
    """Contact form submissions"""

    REQUEST_TYPES = [
        ('GENERAL', 'General Inquiry'),
        ('DEMO', 'Request Demo'),
        ('SALES', 'Talk to Sales'),
        ('PARTNERSHIP', 'Partnership'),
        ('PRESS', 'Press Inquiry'),
    ]

    # Contact Info
    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    company = models.CharField(max_length=255, blank=True)
    job_title = models.CharField(max_length=100, blank=True)

    # Request Details
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPES)
    message = models.TextField()

    # Additional Info
    company_size = models.CharField(
        max_length=20,
        choices=[
            ('1-10', '1-10 employees'),
            ('11-50', '11-50 employees'),
            ('51-200', '51-200 employees'),
            ('201-500', '201-500 employees'),
            ('500+', '500+ employees'),
        ],
        blank=True
    )

    # Status
    is_processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # Tracking
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'public_support_contact_requests'
        verbose_name = 'Contact Request'
        verbose_name_plural = 'Contact Requests'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_request_type_display()} from {self.name}"

    def mark_processed(self):
        """Mark as processed"""
        self.is_processed = True
        self.processed_at = timezone.now()
        self.save()