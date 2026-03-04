"""
tasks.py — Celery tasks for the expenses app
=============================================

Tasks:
  1. process_receipt_ocr          — OCR a receipt file, populate Expense fields
  2. create_recurring_expenses    — Auto-create the next copy of recurring expenses
  3. send_weekly_budget_digest    — Weekly email: spending totals + budget status
                                    (renders expenses/emails/weekly_digest.html)
  4. send_budget_alert_email      — Budget-threshold alert email
                                    (renders expenses/emails/budget_alert.html)
                                    Rate-limited to once per budget per hour via cache.
  5. send_expense_notification_email — Approval workflow status email
                                    (renders expenses/emails/expense_notification.html)
  6. cleanup_stale_receipts       — Delete orphaned receipt files older than N days
  7. check_budget_alerts          — Periodic: scan all budgets and fire alerts (NEW)

EMAIL TEMPLATE LOCATIONS
-------------------------
Put the HTML files in:
  templates/
    expenses/
      emails/
        budget_alert.html         ← rendered by send_budget_alert_email
        weekly_digest.html        ← rendered by send_weekly_budget_digest
        expense_notification.html ← rendered by send_expense_notification_email
        budget_alert.txt          ← plain-text fallback (optional)
        weekly_digest.txt         ← plain-text fallback (optional)
        expense_notification.txt  ← plain-text fallback (optional)

WHEN EACH TASK FIRES
---------------------
  send_budget_alert_email
    • Called by check_budget_alerts every hour (Celery Beat)
    • Called by views._trigger_budget_alert_if_needed after budget create/edit
    • Called by views._check_budgets_after_expense after expense create/edit
    • Rate-limited: at most once per budget per hour (Django cache)

  send_weekly_budget_digest
    • Every Monday 07:00 via Celery Beat

  send_expense_notification_email
    • After expense_approve (event='approved')
    • After expense_reject  (event='rejected')
    • Can also be called from signals.py on ExpenseApproval creation

  check_budget_alerts
    • Every hour via Celery Beat

  create_recurring_expenses
    • Daily at midnight via Celery Beat

  cleanup_stale_receipts
    • Monthly via Celery Beat

REQUIRED SETTINGS
------------------
  EMAIL_BACKEND       = 'django.core.mail.backends.smtp.EmailBackend'
  EMAIL_HOST          = 'smtp.example.com'
  EMAIL_PORT          = 587
  EMAIL_USE_TLS       = True
  EMAIL_HOST_USER     = 'noreply@example.com'
  EMAIL_HOST_PASSWORD = '...'
  DEFAULT_FROM_EMAIL  = 'PrimeBooks <noreply@example.com>'
  SITE_URL            = 'https://yourapp.com'

CELERY_BEAT_SCHEDULE (add to settings.py)
------------------------------------------
  from celery.schedules import crontab

  CELERY_BEAT_SCHEDULE = {
      'check-budget-alerts': {
          'task': 'expenses.tasks.check_budget_alerts',
          'schedule': crontab(minute=0),                          # every hour
      },
      'weekly-digest': {
          'task': 'expenses.tasks.send_weekly_budget_digest',
          'schedule': crontab(hour=7, minute=0, day_of_week='monday'),
      },
      'create-recurring-expenses': {
          'task': 'expenses.tasks.create_recurring_expenses',
          'schedule': crontab(hour=0, minute=5),                  # daily 00:05
      },
      'cleanup-stale-receipts': {
          'task': 'expenses.tasks.cleanup_stale_receipts',
          'schedule': crontab(hour=2, minute=0, day_of_month='1'), # monthly
      },
  }
"""

from __future__ import annotations

import logging
import os
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)
User = get_user_model()


