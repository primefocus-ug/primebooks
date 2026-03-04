"""
signals.py — Expense & Budget signals

Improvements over original:
  1. Real notifications pushed via Django Channels (WebSocket) and Celery email tasks
  2. Debounce: a Redis/cache flag prevents repeated alerts within a cool-down window
  3. Budget *recovery* signal — fires when spending drops back below the threshold
     after an Expense is deleted (post_delete)
  4. post_save on ExpenseApproval sends WebSocket events to the expense owner
     and to the approver dashboard
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Budget, Expense, ExpenseApproval

logger = logging.getLogger(__name__)
User = get_user_model()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# How long (seconds) before the same budget alert can fire again for the same user.
ALERT_DEBOUNCE_SECONDS = 3600  # 1 hour


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _debounce_key(budget: Budget, event: str) -> str:
    return f"budget_alert:{budget.pk}:{event}"


def _is_debounced(budget: Budget, event: str) -> bool:
    return bool(cache.get(_debounce_key(budget, event)))


def _set_debounce(budget: Budget, event: str) -> None:
    cache.set(_debounce_key(budget, event), True, timeout=ALERT_DEBOUNCE_SECONDS)


def _clear_debounce(budget: Budget, event: str) -> None:
    cache.delete(_debounce_key(budget, event))


def _push_ws_notification(user_id: int, payload: dict) -> None:
    """Push a notification to the user's personal WebSocket group (best-effort)."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return

        group_name = f"expense_user_{user_id}"
        async_to_sync(channel_layer.group_send)(group_name, payload)
    except Exception as exc:
        logger.warning("WebSocket push failed for user %s: %s", user_id, exc)


