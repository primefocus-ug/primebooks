# company/services/pause_service.py

import logging
from django.utils import timezone
from django.db import transaction
from django_tenants.utils import schema_context

logger = logging.getLogger(__name__)

# ── Permission codename ───────────────────────────────────────────────────────
EFRIS_PAUSE_PERMISSION = 'company.can_manage_efris_pause'

# ── Exemption reason stamped on records when a pause window closes ────────────
PAUSE_EXEMPTION_REASON_TEMPLATE = (
    'Created during EFRIS pause window '
    '({paused_at} – {resumed_at}). Exempt from fiscalization.'
)


# =============================================================================
# PERMISSION HELPER
# =============================================================================

def user_can_manage_efris_pause(user, schema_name: str = None) -> bool:
    """
    Return True if `user` is allowed to activate / deactivate pause mode.

    Allowed when ANY of these conditions are met:
      • user.is_saas_admin
      • user.company_admin
      • user has Django permission 'company.can_manage_efris_pause'
        (granted via their Role's Group permissions — lives in the tenant schema)

    Args:
        user:        CustomUser instance.
        schema_name: The tenant schema name to use when checking Django permissions.
                     Required when accounts is a tenant app (not in SHARED_APPS).
                     If omitted, permission check is skipped and only the boolean
                     attribute shortcuts are evaluated.
    """
    if not user or not user.is_authenticated:
        return False

    if getattr(user, 'is_saas_admin', False):
        return True

    if getattr(user, 'company_admin', False):
        return True

    # has_perm() hits the DB via django's permission backend which reads
    # auth_permission / accounts tables — all in the tenant schema.
    if schema_name:
        with schema_context(schema_name):
            return user.has_perm(EFRIS_PAUSE_PERMISSION)

    # Fallback: if no schema_name provided, attempt the check without switching
    # (works only if the connection is already set to the correct tenant schema).
    return user.has_perm(EFRIS_PAUSE_PERMISSION)


# =============================================================================
# MAIN TOGGLE FUNCTION
# =============================================================================