# ===========================================================================
# 1. Receipt OCR
# ===========================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_receipt_ocr(self, expense_id: int) -> dict:
    """
    Run OCR on the receipt attached to *expense_id* and back-fill:
      • expense.ocr_raw    — raw extracted text
      • expense.ocr_vendor — best-guess vendor name
      • expense.ocr_amount — best-guess total amount

    Uses pytesseract (local) when available; falls back gracefully.
    The caller is responsible for saving the expense beforehand with a
    receipt file already attached.
    """
    from .models import Expense

    try:
        expense = Expense.objects.get(pk=expense_id)
    except Expense.DoesNotExist:
        logger.error("process_receipt_ocr: Expense %s not found", expense_id)
        return {"success": False, "error": "Expense not found"}

    if not expense.receipt:
        logger.info("process_receipt_ocr: Expense %s has no receipt", expense_id)
        return {"success": False, "error": "No receipt attached"}

    if expense.ocr_processed:
        logger.info("process_receipt_ocr: Expense %s already processed", expense_id)
        return {"success": True, "already_processed": True}

    raw_text = ""
    try:
        import pytesseract
        from PIL import Image

        receipt_path = expense.receipt.path
        img = Image.open(receipt_path)
        raw_text = pytesseract.image_to_string(img)
        logger.info("process_receipt_ocr: OCR succeeded for expense %s", expense_id)

    except ImportError:
        logger.warning(
            "process_receipt_ocr: pytesseract/Pillow not installed — skipping OCR for expense %s",
            expense_id,
        )
        return {"success": False, "error": "pytesseract not installed"}

    except Exception as exc:
        logger.exception("process_receipt_ocr: OCR failed for expense %s: %s", expense_id, exc)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"success": False, "error": str(exc)}

    # -----------------------------------------------------------------------
    # Parse vendor and amount from raw text
    # -----------------------------------------------------------------------
    vendor = _extract_vendor(raw_text)
    amount = _extract_amount(raw_text)

    # Persist results
    expense.ocr_raw = raw_text
    expense.ocr_vendor = vendor or ""
    expense.ocr_amount = amount
    expense.ocr_processed = True

    # Auto-fill if the user hasn't already set these fields
    if not expense.vendor and vendor:
        expense.vendor = vendor
    if amount and expense.amount == Decimal("0.01"):
        expense.amount = amount

    expense.save(update_fields=[
        "ocr_raw", "ocr_vendor", "ocr_amount", "ocr_processed",
        "vendor", "amount", "amount_base", "updated_at",
    ])

    return {
        "success": True,
        "vendor": vendor,
        "amount": float(amount) if amount else None,
        "raw_length": len(raw_text),
    }


def _extract_vendor(text: str) -> str:
    """Heuristic: first non-empty line is usually the store/vendor name."""
    for line in text.splitlines():
        line = line.strip()
        if line and len(line) > 2:
            return line[:200]
    return ""


def _extract_amount(text: str) -> Decimal | None:
    """
    Look for patterns like:  TOTAL  $12.50   /   Total: 12.50
    Returns the largest matched amount (most likely the grand total).
    """
    # Patterns ordered from most to least specific
    patterns = [
        r"(?:total|grand\s*total|amount\s*due|balance\s*due)[^\d]*(\d{1,6}[.,]\d{2})",
        r"\$\s*(\d{1,6}[.,]\d{2})",
        r"(\d{1,6}\.\d{2})",
    ]
    candidates: list[Decimal] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            raw = match.group(1).replace(",", ".")
            try:
                candidates.append(Decimal(raw))
            except InvalidOperation:
                pass
        if candidates:
            break  # Use the most-specific pattern that yielded results

    return max(candidates) if candidates else None


# ===========================================================================
# 2. Recurring expense auto-creation
# ===========================================================================

@shared_task
def create_recurring_expenses() -> dict:
    """
    Run daily (e.g. via Celery Beat at midnight).

    For every Expense where is_recurring=True and next_recurrence_date <= today,
    create a copy dated today and advance next_recurrence_date by the interval.
    """
    from .models import Expense

    today = timezone.now().date()
    due = Expense.objects.filter(
        is_recurring=True,
        next_recurrence_date__lte=today,
        recurrence_interval__in=["daily", "weekly", "fortnightly", "monthly", "yearly"],
    ).select_related("user")

    created_count = 0
    for expense in due:
        try:
            _create_recurring_copy(expense, today)
            _advance_recurrence(expense, today)
            created_count += 1
        except Exception as exc:
            logger.exception(
                "create_recurring_expenses: failed for expense %s: %s", expense.pk, exc
            )

    logger.info("create_recurring_expenses: created %d copies", created_count)
    return {"created": created_count, "evaluated": due.count()}


def _create_recurring_copy(expense: "Expense", today) -> "Expense":
    """Clone the expense for today, resetting transient fields."""
    from .models import Expense

    copy = Expense(
        user=expense.user,
        amount=expense.amount,
        currency=expense.currency,
        exchange_rate=expense.exchange_rate,
        description=expense.description,
        vendor=expense.vendor,
        payment_method=expense.payment_method,
        notes=expense.notes,
        is_recurring=True,
        recurrence_interval=expense.recurrence_interval,
        is_important=expense.is_important,
        status="draft",
        date=today,
    )
    copy.save()

    # Copy tags
    tag_names = list(expense.tags.names())
    if tag_names:
        copy.tags.set(*tag_names)

    return copy