def _push_ws_approval_dashboard(payload: dict) -> None:
    """Push an event to the shared approval dashboard group (best-effort)."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return

        async_to_sync(channel_layer.group_send)("expense_approval_dashboard", payload)
    except Exception as exc:
        logger.warning("WebSocket approval-dashboard push failed: %s", exc)


def _enqueue_budget_alert_email(budget: Budget, percentage: float, spending) -> None:
    """Queue a Celery task to send the budget-alert email (fire-and-forget)."""
    try:
        from .tasks import send_budget_alert_email
        send_budget_alert_email.delay(budget.pk, float(percentage), float(spending))
    except Exception as exc:
        logger.warning("Could not enqueue budget alert email for budget %s: %s", budget.pk, exc)


def _enqueue_expense_notification_email(
    expense: Expense, event: str, actor_id: int | None = None, comment: str = ""
) -> None:
    """Queue a Celery task to send an expense-status notification email."""
    try:
        from .tasks import send_expense_notification_email
        send_expense_notification_email.delay(expense.pk, event, actor_id, comment)
    except Exception as exc:
        logger.warning(
            "Could not enqueue expense notification email for expense %s: %s", expense.pk, exc
        )


# ---------------------------------------------------------------------------
# Budget alert helper — shared by post_save and post_delete handlers
# ---------------------------------------------------------------------------

def _check_budgets_for_user(user, source_expense: Expense | None = None) -> None:
    """
    Scan all active budgets for *user* and fire threshold-crossed / recovery
    notifications as appropriate.

    Pass source_expense when called from a post_save so tag-matching can be
    done before doing the heavier per-budget scan.
    """
    budgets = Budget.objects.filter(user=user, is_active=True).prefetch_related("tags")

    for budget in budgets:
        # If this budget is tag-scoped, skip when the triggering expense has
        # no overlapping tags (fast path — avoids the DB aggregation entirely).
        if source_expense is not None and budget.tags.exists():
            expense_tags = set(source_expense.tags.names())
            budget_tags = set(budget.tags.names())
            if not expense_tags.intersection(budget_tags):
                continue

        percentage = float(budget.get_percentage_used())
        spending = budget.get_current_spending()
        now_ts = timezone.now().isoformat()

        over = budget.is_over_threshold()

        if over:
            # --- THRESHOLD CROSSED ---
            if _is_debounced(budget, "alert"):
                # Already notified recently; skip without resetting recovery flag
                continue

            _set_debounce(budget, "alert")
            # Clear any lingering recovery debounce so it can fire again later
            _clear_debounce(budget, "recovery")

            logger.info(
                "Budget alert: '%s' is at %.1f%% ($%s of $%s)",
                budget.name, percentage, spending, budget.amount,
            )

            # WebSocket push to expense owner
            _push_ws_notification(user.pk, {
                "type": "expense_notification",
                "notification_type": "budget_alert",
                "title": f"⚠️ Budget Alert: {budget.name}",
                "message": (
                    f"You've used {percentage:.1f}% of your {budget.name} budget "
                    f"(${spending} of ${budget.amount})."
                ),
                "timestamp": now_ts,
            })

            # Email via Celery
            _enqueue_budget_alert_email(budget, percentage, spending)

        else:
            # --- POSSIBLE RECOVERY ---
            # Only fire if the alert had previously been set (i.e. we were over)
            if cache.get(_debounce_key(budget, "alert")) or not _is_debounced(budget, "recovery"):
                # We were over threshold and now we're back under it
                if not _is_debounced(budget, "recovery"):
                    _clear_debounce(budget, "alert")
                    _set_debounce(budget, "recovery")

                    logger.info(
                        "Budget recovery: '%s' is back at %.1f%%",
                        budget.name, percentage,
                    )

                    _push_ws_notification(user.pk, {
                        "type": "expense_notification",
                        "notification_type": "budget_recovery",
                        "title": f"✅ Budget Recovery: {budget.name}",
                        "message": (
                            f"Your {budget.name} budget is back under the threshold "
                            f"({percentage:.1f}% used)."
                        ),
                        "timestamp": now_ts,
                    })


# ---------------------------------------------------------------------------
# Expense signals
# ---------------------------------------------------------------------------

@receiver(post_save, sender=Expense)
def check_budget_alerts_on_save(sender, instance: Expense, created: bool, **kwargs):
    """Check budgets whenever a new expense is created."""
    if not created:
        return
    if instance.user is None:
        return
    _check_budgets_for_user(instance.user, source_expense=instance)


@receiver(post_delete, sender=Expense)
def check_budget_recovery_on_delete(sender, instance: Expense, **kwargs):
    """
    Re-check budgets after an expense is deleted so that if spending has
    dropped back below the threshold we send a recovery notification.
    """
    if instance.user is None:
        return
    _check_budgets_for_user(instance.user, source_expense=None)


# ---------------------------------------------------------------------------
# ExpenseApproval signals — real-time events for the approval workflow
# ---------------------------------------------------------------------------

@receiver(post_save, sender=ExpenseApproval)
def notify_on_approval_action(sender, instance: ExpenseApproval, created: bool, **kwargs):
    """
    Push WebSocket notifications when an approval action is recorded:
      • The expense *owner* gets a personal notification.
      • Approvers on the dashboard get an aggregated count update.
    """
    if not created:
        return

    expense = instance.expense
    now_ts = instance.created_at.isoformat()

    action_labels = {
        "submitted": ("📤 Expense Submitted", "Your expense has been submitted for approval."),
        "under_review": ("🔍 Under Review", "Your expense is being reviewed."),
        "approved": ("✅ Expense Approved", "Your expense has been approved."),
        "rejected": ("❌ Expense Rejected", "Your expense was rejected."),
        "resubmit": ("🔄 Resubmission Required", "Your expense needs changes before approval."),
        "cancelled": ("🚫 Expense Cancelled", "The expense was cancelled."),
        "comment": ("💬 New Comment", "A comment was added to your expense."),
    }

    title, message = action_labels.get(
        instance.action, ("🔔 Expense Update", "Your expense status has changed.")
    )
    if instance.comment:
        message = f"{message} Note: {instance.comment}"

    # --- Notify the expense owner ---
    if expense.user_id:
        _push_ws_notification(expense.user_id, {
            "type": "expense_notification",
            "notification_type": instance.action,
            "title": title,
            "message": message,
            "expense_id": expense.pk,
            "timestamp": now_ts,
        })

        # Email for terminal states
        if instance.action in ("approved", "rejected", "resubmit"):
            _enqueue_expense_notification_email(
                expense,
                instance.action,
                actor_id=instance.actor_id,
                comment=instance.comment,
            )

    # --- Notify the approval dashboard ---
    pending_count = Expense.objects.filter(
        status__in=("submitted", "under_review")
    ).count()

    _push_ws_approval_dashboard({
        "type": "approval_update",
        "pending_count": pending_count,
        "recent_activity": [
            {
                "expense_id": expense.pk,
                "expense_number": str(expense.sync_id)[:8].upper(),
                "action": instance.action,
                "actor": str(instance.actor) if instance.actor else "System",
                "timestamp": now_ts,
            }
        ],
        "timestamp": now_ts,
    })