def set_efris_fiscalization_mode(company, new_mode: str, changed_by) -> dict:
    """
    Change the company's EFRIS fiscalization mode with all required side effects.

    Args:
        company:     Company instance (the tenant). Must have a .schema_name attribute.
        new_mode:    One of 'enabled', 'disabled', 'paused'.
        changed_by:  CustomUser instance performing the change.

    Returns:
        dict with keys:
            success  (bool)
            message  (str)
            mode     (str)  — new mode if successful
            details  (dict) — extra info (e.g. exempt_count, queued_count)

    Raises:
        Nothing — errors are returned as {'success': False, 'message': ...}
    """
    VALID_MODES = ('enabled', 'disabled', 'paused')
    schema = company.schema_name

    # ── Validate mode ─────────────────────────────────────────────────────────
    if new_mode not in VALID_MODES:
        return {
            'success': False,
            'message': f"Invalid mode '{new_mode}'. Must be one of: {', '.join(VALID_MODES)}",
        }

    # ── Permission check for 'paused' — runs inside the tenant schema ─────────
    if new_mode == 'paused' and not user_can_manage_efris_pause(changed_by, schema_name=schema):
        return {
            'success': False,
            'message': (
                'You do not have permission to activate pause mode. '
                'Contact a company admin.'
            ),
        }

    old_mode = company.efris_fiscalization_mode
    now = timezone.now()

    # Nothing to do if same mode
    if old_mode == new_mode:
        return {
            'success': True,
            'message': f'EFRIS is already in {new_mode} mode.',
            'mode': new_mode,
            'details': {},
        }

    details = {}

    # All DB work against tenant tables runs inside schema_context so that
    # Django's connection is pointed at the correct PostgreSQL search_path.
    with schema_context(schema):
        with transaction.atomic():

            # ══════════════════════════════════════════════════════════════════
            # TRANSITION: anything → 'paused'
            # ══════════════════════════════════════════════════════════════════
            if new_mode == 'paused':
                _activate_pause(company, changed_by, now)
                details['pause_started_at'] = now.isoformat()
                message = (
                    'EFRIS has been paused. Invoices and sales recorded from now '
                    'will be permanently exempt from fiscalization until pause is lifted.'
                )

            # ══════════════════════════════════════════════════════════════════
            # TRANSITION: 'paused' → 'disabled'
            # Mark all invoices/sales in the pause window as permanently exempt.
            # ══════════════════════════════════════════════════════════════════
            elif old_mode == 'paused' and new_mode == 'disabled':
                exempt_count = _close_pause_window_as_exempt(company, now)
                details['exempt_count'] = exempt_count
                message = (
                    f'Pause mode ended. {exempt_count} record(s) created during the '
                    'pause window have been permanently exempted from fiscalization. '
                    'EFRIS is now disabled (normal off).'
                )

            # ══════════════════════════════════════════════════════════════════
            # TRANSITION: 'paused' → 'enabled'
            # Close the pause window (exempt those records) then kick off catch-up
            # for all OTHER unfiscalized, non-exempt records.
            # ══════════════════════════════════════════════════════════════════
            elif old_mode == 'paused' and new_mode == 'enabled':
                exempt_count = _close_pause_window_as_exempt(company, now)
                queued_count = _queue_catchup_fiscalization(company)
                details['exempt_count'] = exempt_count
                details['queued_for_fiscalization'] = queued_count
                message = (
                    f'Pause mode ended. {exempt_count} record(s) from the pause window '
                    f'are permanently exempt. {queued_count} other unfiscalized record(s) '
                    'have been queued for fiscalization.'
                )

            # ══════════════════════════════════════════════════════════════════
            # TRANSITION: 'disabled' → 'enabled'
            # Normal re-enable: catch up all unfiscalized, non-exempt records.
            # ══════════════════════════════════════════════════════════════════
            elif old_mode == 'disabled' and new_mode == 'enabled':
                queued_count = _queue_catchup_fiscalization(company)
                details['queued_for_fiscalization'] = queued_count
                message = (
                    f'EFRIS enabled. {queued_count} unfiscalized record(s) have been '
                    'queued for fiscalization.'
                )

            # ══════════════════════════════════════════════════════════════════
            # TRANSITION: 'enabled' → 'disabled'
            # Simply turn off — existing unfiscalized records stay as-is and will
            # be caught up when re-enabled later.
            # ══════════════════════════════════════════════════════════════════
            elif old_mode == 'enabled' and new_mode == 'disabled':
                message = 'EFRIS disabled. Unfiscalized records will be caught up on re-enable.'

            else:
                # Catch-all for any other combination (e.g. disabled → disabled handled above)
                message = f'EFRIS mode changed from {old_mode} to {new_mode}.'

            # ── Persist the new mode ──────────────────────────────────────────
            company.efris_fiscalization_mode = new_mode
            company.efris_enabled = (new_mode == 'enabled')

            # Clear pause tracking fields if we're leaving paused mode
            if old_mode == 'paused' and new_mode != 'paused':
                company.efris_paused_at = None
                company.efris_paused_by_id = None
                company.efris_paused_by_name = None

            company.save(update_fields=[
                'efris_fiscalization_mode',
                'efris_enabled',
                'efris_paused_at',
                'efris_paused_by_id',
                'efris_paused_by_name',
            ])

    # ── Audit log (also tenant-scoped — handled inside _log_mode_change) ──────
    _log_mode_change(company, old_mode, new_mode, changed_by, details)

    logger.info(
        'EFRIS mode changed: company=%s old=%s new=%s by=%s details=%s',
        schema, old_mode, new_mode, changed_by.email, details,
    )

    return {
        'success': True,
        'message': message,
        'mode': new_mode,
        'details': details,
    }


# =============================================================================
# INTERNAL HELPERS
# (All called from within set_efris_fiscalization_mode which already wraps
#  everything in schema_context, so these helpers do NOT need their own wrapper.)
# =============================================================================

def _activate_pause(company, paused_by, now):
    """
    Record pause start time and who triggered it.
    Called inside an atomic block that is already inside schema_context.
    """
    company.efris_paused_at = now
    company.efris_paused_by_id = str(paused_by.pk)
    company.efris_paused_by_name = paused_by.get_full_name() or paused_by.email
    # Note: efris_enabled stays at its current value —
    # pause is a sub-state of "off", so we set it False too.
    company.efris_enabled = False
    # We do NOT call .save() here; the caller does one atomic save.