def _advance_recurrence(expense: "Expense", from_date) -> None:
    """Move next_recurrence_date forward by one interval."""
    interval = expense.recurrence_interval
    if interval == "daily":
        delta = timedelta(days=1)
    elif interval == "weekly":
        delta = timedelta(weeks=1)
    elif interval == "fortnightly":
        delta = timedelta(days=14)
    elif interval == "monthly":
        # Add ~30 days; for proper month arithmetic use relativedelta if available
        try:
            from dateutil.relativedelta import relativedelta
            next_date = from_date + relativedelta(months=1)
        except ImportError:
            next_date = from_date + timedelta(days=30)
        expense.next_recurrence_date = next_date
        expense.save(update_fields=["next_recurrence_date"])
        return
    elif interval == "yearly":
        try:
            from dateutil.relativedelta import relativedelta
            next_date = from_date + relativedelta(years=1)
        except ImportError:
            next_date = from_date + timedelta(days=365)
        expense.next_recurrence_date = next_date
        expense.save(update_fields=["next_recurrence_date"])
        return
    else:
        return

    expense.next_recurrence_date = from_date + delta
    expense.save(update_fields=["next_recurrence_date"])


# ===========================================================================
# 3. Weekly budget digest
# ===========================================================================

@shared_task
def send_weekly_budget_digest() -> dict:
    """
    Run every Monday morning via Celery Beat.

    Sends each active user a rich weekly digest covering:
      - Week & month spending totals
      - Top 5 expenses this week
      - Budget status for all active budgets
      - Top spending tag & largest single expense

    Schedule in CELERY_BEAT_SCHEDULE:
        'weekly-digest': {
            'task': 'expenses.tasks.send_weekly_budget_digest',
            'schedule': crontab(hour=7, minute=0, day_of_week='monday'),
        }
    """
    from .models import Budget

    # Send to every active user who has either a budget OR at least one expense
    # (not just budget owners, so new users who haven't set up budgets still get a digest)
    user_ids = set(
        Budget.objects.filter(is_active=True)
        .values_list("user_id", flat=True)
    )

    # Also include users with expenses in the past month
    from .models import Expense
    from django.utils import timezone as tz
    recent_cutoff = tz.now().date().replace(day=1)
    expense_user_ids = set(
        Expense.objects.filter(date__gte=recent_cutoff)
        .values_list("user_id", flat=True)
    )
    all_user_ids = user_ids | expense_user_ids

    users_notified = 0
    for user_id in all_user_ids:
        try:
            user = User.objects.get(pk=user_id, is_active=True)
            if user.email:
                _send_digest_for_user(user)
                users_notified += 1
        except User.DoesNotExist:
            continue
        except Exception as exc:
            logger.exception("send_weekly_budget_digest: failed for user %s: %s", user_id, exc)

    logger.info("send_weekly_budget_digest: notified %d users", users_notified)
    return {"users_notified": users_notified}


