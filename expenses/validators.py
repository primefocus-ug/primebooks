"""
validators.py

Changes from original:
  • validate_file_type now distinguishes receipts (images + PDF only)
    from general attachments, and uses python-magic when available for
    true MIME detection rather than trusting the browser Content-Type.
  • validate_receipt_file — convenience composite validator for the
    Expense.receipt field used in ExpenseForm.
  • validate_amount — guards against suspiciously large or zero amounts.
  • validate_exchange_rate — must be positive.
  • validate_due_date signature unchanged (backward compatible).
  • validate_expense_date: future-date check preserved.
"""

import logging
import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

# Allowed MIME types for receipt uploads
RECEIPT_ALLOWED_MIME_TYPES = {
    'image/jpeg',
    'image/png',
    'image/webp',
    'image/gif',
    'image/heic',
    'application/pdf',
}

# Maximum receipt file size (default 10 MB)
RECEIPT_MAX_SIZE_BYTES = getattr(settings, 'EXPENSE_RECEIPT_MAX_SIZE', 10 * 1024 * 1024)

# Maximum general attachment size (default 5 MB)
ATTACHMENT_MAX_SIZE_BYTES = getattr(settings, 'EXPENSE_ATTACHMENT_MAX_SIZE', 5 * 1024 * 1024)


# ---------------------------------------------------------------------------
# File validators
# ---------------------------------------------------------------------------

def validate_file_size(file, max_bytes: int = ATTACHMENT_MAX_SIZE_BYTES):
    """Raise ValidationError if the file exceeds *max_bytes*."""
    if file.size > max_bytes:
        max_mb = max_bytes / (1024 * 1024)
        raise ValidationError(
            _('File size %(size).1f MB exceeds the maximum of %(max).1f MB.'),
            params={'size': file.size / (1024 * 1024), 'max': max_mb},
        )


def validate_file_type(file, allowed_types: set | None = None):
    """
    Validate the MIME type of an uploaded file.

    Uses python-magic for true MIME detection when available; falls back to
    the browser-supplied Content-Type header otherwise.
    """
    if allowed_types is None:
        # Default: use the project setting or allow any type
        allowed_types = set(
            getattr(settings, 'EXPENSE_ATTACHMENT_ALLOWED_TYPES', [])
        )

    if not allowed_types:
        return  # No restriction configured

    # Try python-magic first
    detected_type = _detect_mime(file)
    content_type = detected_type or getattr(file, 'content_type', '')

    if content_type and content_type not in allowed_types:
        raise ValidationError(
            _('File type "%(type)s" is not allowed.'),
            params={'type': content_type},
        )


def validate_receipt_file(file):
    """
    Composite validator for Expense.receipt:
      1. File size ≤ RECEIPT_MAX_SIZE_BYTES
      2. MIME type must be an image or PDF
    """
    validate_file_size(file, max_bytes=RECEIPT_MAX_SIZE_BYTES)
    validate_file_type(file, allowed_types=RECEIPT_ALLOWED_MIME_TYPES)


def _detect_mime(file) -> str | None:
    """Attempt true MIME detection via python-magic. Returns None on failure."""
    try:
        import magic  # python-magic
        file.seek(0)
        header = file.read(2048)
        file.seek(0)
        return magic.from_buffer(header, mime=True)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Date validators
# ---------------------------------------------------------------------------

def validate_expense_date(date):
    """Expense date must not be in the future."""
    from django.utils import timezone

    if date > timezone.now().date():
        raise ValidationError(_('Expense date cannot be in the future.'))


def validate_due_date(expense_date, due_date):
    """Due date must not be before the expense date."""
    if due_date and expense_date and due_date < expense_date:
        raise ValidationError(_('Due date cannot be before the expense date.'))


# ---------------------------------------------------------------------------
# Amount validators
# ---------------------------------------------------------------------------

def validate_amount(value):
    """
    Raise ValidationError for implausible amounts:
      • Zero or negative (already enforced by MinValueValidator on the model,
        but useful as a standalone form validator too)
      • Unreasonably large (> 1,000,000,000 — configurable)
    """
    from decimal import Decimal

    max_amount = Decimal(
        str(getattr(settings, 'EXPENSE_MAX_SINGLE_AMOUNT', 1_000_000_000))
    )

    if value <= 0:
        raise ValidationError(_('Amount must be greater than zero.'))

    if value > max_amount:
        raise ValidationError(
            _('Amount %(value)s exceeds the maximum allowed value of %(max)s.'),
            params={'value': value, 'max': max_amount},
        )


def validate_exchange_rate(value):
    """Exchange rate must be a positive number."""
    if value <= 0:
        raise ValidationError(_('Exchange rate must be greater than zero.'))