def _close_pause_window_as_exempt(company, now) -> int:
    """
    Stamp all invoices and sales that were created between `company.efris_paused_at`
    and `now` (and are not yet fiscalized) as permanently exempt.

    Returns the total number of records stamped.
    Called inside schema_context + atomic block.
    """
    paused_at = company.efris_paused_at
    if not paused_at:
        logger.warning(
            'close_pause_window called but efris_paused_at is None for company=%s',
            company.schema_name,
        )
        return 0

    exemption_reason = PAUSE_EXEMPTION_REASON_TEMPLATE.format(
        paused_at=paused_at.strftime('%Y-%m-%d %H:%M'),
        resumed_at=now.strftime('%Y-%m-%d %H:%M'),
    )

    total_exempted = 0

    # ── Exempt Invoices ───────────────────────────────────────────────────────
    try:
        from invoices.models import Invoice
        invoice_qs = Invoice.objects.filter(
            company=company,
            created_at__gte=paused_at,
            created_at__lte=now,
            efris_exempt=False,
            # Adjust the field name below to match your Invoice model.
            efris_status__in=['pending', 'failed', ''],
        )
        invoice_count = invoice_qs.update(
            efris_exempt=True,
            efris_exemption_reason=exemption_reason,
        )
        total_exempted += invoice_count
        logger.info('Exempted %d invoices in pause window for company=%s', invoice_count, company.schema_name)
    except Exception as e:
        logger.error('Error exempting invoices for company=%s: %s', company.schema_name, e)

    # ── Exempt Sales ──────────────────────────────────────────────────────────
    try:
        from sales.models import Sale
        sale_qs = Sale.objects.filter(
            company=company,
            created_at__gte=paused_at,
            created_at__lte=now,
            efris_exempt=False,
            # Adjust field name/values to match your Sale model's EFRIS status field.
            efris_status__in=['pending', 'failed', ''],
        )
        sale_count = sale_qs.update(
            efris_exempt=True,
            efris_exemption_reason=exemption_reason,
        )
        total_exempted += sale_count
        logger.info('Exempted %d sales in pause window for company=%s', sale_count, company.schema_name)
    except Exception as e:
        logger.error('Error exempting sales for company=%s: %s', company.schema_name, e)

    return total_exempted


def _queue_catchup_fiscalization(company) -> int:
    """
    Find all invoices and sales that:
      • belong to this company
      • are NOT yet fiscalized
      • are NOT exempt (efris_exempt=False)

    Then queue them for fiscalization via your existing Celery task.

    Returns the count of records queued.
    Called inside schema_context + atomic block.
    """
    total_queued = 0

    # ── Queue Invoices ────────────────────────────────────────────────────────
    try:
        from invoices.models import Invoice
        invoice_ids = list(
            Invoice.objects.filter(
                company=company,
                efris_exempt=False,
                # Adjust to your model's unfiscalized status values:
                efris_status__in=['pending', 'failed', ''],
            ).values_list('id', flat=True)
        )

        if invoice_ids:
            _dispatch_fiscalization_task('invoice', invoice_ids, company)
            total_queued += len(invoice_ids)
            logger.info(
                'Queued %d invoices for catch-up fiscalization for company=%s',
                len(invoice_ids), company.schema_name,
            )
    except Exception as e:
        logger.error('Error queuing invoices for company=%s: %s', company.schema_name, e)

    # ── Queue Sales ───────────────────────────────────────────────────────────
    try:
        from sales.models import Sale
        sale_ids = list(
            Sale.objects.filter(
                company=company,
                efris_exempt=False,
                efris_status__in=['pending', 'failed', ''],
            ).values_list('id', flat=True)
        )

        if sale_ids:
            _dispatch_fiscalization_task('sale', sale_ids, company)
            total_queued += len(sale_ids)
            logger.info(
                'Queued %d sales for catch-up fiscalization for company=%s',
                len(sale_ids), company.schema_name,
            )
    except Exception as e:
        logger.error('Error queuing sales for company=%s: %s', company.schema_name, e)

    return total_queued


