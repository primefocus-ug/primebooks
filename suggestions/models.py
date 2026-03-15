"""
reports/models.py

Models:
  Report        — a user-submitted report/complaint/request
  ReportUpdate  — status updates and admin replies on a report
"""

import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


def report_attachment_path(instance, filename):
    return f'suggestions/{instance.ticket_number}/{filename}'


class Suggestion(models.Model):

    TYPE_CHOICES = [
        ('bug',       'Bug / Technical Issue'),
        ('feature',   'Feature Request'),
        ('billing',   'Billing / Payment Complaint'),
        ('complaint', 'User / Staff Complaint'),
        ('data',      'Data Error / Incorrect Record'),
    ]

    PRIORITY_CHOICES = [
        ('low',    'Low'),
        ('medium', 'Medium'),
        ('high',   'High'),
        ('urgent', 'Urgent'),
    ]

    STATUS_CHOICES = [
        ('open',        'Open'),
        ('in_progress', 'In Progress'),
        ('waiting',     'Waiting on User'),
        ('resolved',    'Resolved'),
        ('closed',      'Closed'),
    ]

    # ── Identity ──
    ticket_number = models.CharField(max_length=12, unique=True, editable=False)
    submitted_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, related_name='reports',
    )

    # ── Classification ──
    type          = models.CharField(max_length=20, choices=TYPE_CHOICES)
    priority      = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    status        = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')

    # ── Content ──
    title         = models.CharField(max_length=160)
    description   = models.TextField()
    affected_url  = models.CharField(max_length=500, blank=True, help_text='Auto-captured page URL')
    affected_record = models.CharField(max_length=200, blank=True, help_text='e.g. Invoice #1042')
    screenshot    = models.ImageField(upload_to=report_attachment_path, null=True, blank=True)

    # ── Meta ──
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)
    resolved_at   = models.DateTimeField(null=True, blank=True)

    # ── Admin ──
    assigned_to   = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_reports',
    )
    internal_note = models.TextField(blank=True, help_text='Private note — not visible to the user.')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Report'
        verbose_name_plural = 'Reports'

    def __str__(self):
        return f'[{self.ticket_number}] {self.title}'

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            self.ticket_number = self._generate_ticket_number()
        if self.status == 'resolved' and not self.resolved_at:
            self.resolved_at = timezone.now()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_ticket_number():
        """Generates e.g. PB-A3F9C2"""
        uid = uuid.uuid4().hex[:6].upper()
        return f'PB-{uid}'

    def get_priority_colour(self):
        return {
            'low':    '#22c55e',
            'medium': '#f59e0b',
            'high':   '#ef4444',
            'urgent': '#dc2626',
        }.get(self.priority, '#6b7280')

    def get_status_colour(self):
        return {
            'open':        '#3b82f6',
            'in_progress': '#8b5cf6',
            'waiting':     '#f59e0b',
            'resolved':    '#22c55e',
            'closed':      '#6b7280',
        }.get(self.status, '#6b7280')


class SuggestionUpdate(models.Model):
    """
    A timeline entry on a report — either an admin reply or a status change.
    Visible to the submitting user unless is_internal=True.
    """

    UPDATE_TYPE_CHOICES = [
        ('reply',          'Reply'),
        ('status_change',  'Status Change'),
        ('note',           'Internal Note'),
    ]

    report       = models.ForeignKey(Suggestion, on_delete=models.CASCADE, related_name='updates')
    author       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
    )
    update_type  = models.CharField(max_length=20, choices=UPDATE_TYPE_CHOICES, default='reply')
    message      = models.TextField(blank=True)
    old_status   = models.CharField(max_length=20, blank=True)
    new_status   = models.CharField(max_length=20, blank=True)
    is_internal  = models.BooleanField(default=False, help_text='If True, only admins see this update.')
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Report Update'

    def __str__(self):
        return f'{self.report.ticket_number} — {self.update_type} at {self.created_at:%Y-%m-%d %H:%M}'


class SuggestionFeedback(models.Model):
    """
    One-per-ticket satisfaction rating submitted by the user after resolution.
    Visible to admins; never shown to other users.
    """

    RATING_CHOICES = [
        (1, '1 — Very poor'),
        (2, '2 — Poor'),
        (3, '3 — Okay'),
        (4, '4 — Good'),
        (5, '5 — Excellent'),
    ]

    report       = models.OneToOneField(
        Suggestion, on_delete=models.CASCADE, related_name='feedback',
    )
    rating       = models.PositiveSmallIntegerField(
        choices=RATING_CHOICES,
        help_text='1–5 star satisfaction rating.',
    )
    resolved_ok  = models.BooleanField(
        help_text="Did this ticket resolve the user's issue?",
    )
    comment      = models.TextField(
        blank=True,
        help_text='Optional free-text comment from the user.',
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'Report Feedback'
        verbose_name_plural = 'Report Feedback'

    def __str__(self):
        resolved_icon = '✓' if self.resolved_ok else '✗'
        return f'{self.report.ticket_number} — {resolved_icon} — {self.rating}/5'