def _send_digest_for_user(user) -> None:
    """
    Build the full weekly digest context and send the email for one user.
    Renders expenses/emails/weekly_digest.html (the upgraded HTML template).
    """
    from .models import Budget, Expense
    from django.db.models import Avg, Count, Max, Sum

    today      = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())   # Monday
    week_end   = week_start + timedelta(days=6)            # Sunday
    month_start = today.replace(day=1)

    # ── Week aggregates ──────────────────────────────────────────────────────
    week_qs = Expense.objects.filter(user=user, date__gte=week_start, date__lte=week_end)
    week_agg = week_qs.aggregate(
        total=Sum("amount_base"),
        count=Count("id"),
        largest=Max("amount_base"),
    )
    week_total   = week_agg["total"]   or Decimal("0")
    week_count   = week_agg["count"]   or 0
    week_largest = week_agg["largest"] or Decimal("0")
    daily_avg    = week_total / 7

    # ── Month total ──────────────────────────────────────────────────────────
    month_total = (
        Expense.objects.filter(user=user, date__gte=month_start, date__lte=today)
        .aggregate(t=Sum("amount_base"))["t"] or Decimal("0")
    )

    # ── Top 5 expenses this week ─────────────────────────────────────────────
    top_expenses = list(
        week_qs.prefetch_related("tags").order_by("-amount_base")[:5]
    )

    # ── Top tag this week ────────────────────────────────────────────────────
    tag_totals: dict[str, Decimal] = {}
    for exp in week_qs.prefetch_related("tags"):
        for tag in exp.tags.all():
            tag_totals[tag.name] = tag_totals.get(tag.name, Decimal("0")) + exp.amount_base
    week_top_tag = max(tag_totals, key=tag_totals.get) if tag_totals else None

    # ── Budget statuses ──────────────────────────────────────────────────────
    budget_statuses = []
    alerts = []
    for b in Budget.objects.filter(user=user, is_active=True):
        pct   = float(b.get_percentage_used())
        spent = float(b.get_current_spending())
        entry = {
            "name":       b.name,
            "amount":     float(b.amount),
            "spent":      spent,
            "remaining":  float(b.get_remaining()),
            "percentage": round(pct, 1),
            "period":     b.get_period_display(),
            "status":     b.get_status_color(),
        }
        budget_statuses.append(entry)
        if b.is_over_threshold():
            alerts.append(entry)

    # ── Subject line ─────────────────────────────────────────────────────────
    subject = f"📊 Your Weekly Digest – {week_start.strftime('%d %b')} to {week_end.strftime('%d %b %Y')}"
    if alerts:
        subject = f"⚠️ {len(alerts)} Budget Alert(s) — {subject}"

    context = {
        "user":            user,
        "week_start":      week_start,
        "week_end":        week_end,
        "week_total":      week_total,
        "week_count":      week_count,
        "week_largest":    week_largest,
        "week_top_tag":    week_top_tag,
        "daily_avg":       daily_avg,
        "month_total":     month_total,
        "top_expenses":    top_expenses,
        "budget_statuses": budget_statuses,  # used by weekly_digest.html
        "budget_summaries": budget_statuses, # alias kept for backward compat
        "alerts":          alerts,
        "period_label":    "Weekly",
        "site_url":        getattr(settings, "SITE_URL", ""),
    }

    # ── HTML body ────────────────────────────────────────────────────────────
    try:
        html_body = render_to_string("expenses/emails/weekly_digest.html", context)
    except Exception as exc:
        logger.warning("Could not render weekly_digest.html for user %s: %s", user.pk, exc)
        html_body = None

    # ── Plain-text fallback ──────────────────────────────────────────────────
    try:
        text_body = render_to_string("expenses/emails/weekly_digest.txt", context)
    except Exception:
        lines = [
            f"Hi {user.get_full_name() or user.username},",
            "",
            f"Week: {week_start.strftime('%d %b')} – {week_end.strftime('%d %b %Y')}",
            f"Total spent this week: {week_total:,.0f} UGX ({week_count} expenses)",
            f"Month total: {month_total:,.0f} UGX",
            "",
        ]
        if top_expenses:
            lines.append("Top expenses:")
            for e in top_expenses:
                lines.append(f"  • {e.description}: {e.amount_base:,.0f} UGX ({e.date})")
            lines.append("")
        if budget_statuses:
            lines.append("Budget status:")
            for b in budget_statuses:
                lines.append(
                    f"  • {b['name']} ({b['period']}): "
                    f"{b['spent']:,.0f} / {b['amount']:,.0f} UGX ({b['percentage']}%)"
                )
            lines.append("")
        lines.append(f"View your dashboard: {getattr(settings, 'SITE_URL', '')}/expenses/")
        text_body = "\n".join(lines)

    send_mail(
        subject=subject,
        message=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        html_message=html_body,
        fail_silently=True,
    )
    logger.info("Weekly digest sent to %s", user.email)


# ===========================================================================
# 4. Budget alert email (called from signals.py)
# ===========================================================================