def _dispatch_fiscalization_task(record_type: str, ids: list, company):
    """
    Send a batch of invoice/sale IDs to your existing Celery fiscalization task.

    ── HOW TO WIRE THIS UP ──────────────────────────────────────────────────
    Replace the import path and task name below with your actual Celery task.

    Example (if you already have a task like this):

        from efris.tasks import fiscalize_invoices_batch
        fiscalize_invoices_batch.delay(
            company_schema=company.schema_name,
            record_ids=ids,
        )

    If you use django_tenants, make sure your task switches schema:

        from django_tenants.utils import schema_context
        with schema_context(company.schema_name):
            Invoice.objects.filter(id__in=ids)...
    ────────────────────────────────────────────────────────────────────────
    """
    try:
        # ── REPLACE THIS BLOCK with your actual Celery task import ────────────
        if record_type == 'invoice':
            from efris.tasks import fiscalize_invoices_batch   # ← adjust import
            fiscalize_invoices_batch.delay(
                company_schema=company.schema_name,
                invoice_ids=ids,
            )
        elif record_type == 'sale':
            from efris.tasks import fiscalize_sales_batch      # ← adjust import
            fiscalize_sales_batch.delay(
                company_schema=company.schema_name,
                sale_ids=ids,
            )
        # ─────────────────────────────────────────────────────────────────────
    except ImportError:
        # Task module not found — log a clear error so you know to wire it up
        logger.error(
            'Could not import fiscalization task for %s. '
            'Wire up _dispatch_fiscalization_task() in pause_service.py',
            record_type,
        )
    except Exception as e:
        logger.error('Error dispatching fiscalization task for %s: %s', record_type, e)


def _log_mode_change(company, old_mode, new_mode, changed_by, details):
    """
    Write an AuditLog entry for the mode change.

    AuditLog lives in the tenant schema (accounts is a TENANT_APP), so we
    explicitly wrap the write in schema_context.

    Silently skips if AuditLog is unavailable so the main flow never breaks.
    """
    try:
        from accounts.models import AuditLog
        from django.contrib.contenttypes.models import ContentType
        from company.models import Company

        with schema_context(company.schema_name):
            AuditLog.objects.create(
                user=changed_by,
                action='EFRIS_MODE_CHANGE',
                content_type=ContentType.objects.get_for_model(Company),
                object_id=str(company.pk),
                object_repr=str(company),
                changes={
                    'efris_fiscalization_mode': {'old': old_mode, 'new': new_mode},
                    **details,
                },
                ip_address=None,   # Pass request.META.get('REMOTE_ADDR') from view if needed
            )
    except Exception as e:
        logger.warning('Could not write AuditLog for EFRIS mode change: %s', e)


# =============================================================================
# CONVENIENCE CHECKS (for use in invoice/sale creation logic)
# =============================================================================

def is_efris_paused(company) -> bool:
    """Quick check — call this when creating an invoice/sale to decide whether
    to pre-stamp it as exempt."""
    return getattr(company, 'efris_fiscalization_mode', 'disabled') == 'paused'


def stamp_record_if_paused(company, record):
    """
    Call this right after saving a new Invoice or Sale.
    If the company is currently paused, marks the record as exempt immediately.

    The save() on the record touches the tenant schema — we wrap it in
    schema_context so it works regardless of the current connection state.

    Args:
        company:  Company instance
        record:   Invoice or Sale instance (must have efris_exempt + efris_exemption_reason fields)

    Example usage in invoices/views.py or sales/views.py:

        from company.services.pause_service import stamp_record_if_paused
        invoice = form.save()
        stamp_record_if_paused(request.tenant, invoice)
    """
    if is_efris_paused(company):
        record.efris_exempt = True
        record.efris_exemption_reason = (
            f'Created while EFRIS was paused '
            f'(since {company.efris_paused_at.strftime("%Y-%m-%d %H:%M") if company.efris_paused_at else "unknown"}).'
        )
        with schema_context(company.schema_name):
            record.save(update_fields=['efris_exempt', 'efris_exemption_reason'])