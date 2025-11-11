from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.conf import settings


def validate_file_size(file):
    """Validate uploaded file size"""
    max_size = getattr(settings, 'EXPENSE_ATTACHMENT_MAX_SIZE', 5 * 1024 * 1024)

    if file.size > max_size:
        raise ValidationError(
            _('File size exceeds maximum allowed size of %(max_size)s MB'),
            params={'max_size': max_size / (1024 * 1024)}
        )


def validate_file_type(file):
    """Validate uploaded file type"""
    allowed_types = getattr(settings, 'EXPENSE_ATTACHMENT_ALLOWED_TYPES', [])

    if not allowed_types:
        return

    content_type = file.content_type

    if content_type not in allowed_types:
        raise ValidationError(
            _('File type "%(type)s" is not allowed. Allowed types: images, PDFs, documents'),
            params={'type': content_type}
        )


def validate_expense_date(date):
    """Validate expense date is not in future"""
    from django.utils import timezone

    if date > timezone.now().date():
        raise ValidationError(
            _('Expense date cannot be in the future')
        )


def validate_due_date(expense_date, due_date):
    """Validate due date is after expense date"""
    if due_date and expense_date and due_date < expense_date:
        raise ValidationError(
            _('Due date cannot be before expense date')
        )