@shared_task
def send_budget_alert_email(budget_id: int, percentage: float = None, spending: float = None) -> dict:
    """
    Send a single budget-threshold alert email.

    Called from signals.py (passing percentage + spending) OR from
    check_budget_alerts() / views.py (passing only budget_id — the task
    fetches live values itself).

    A cache key prevents the same alert firing more than once per hour
    per budget, so it's safe to call this from both signals and periodic tasks.
    """
    from django.core.cache import cache
    from .models import Budget

    # Rate-limit: one alert per budget per hour
    cache_key = f"budget_alert_sent_{budget_id}"
    if cache.get(cache_key):
        logger.debug("Budget alert already sent recently for budget %s — skipping", budget_id)
        return {"sent": False, "reason": "rate-limited"}

    try:
        budget = Budget.objects.select_related("user").get(pk=budget_id)
    except Budget.DoesNotExist:
        return {"sent": False, "reason": "budget not found"}

    user = budget.user
    if not user or not user.email:
        return {"sent": False, "reason": "no email address"}

    # Use live values if not provided by caller
    spent      = Decimal(str(spending)) if spending is not None else budget.get_current_spending()
    pct        = float(percentage) if percentage is not None else float(budget.get_percentage_used())
    remaining  = float(budget.get_remaining())

    subject = (
        f"🚨 Budget Exceeded: {budget.name}"
        if pct >= 100
        else f"⚠️ Budget Alert: {budget.name} at {pct:.1f}%"
    )

    context = {
        "user":          user,
        "budget":        budget,
        "budget_name":   budget.name,
        "budget_amount": budget.amount,
        "percentage":    pct,
        "spending":      float(spent),
        "spent":         float(spent),
        "remaining":     remaining,
        "period":        budget.get_period_display(),
        "site_url":      getattr(settings, "SITE_URL", ""),
    }

    try:
        html_body = render_to_string("expenses/emails/budget_alert.html", context)
    except Exception:
        html_body = None

    # Plain-text fallback (used when no .txt template exists yet)
    try:
        text_body = render_to_string("expenses/emails/budget_alert.txt", context)
    except Exception:
        text_body = (
            f"Hi {user.get_full_name() or user.username},\n\n"
            f"Your budget '{budget.name}' is at {pct:.1f}% "
            f"({float(spent):,.0f} of {float(budget.amount):,.0f} UGX).\n"
            f"Remaining: {remaining:,.0f} UGX\n\n"
            f"View your budgets: {getattr(settings, 'SITE_URL', '')}/expenses/budgets/\n"
        )

    send_mail(
        subject=subject,
        message=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        html_message=html_body,
        fail_silently=True,
    )

    # Set rate-limit flag — expires after 1 hour
    cache.set(cache_key, True, timeout=3600)
    logger.info("Budget alert sent for budget %s (%.1f%%) → %s", budget_id, pct, user.email)
    return {"sent": True, "budget_id": budget_id, "percentage": pct}


# ===========================================================================
# 5. Expense approval notification email (called from signals.py)
# ===========================================================================

@shared_task
def send_expense_notification_email(
    expense_id: int,
    event: str,
    actor_id: int | None = None,
    comment: str = "",
) -> dict:
    """
    Send an email to the expense owner about a status change.

    *event* is one of: 'submitted', 'approved', 'rejected', 'resubmit'

    Called from views.py expense_approve / expense_reject, or from
    signals.py when ExpenseApproval records are created.
    """
    from .models import Expense

    try:
        expense = Expense.objects.select_related("user").get(pk=expense_id)
    except Expense.DoesNotExist:
        return {"sent": False, "reason": "expense not found"}

    owner = expense.user
    if not owner or not owner.email:
        return {"sent": False, "reason": "no email"}

    actor = None
    if actor_id:
        try:
            actor = User.objects.get(pk=actor_id)
        except User.DoesNotExist:
            pass

    event_labels = {
        "submitted":   "📤 Expense Submitted for Approval",
        "approved":    "✅ Your Expense Has Been Approved",
        "rejected":    "❌ Your Expense Was Rejected",
        "resubmit":    "🔄 Your Expense Needs Changes",
        "under_review": "🔍 Your Expense Is Under Review",
    }
    subject = event_labels.get(event, "🔔 Expense Status Update")

    context = {
        "owner":    owner,
        "user":     owner,
        "expense":  expense,
        "event":    event,
        "actor":    actor,
        "comment":  comment,
        "site_url": getattr(settings, "SITE_URL", ""),
    }

    try:
        html_body = render_to_string("expenses/emails/expense_notification.html", context)
    except Exception:
        html_body = None

    try:
        text_body = render_to_string("expenses/emails/expense_notification.txt", context)
    except Exception:
        actor_name = actor.get_full_name() if actor else "Someone"
        text_body = (
            f"Hi {owner.get_full_name() or owner.username},\n\n"
            f"{actor_name} has {event} your expense:\n\n"
            f"  Description: {expense.description}\n"
            f"  Amount:      {expense.amount:,.2f} UGX\n"
            f"  Date:        {expense.date}\n"
            + (f"\nNote: {comment}\n" if comment else "")
            + f"\nView it here: {getattr(settings, 'SITE_URL', '')}/expenses/{expense.pk}/\n"
        )

    send_mail(
        subject=subject,
        message=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[owner.email],
        html_message=html_body,
        fail_silently=True,
    )

    logger.info(
        "Expense notification sent: expense=%s event=%s → %s", expense_id, event, owner.email
    )
    return {"sent": True, "event": event, "expense_id": expense_id}


# ===========================================================================
# Periodic budget checker  (NEW — was missing from original)
# ===========================================================================

@shared_task
def check_budget_alerts() -> dict:
    """
    Run hourly via Celery Beat.

    Scans every active budget and fires send_budget_alert_email for any that
    are at or over their alert threshold. The rate-limiting inside
    send_budget_alert_email (1 alert per budget per hour via cache) means it
    is safe to call this every hour — users won't get duplicate emails.

    Schedule in CELERY_BEAT_SCHEDULE:
        'check-budget-alerts': {
            'task': 'expenses.tasks.check_budget_alerts',
            'schedule': crontab(minute=0),   # top of every hour
        }
    """
    from .models import Budget

    budgets   = Budget.objects.filter(is_active=True).select_related("user")
    triggered = 0

    for budget in budgets:
        try:
            if budget.is_over_threshold():
                pct   = float(budget.get_percentage_used())
                spent = float(budget.get_current_spending())
                send_budget_alert_email.delay(budget.pk, pct, spent)
                triggered += 1
        except Exception as exc:
            logger.exception("check_budget_alerts: error on budget %s: %s", budget.pk, exc)

    logger.info(
        "check_budget_alerts: checked %d budgets, triggered %d alerts",
        budgets.count(), triggered,
    )
    return {"checked": budgets.count(), "triggered": triggered}


# ===========================================================================
# 6. Stale receipt cleanup
# ===========================================================================

@shared_task
def cleanup_stale_receipts(older_than_days: int = 90) -> dict:
    """
    Run periodically (e.g. monthly via Celery Beat).

    Finds Expense records whose receipt file no longer exists on disk (i.e. the
    file was manually deleted or the upload failed mid-way) and clears the
    database field.

    Also optionally removes receipt files for expenses deleted more than
    *older_than_days* days ago if the file is still on disk (shouldn't normally
    happen but guards against edge-cases in storage back-ends).
    """
    from .models import Expense

    cleared = 0
    missing = 0

    expenses_with_receipt = Expense.objects.exclude(receipt="").exclude(receipt=None)

    for expense in expenses_with_receipt:
        try:
            path = expense.receipt.path
        except (ValueError, NotImplementedError):
            # Remote storages (S3, GCS) don't expose .path — skip gracefully
            continue

        if not os.path.exists(path):
            logger.info(
                "cleanup_stale_receipts: receipt file missing for expense %s (%s) — clearing field",
                expense.pk, path,
            )
            expense.receipt = None
            expense.save(update_fields=["receipt"])
            missing += 1

    # Remove orphaned files older than the cutoff that have no matching Expense row
    cutoff = timezone.now() - timedelta(days=older_than_days)
    receipts_media_root = os.path.join(
        settings.MEDIA_ROOT, "receipts"
    )

    if os.path.isdir(receipts_media_root):
        for root, dirs, files in os.walk(receipts_media_root):
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    mtime = timezone.datetime.fromtimestamp(
                        os.path.getmtime(fpath), tz=timezone.get_current_timezone()
                    )
                    if mtime < cutoff:
                        # Check if any Expense still references this file
                        rel_path = os.path.relpath(fpath, settings.MEDIA_ROOT)
                        if not Expense.objects.filter(receipt=rel_path).exists():
                            os.remove(fpath)
                            cleared += 1
                            logger.info("cleanup_stale_receipts: removed orphan %s", fpath)
                except Exception as exc:
                    logger.warning("cleanup_stale_receipts: could not process %s: %s", fpath, exc)

    logger.info(
        "cleanup_stale_receipts: cleared %d missing-file records, removed %d orphan files",
        missing, cleared,
    )
    return {"missing_cleared": missing, "orphans_removed": cleared}