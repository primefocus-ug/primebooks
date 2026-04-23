"""
Celery Tasks for Asynchronous Report Generation

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REQUIRED: Add the following to your settings.py to enable
          scheduled tasks via Celery Beat:

    from celery.schedules import crontab

    CELERY_BEAT_SCHEDULE = {
        # Fire per-schedule report generation every 5 minutes
        'process-scheduled-reports': {
            'task': 'reports.tasks.process_scheduled_reports',
            'schedule': crontab(minute='*/5'),
        },
        # Send a daily summary email to all tenant admins at 7 AM
        'dispatch-daily-reports': {
            'task': 'reports.tasks.dispatch_daily_reports',
            'schedule': crontab(hour=7, minute=0),
        },
        # Send a weekly summary email every Monday at 8 AM
        'dispatch-weekly-reports': {
            'task': 'reports.tasks.dispatch_weekly_reports',
            'schedule': crontab(day_of_week=1, hour=8, minute=0),
        },
        # Clean up expired report files daily at 2 AM
        'cleanup-expired-reports': {
            'task': 'reports.tasks.cleanup_expired_reports',
            'schedule': crontab(hour=2, minute=0),
        },
        # Refresh real-time dashboard every 5 minutes
        'update-real-time-dashboard': {
            'task': 'reports.tasks.update_real_time_dashboard',
            'schedule': crontab(minute='*/5'),
        },
    }

Then run the beat worker alongside your Celery worker:
    celery -A <your_project> worker -l info
    celery -A <your_project> beat   -l info
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import json
import logging
import os
import shutil
import time
from datetime import timedelta

from asgiref.sync import async_to_sync
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMessage, send_mail
from django.db import connection, transaction
from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone
from django_tenants.utils import get_tenant_model, schema_context, tenant_context

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# TENANT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_tenant_from_schema(schema_name):
    """Return the tenant object for the given schema, or None."""
    from company.models import Company
    try:
        return Company.objects.get(schema_name=schema_name)
    except Company.DoesNotExist:
        logger.error(f"Tenant not found for schema: {schema_name}")
        return None


def get_all_tenants():
    """Return all non-public active tenant objects."""
    from company.models import Company
    return Company.objects.filter(is_active=True).exclude(schema_name='public')


@shared_task(bind=True, max_retries=3)
def generate_report_async(self, report_id, user_id, schema_name, **kwargs):
    tenant = get_tenant_from_schema(schema_name)
    if not tenant:
        return

    with tenant_context(tenant):
        from django.db import transaction
        from django.utils import timezone
        from .models import SavedReport, GeneratedReport
        from accounts.models import CustomUser
        from .services.pdf_export import PDFExportService
        from .services.excel_export import ExcelExportService
        from .consumers import send_report_progress, send_report_complete, send_report_failed

        generated_report = None

        try:
            report = SavedReport.objects.get(id=report_id)
            user = CustomUser.objects.get(id=user_id)

            # ── ATOMIC LOCK ──────────────────────────────────────────────────
            with transaction.atomic():
                active_qs = (
                    GeneratedReport.objects
                    .select_for_update()
                    .filter(
                        report=report,
                        generated_by=user,
                        status__in=['PENDING', 'PROCESSING']
                    )
                    .order_by('-generated_at')
                )

                # Cancel ALL old active ones
                active_qs.update(
                    status='CANCELLED',
                    error_message='Superseded by new run',
                    completed_at=timezone.now()
                )

                # Always create a fresh row
                generated_report = GeneratedReport.objects.create(
                    report=report,
                    generated_by=user,
                    parameters=kwargs,
                    file_format=kwargs.get('format', 'PDF'),
                    status='PROCESSING',
                    progress=10,
                    task_id=self.request.id
                )

            generated_report.save(update_fields=['status', 'progress'])

            async_to_sync(send_report_progress)(
                generated_report.id, 10, 'Initializing...', 'processing'
            )

            start_time = time.time()

            # ── NEW: narrative/comparison imports ────────────────────────────
            from .services.comparison_engine import ComparisonEngine
            from .services.narrative_engine import build_narratives, resolve_reader_role
            from .services.currency_formatter import get_formatter

            generated_report.update_progress(30, 'Fetching data...')
            async_to_sync(send_report_progress)(
                generated_report.id, 30, 'Fetching data...', 'processing'
            )

            # ── Currency formatter (reads company.preferred_currency) ────────
            fmt = get_formatter(user=user)

            # ── Reader role from user priority ───────────────────────────────
            reader_role = resolve_reader_role(user)

            # ── Pop comparison params from kwargs so they don't hit generator
            comparison_mode  = kwargs.pop('comparison_mode',  'auto')
            comparison_start = kwargs.pop('comparison_start', None)
            comparison_end   = kwargs.pop('comparison_end',   None)

            # ── Fetch current + prior period via ComparisonEngine ────────────
            engine = ComparisonEngine(user, report)
            result = engine.fetch(
                start_date       = kwargs.get('start_date'),
                end_date         = kwargs.get('end_date'),
                store_id         = kwargs.get('store_id'),
                comparison_mode  = comparison_mode,
                comparison_start = comparison_start,
                comparison_end   = comparison_end,
                **{k: v for k, v in kwargs.items()
                   if k not in ('start_date', 'end_date', 'store_id', 'format',
                                'include_charts', 'include_summary', 'email_report',
                                'email_recipients', 'cc_recipients', 'confidential',
                                'watermark', 'efris_format', 'include_efris')},
            )

            report_data  = result['current']
            prior_data   = result['prior']
            delta        = result['delta']
            period_label = result['current_label']
            prior_label  = result['prior_label']

            generated_report.update_progress(50, 'Building narratives...')
            async_to_sync(send_report_progress)(
                generated_report.id, 50, 'Building narratives...', 'processing'
            )

            # ── Build narrative blocks ───────────────────────────────────────
            narratives = build_narratives(
                report_type  = report.report_type,
                data         = report_data,
                prior        = prior_data,
                delta        = delta,
                fmt          = fmt,
                period_label = period_label,
                prior_label  = prior_label,
                reader_role  = reader_role,
            )

            company_info = {
                'name': user.company.name if user.company else 'Company',
            }

            file_format = kwargs.get('format', 'PDF')

            generated_report.update_progress(70, f'Generating {file_format}...')
            async_to_sync(send_report_progress)(
                generated_report.id, 70, f'Generating {file_format}...', 'processing'
            )

            if file_format == 'PDF':
                buffer = PDFExportService(
                    report_data  = report_data,
                    report_name  = report.name,
                    report_type  = report.report_type,
                    company_info = company_info,
                    narratives   = narratives,
                    fmt          = fmt,
                    prior_data   = prior_data,
                    delta        = delta,
                    period_label = period_label,
                    prior_label  = prior_label,
                    reader_role  = reader_role,
                ).generate_pdf()
                ext = 'pdf'
            elif file_format == 'XLSX':
                buffer = ExcelExportService(report_data, report.name, company_info).generate_excel()
                ext = 'xlsx'
            else:
                raise ValueError('Unsupported format')

            reports_dir = os.path.join(settings.MEDIA_ROOT, 'generated_reports', schema_name)
            os.makedirs(reports_dir, exist_ok=True)

            filename = f"{report.name.replace(' ', '_')}_{timezone.now():%Y%m%d_%H%M%S}.{ext}"
            file_path = os.path.join(reports_dir, filename)

            with open(file_path, 'wb') as f:
                f.write(buffer.getvalue())

            file_size = os.path.getsize(file_path)
            generation_time = time.time() - start_time
            row_count = len(report_data.get('products', []))

            generated_report.mark_as_completed(
                file_path, file_size, row_count, generation_time
            )

            async_to_sync(send_report_progress)(
                generated_report.id, 100, 'Completed', 'completed'
            )

            async_to_sync(send_report_complete)(
                generated_report.id,
                generated_report.id,
                f'/reports/download/{generated_report.id}/',
                file_size,
                row_count
            )

            # Send email if this was triggered by a schedule
            email_report = kwargs.get('email_report', False)
            email_recipients = kwargs.get('email_recipients', '')
            cc_recipients = kwargs.get('cc_recipients', '')

            if email_report and email_recipients:
                send_report_email.delay(
                    generated_report.id,
                    email_recipients,
                    schema_name,
                    cc_recipients=cc_recipients
                )
                logger.info(
                    f"Queued email delivery for report {generated_report.id} "
                    f"to: {email_recipients}"
                )

        except Exception as e:
            if generated_report and generated_report.status != 'COMPLETED':
                generated_report.mark_as_failed(str(e))
                async_to_sync(send_report_failed)(
                    generated_report.id, str(e)
                )

            if 'timeout' in str(e).lower() or 'database' in str(e).lower():
                raise self.retry(exc=e, countdown=60)

            raise


@shared_task(bind=True, max_retries=3)
def send_report_email(self, generated_report_id, recipients, schema_name, cc_recipients=''):
    """Send generated report via email"""
    tenant = get_tenant_from_schema(schema_name)
    if not tenant:
        logger.error(f"send_report_email: tenant not found for schema '{schema_name}'")
        return

    with tenant_context(tenant):
        from .models import GeneratedReport

        try:
            report = GeneratedReport.objects.get(id=generated_report_id)

            if not report.file_path or not os.path.exists(report.file_path):
                logger.error(f"Report file not found: {report.file_path}")
                return

            # Parse TO recipients
            if isinstance(recipients, str):
                recipients = [e.strip() for e in recipients.split(',') if e.strip()]

            # Parse CC recipients
            cc_list = []
            if cc_recipients:
                if isinstance(cc_recipients, str):
                    cc_list = [e.strip() for e in cc_recipients.split(',') if e.strip()]
                elif isinstance(cc_recipients, list):
                    cc_list = cc_recipients

            if not recipients:
                logger.warning(f"No valid recipients for report {generated_report_id}, skipping email.")
                return

            company_name = (
                report.generated_by.company.name
                if report.generated_by and report.generated_by.company
                else 'System'
            )

            subject = f"Scheduled Report: {report.report.name}"
            body = (
                f"Hello,\n\n"
                f'Your scheduled report "{report.report.name}" has been generated successfully.\n\n'
                f"Report Details:\n"
                f"  - Generated At : {report.generated_at.strftime('%B %d, %Y %I:%M %p')}\n"
                f"  - Format       : {report.file_format}\n"
                f"  - File Size    : {report.file_size / 1024:.2f} KB\n"
                f"  - Rows         : {report.row_count:,}\n\n"
                f"Please find the report attached to this email.\n\n"
                f"Best regards,\n{company_name}"
            )

            email = EmailMessage(
                subject=subject,
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=recipients,
                cc=cc_list if cc_list else [],
            )

            email.attach_file(report.file_path)
            email.send()

            logger.info(
                f"Report '{report.report.name}' emailed to {recipients}"
                + (f" (CC: {cc_list})" if cc_list else "")
            )

        except GeneratedReport.DoesNotExist:
            logger.error(f"send_report_email: GeneratedReport {generated_report_id} does not exist.")

        except Exception as e:
            logger.error(f"Error sending report email: {str(e)}", exc_info=True)
            raise self.retry(exc=e, countdown=120)


@shared_task
def process_scheduled_reports():
    """Process due scheduled reports for all tenants"""
    from company.models import Company
    from django.utils import timezone

    now = timezone.now()
    logger.info(f"=== Processing scheduled reports at {now} ===")

    tenants = Company.objects.filter(is_active=True).exclude(schema_name='public')

    for tenant in tenants:
        with tenant_context(tenant):
            from .models import ReportSchedule

            due_schedules = ReportSchedule.objects.filter(
                is_active=True
            ).filter(
                Q(next_scheduled__lte=now) | Q(next_scheduled__isnull=True)
            ).select_related('report', 'report__created_by')

            logger.info(
                f"Tenant {tenant.schema_name}: "
                f"Found {due_schedules.count()} schedules to process"
            )

            for schedule in due_schedules:
                try:
                    if not schedule.next_scheduled:
                        logger.info(f"Schedule {schedule.id} missing next_scheduled, calculating...")
                        schedule.calculate_next_run()
                        schedule.save()

                        if schedule.next_scheduled > now:
                            logger.info(
                                f"Schedule {schedule.id} next run is {schedule.next_scheduled}, "
                                f"skipping for now"
                            )
                            continue

                    logger.info(
                        f"Executing scheduled report: {schedule.report.name} "
                        f"(ID: {schedule.id}, Next: {schedule.next_scheduled})"
                    )

                    user = schedule.report.created_by

                    kwargs = schedule.report.filters or {}
                    kwargs['format'] = schedule.format
                    kwargs['email_report'] = True
                    kwargs['email_recipients'] = schedule.recipients
                    kwargs['cc_recipients'] = schedule.cc_recipients
                    kwargs['include_efris'] = schedule.include_efris

                    if schedule.efris_report_format:
                        kwargs['efris_format'] = schedule.efris_report_format

                    generate_report_async.delay(
                        schedule.report.id,
                        user.id,
                        tenant.schema_name,
                        **kwargs
                    )

                    schedule.last_sent = now
                    schedule.calculate_next_run()
                    schedule.retry_count = 0
                    schedule.save()

                    logger.info(
                        f"Triggered report {schedule.report.name} "
                        f"(Next run: {schedule.next_scheduled})"
                    )

                except Exception as e:
                    logger.error(
                        f"Error processing schedule {schedule.id}: {str(e)}",
                        exc_info=True
                    )

                    schedule.retry_count += 1
                    if schedule.retry_count >= schedule.max_retries:
                        schedule.is_active = False
                        logger.error(
                            f"Deactivating schedule {schedule.id} after "
                            f"{schedule.retry_count} failed attempts"
                        )
                    schedule.save()

    logger.info("=== Finished processing scheduled reports ===")


@shared_task
def cleanup_expired_reports():
    """Clean up expired generated reports for all tenants"""
    from company.models import Company
    from django.utils import timezone

    now = timezone.now()
    total_count = 0

    tenants = Company.objects.filter(is_active=True).exclude(schema_name='public')

    for tenant in tenants:
        with tenant_context(tenant):
            from .models import GeneratedReport

            expired_reports = GeneratedReport.objects.filter(
                expires_at__lt=now,
                status='COMPLETED'
            )

            count = 0
            for report in expired_reports:
                try:
                    if os.path.exists(report.file_path):
                        os.remove(report.file_path)
                        logger.info(f"Deleted expired report file: {report.file_path}")

                    report.delete()
                    count += 1

                except Exception as e:
                    logger.error(f"Error deleting expired report {report.id}: {str(e)}")

            logger.info(f"Cleaned up {count} expired reports for tenant {tenant.schema_name}")
            total_count += count

    logger.info(f"Total cleaned up {total_count} expired reports")
    return total_count


@shared_task
def update_dashboard_cache():
    """Update dashboard statistics cache for all tenants"""
    from company.models import Company
    from django.db.models import Sum, Count, F
    from datetime import timedelta

    today = timezone.now().date()
    week_ago = today - timedelta(days=7)

    tenants = Company.objects.filter(is_active=True).exclude(schema_name='public')

    for tenant in tenants:
        with tenant_context(tenant):
            from sales.models import Sale
            from inventory.models import Stock
            from stores.models import Store

            try:
                stores = Store.objects.filter(is_active=True)

                stats = {
                    'sales_today': float(Sale.objects.filter(
                        store__in=stores,
                        created_at__date=today,
                        status__in=['COMPLETED', 'PAID']
                    ).aggregate(total=Sum('total_amount'))['total'] or 0),

                    'sales_week': float(Sale.objects.filter(
                        store__in=stores,
                        created_at__date__gte=week_ago,
                        status__in=['COMPLETED', 'PAID']
                    ).aggregate(total=Sum('total_amount'))['total'] or 0),

                    'transactions_today': Sale.objects.filter(
                        store__in=stores,
                        created_at__date=today,
                        status__in=['COMPLETED', 'PAID']
                    ).count(),

                    'low_stock_count': Stock.objects.filter(
                        store__in=stores,
                        quantity__lte=F('low_stock_threshold')
                    ).count(),

                    'pending_fiscalization': Sale.objects.filter(
                        store__in=stores,
                        status__in=['COMPLETED', 'PAID'],
                        is_fiscalized=False,
                        fiscalization_status='PENDING',
                        created_at__date__gte=week_ago
                    ).count(),
                }

                from .consumers import broadcast_dashboard_update
                async_to_sync(broadcast_dashboard_update)(tenant.company_id, stats)

            except Exception as e:
                logger.error(f"Error updating dashboard cache for tenant {tenant.schema_name}: {str(e)}")


@shared_task
def check_stock_alerts():
    """Check for stock alerts and notify for all tenants"""
    from company.models import Company
    from django.db.models import F

    tenants = Company.objects.filter(is_active=True).exclude(schema_name='public')

    for tenant in tenants:
        with tenant_context(tenant):
            from inventory.models import Stock
            from .consumers import broadcast_alert

            critical_stock = Stock.objects.filter(
                quantity__lte=F('low_stock_threshold') / 2,
                quantity__gt=0
            ).select_related('product', 'store')

            for stock in critical_stock:
                try:
                    async_to_sync(broadcast_alert)(
                        tenant.company_id,
                        'low_stock',
                        f'{stock.product.name} is critically low at {stock.store.name}',
                        'critical',
                        {
                            'product_id': stock.product.id,
                            'store_id': stock.store.id,
                            'quantity': stock.quantity,
                            'threshold': stock.low_stock_threshold
                        }
                    )
                except Exception as e:
                    logger.error(f"Error sending stock alert: {str(e)}")

            out_of_stock = Stock.objects.filter(
                quantity=0
            ).select_related('product', 'store')

            for stock in out_of_stock:
                try:
                    async_to_sync(broadcast_alert)(
                        tenant.company_id,
                        'out_of_stock',
                        f'{stock.product.name} is out of stock at {stock.store.name}',
                        'critical',
                        {
                            'product_id': stock.product.id,
                            'store_id': stock.store.id
                        }
                    )
                except Exception as e:
                    logger.error(f"Error sending out of stock alert: {str(e)}")


@shared_task
def check_efris_compliance():
    """Check EFRIS compliance and send alerts for all tenants"""
    from company.models import Company
    from datetime import timedelta

    today = timezone.now().date()
    week_ago = today - timedelta(days=7)

    tenants = Company.objects.filter(is_active=True).exclude(schema_name='public')

    for tenant in tenants:
        with tenant_context(tenant):
            from sales.models import Sale
            from stores.models import Store
            from .consumers import broadcast_alert

            stores = Store.objects.filter(efris_enabled=True, is_active=True)

            for store in stores:
                try:
                    pending = Sale.objects.filter(
                        store=store,
                        status__in=['COMPLETED', 'PAID'],
                        is_fiscalized=False,
                        fiscalization_status='PENDING',
                        created_at__date__gte=week_ago
                    ).count()

                    if pending > 10:
                        async_to_sync(broadcast_alert)(
                            tenant.company_id,
                            'efris_pending',
                            f'{pending} sales pending fiscalization at {store.name}',
                            'warning',
                            {'store_id': store.id, 'count': pending}
                        )

                    failed = Sale.objects.filter(
                        store=store,
                        status__in=['COMPLETED', 'PAID'],
                        fiscalization_status='FAILED',
                        created_at__date__gte=week_ago
                    ).count()

                    if failed > 0:
                        async_to_sync(broadcast_alert)(
                            tenant.company_id,
                            'efris_failed',
                            f'{failed} sales failed fiscalization at {store.name}',
                            'critical',
                            {'store_id': store.id, 'count': failed}
                        )

                except Exception as e:
                    logger.error(f"Error checking EFRIS compliance for store {store.id}: {str(e)}")


@shared_task
def generate_report_comparison(comparison_id, schema_name):
    """Generate report comparison data"""
    tenant = get_tenant_from_schema(schema_name)
    if not tenant:
        return

    with tenant_context(tenant):
        from .models import ReportComparison

        try:
            comparison = ReportComparison.objects.get(id=comparison_id)

            base_results = generate_report_for_period(
                comparison.report,
                comparison.created_by,
                comparison.base_period
            )

            compare_results = generate_report_for_period(
                comparison.report,
                comparison.created_by,
                comparison.compare_period
            )

            comparison_data = calculate_comparison_metrics(
                base_results,
                compare_results,
                comparison.metrics
            )

            cache_key = f'report_comparison_{comparison_id}'
            cache.set(cache_key, comparison_data, 3600)

            comparison.last_run = timezone.now()
            comparison.save()

            logger.info(f"Report comparison generated: {comparison.name}")

            return comparison_data

        except Exception as e:
            logger.error(f"Error generating report comparison: {str(e)}", exc_info=True)
            raise


def generate_report_for_period(report, user, period):
    """Helper function to generate report for specific period"""
    from .services.report_generator import ReportGeneratorService

    generator = ReportGeneratorService(user, report)

    kwargs = {
        'start_date': period.get('start_date'),
        'end_date': period.get('end_date'),
    }

    return generator.generate(**kwargs)


def calculate_comparison_metrics(base_data, compare_data, metrics):
    """Calculate comparison metrics between two periods"""
    comparison = {
        'base_period': {},
        'compare_period': {},
        'changes': {},
        'percentage_changes': {}
    }

    for metric in metrics:
        base_value = get_metric_value(base_data, metric)
        compare_value = get_metric_value(compare_data, metric)

        comparison['base_period'][metric] = base_value
        comparison['compare_period'][metric] = compare_value
        comparison['changes'][metric] = compare_value - base_value

        if base_value != 0:
            comparison['percentage_changes'][metric] = (
                (compare_value - base_value) / base_value * 100
            )
        else:
            comparison['percentage_changes'][metric] = 0

    return comparison


def get_metric_value(data, metric):
    """Extract metric value from report data"""
    if 'summary' in data and metric in data['summary']:
        return data['summary'][metric]
    return 0


@shared_task
def log_report_access(report_id, user_id, schema_name, action, parameters=None, ip_address=None, user_agent=None):
    """Log report access for audit trail"""
    tenant = get_tenant_from_schema(schema_name)
    if not tenant:
        return

    with tenant_context(tenant):
        from .models import SavedReport, ReportAccessLog
        from accounts.models import CustomUser

        try:
            report = SavedReport.objects.get(id=report_id)
            user = CustomUser.objects.get(id=user_id)

            ReportAccessLog.objects.create(
                report=report,
                user=user,
                action=action,
                parameters=parameters or {},
                ip_address=ip_address,
                user_agent=user_agent,
                success=True
            )

        except Exception as e:
            logger.error(f"Error logging report access: {str(e)}")


@shared_task
def generate_efris_compliance_report(store_id, start_date, end_date, schema_name):
    """Generate EFRIS compliance report for specific store"""
    tenant = get_tenant_from_schema(schema_name)
    if not tenant:
        return

    with tenant_context(tenant):
        from stores.models import Store
        from sales.models import Sale
        from django.db.models import Count, Q

        try:
            store = Store.objects.get(id=store_id)

            sales = Sale.objects.filter(
                store=store,
                status__in=['COMPLETED', 'PAID'],
                created_at__date__gte=start_date,
                created_at__date__lte=end_date
            )

            compliance_data = {
                'store': store.name,
                'period': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat()
                },
                'total_sales': sales.count(),
                'fiscalized': sales.filter(is_fiscalized=True).count(),
                'pending':    sales.filter(is_fiscalized=False, fiscalization_status='PENDING').count(),
                'failed':     sales.filter(fiscalization_status='FAILED').count(),
            }

            if compliance_data['total_sales'] > 0:
                compliance_data['compliance_rate'] = (
                    compliance_data['fiscalized'] / compliance_data['total_sales'] * 100
                )
            else:
                compliance_data['compliance_rate'] = 0

            failed_sales = sales.filter(fiscalization_status='FAILED').values(
                'id', 'sale_number', 'total_amount', 'created_at', 'fiscalization_error'
            )[:50]

            compliance_data['failed_details'] = list(failed_sales)

            cache_key = f'efris_compliance_{schema_name}_{store_id}_{start_date}_{end_date}'
            cache.set(cache_key, compliance_data, 1800)

            logger.info(f"EFRIS compliance report generated for store {store.name}")

            return compliance_data

        except Exception as e:
            logger.error(f"Error generating EFRIS compliance report: {str(e)}", exc_info=True)
            raise


@shared_task
def export_report_to_efris_format(generated_report_id, schema_name):
    """Export report in EFRIS-compliant format"""
    tenant = get_tenant_from_schema(schema_name)
    if not tenant:
        return

    with tenant_context(tenant):
        from .models import GeneratedReport, EFRISReportTemplate
        import json

        try:
            report = GeneratedReport.objects.get(id=generated_report_id)

            template = EFRISReportTemplate.objects.filter(
                report_type=report.report.report_type,
                is_active=True,
                is_default=True
            ).first()

            if not template:
                raise ValueError(f"No EFRIS template found for report type {report.report.report_type}")

            with open(report.file_path, 'r') as f:
                if report.file_format == 'JSON':
                    report_data = json.load(f)
                else:
                    raise ValueError("Only JSON reports can be converted to EFRIS format")

            efris_data = transform_to_efris_format(report_data, template)

            efris_filename = report.file_path.replace('.json', '_efris.json')
            with open(efris_filename, 'w') as f:
                json.dump(efris_data, f, indent=2)

            report.is_efris_verified = True
            report.efris_verification_date = timezone.now()
            report.save()

            logger.info(f"Report exported to EFRIS format: {efris_filename}")

            return efris_filename

        except Exception as e:
            logger.error(f"Error exporting to EFRIS format: {str(e)}", exc_info=True)
            raise


def transform_to_efris_format(report_data, template):
    """Transform report data to EFRIS-compliant format"""
    efris_data = {
        'metadata': {
            'report_type': template.report_type,
            'template_version': template.version,
            'generated_at': timezone.now().isoformat(),
        },
        'data': report_data
    }

    return efris_data


@shared_task
def archive_old_reports(days=90):
    """Archive reports older than specified days for all tenants"""
    from company.models import Company
    from datetime import timedelta
    import shutil

    cutoff_date = timezone.now() - timedelta(days=days)
    total_count = 0

    tenants = Company.objects.filter(is_active=True).exclude(schema_name='public')

    for tenant in tenants:
        with tenant_context(tenant):
            from .models import GeneratedReport

            old_reports = GeneratedReport.objects.filter(
                generated_at__lt=cutoff_date,
                status='COMPLETED'
            )

            archive_dir = os.path.join(settings.MEDIA_ROOT, 'archived_reports', tenant.schema_name)
            os.makedirs(archive_dir, exist_ok=True)

            count = 0
            for report in old_reports:
                try:
                    if os.path.exists(report.file_path):
                        archive_path = os.path.join(
                            archive_dir,
                            os.path.basename(report.file_path)
                        )
                        shutil.move(report.file_path, archive_path)
                        report.file_path = archive_path
                        report.save()
                        count += 1

                except Exception as e:
                    logger.error(f"Error archiving report {report.id}: {str(e)}")

            logger.info(f"Archived {count} old reports for tenant {tenant.schema_name}")
            total_count += count

    logger.info(f"Total archived {total_count} old reports")
    return total_count


@shared_task
def update_real_time_dashboard():
    """Update real-time dashboard data"""
    update_dashboard_cache.delay()
    check_stock_alerts.delay()
    check_efris_compliance.delay()


# ─────────────────────────────────────────────────────────────────────────────
# DAILY / WEEKLY BROADCAST EMAIL REPORTS
# ─────────────────────────────────────────────────────────────────────────────

def build_report_data(schema_name, period_days=30):
    """
    Collect aggregated revenue, expense, inventory and store metrics for a
    single tenant schema.  Must be called from inside a schema_context block
    (or will open one itself).  Returns a plain-Python dict safe for email/JSON.
    """
    with schema_context(schema_name):
        from stores.models import Store
        from sales.models import Sale
        from expenses.models import Expense
        from company.models import Company

        today      = timezone.now().date()
        since      = today - timedelta(days=period_days)
        prev_since = today - timedelta(days=period_days * 2)

        company = Company.objects.filter(schema_name=schema_name, is_active=True).first()
        if not company:
            return None

        all_stores = Store.objects.filter(company=company)
        store_ids  = list(all_stores.values_list('id', flat=True))

        base_qs = Sale.objects.filter(
            store_id__in=store_ids,
            is_voided=False,
            status__in=['COMPLETED', 'PAID'],
        )

        current = base_qs.filter(created_at__date__gte=since).aggregate(
            revenue=Sum('total_amount'),
            sales=Count('id'),
            avg_sale=Avg('total_amount'),
        )

        previous = base_qs.filter(
            created_at__date__range=[prev_since, since]
        ).aggregate(
            revenue=Sum('total_amount'),
            sales=Count('id'),
        )

        cur_rev    = float(current['revenue']  or 0)
        prev_rev   = float(previous['revenue'] or 0)
        cur_sales  = int(current['sales']      or 0)
        prev_sales = int(previous['sales']     or 0)

        rev_growth   = round(((cur_rev   - prev_rev)   / prev_rev   * 100), 1) if prev_rev   else 0.0
        sales_growth = round(((cur_sales - prev_sales) / prev_sales * 100), 1) if prev_sales else 0.0

        expenses_qs  = Expense.objects.all()
        expenses_cur = float(expenses_qs.filter(date__gte=since).aggregate(t=Sum('amount'))['t'] or 0)
        pending_exp  = expenses_qs.filter(status='submitted').count()

        profit = cur_rev - expenses_cur
        margin = round((profit / cur_rev * 100), 1) if cur_rev else 0.0

        today_rev = float(
            base_qs.filter(created_at__date=today)
            .aggregate(t=Sum('total_amount'))['t'] or 0
        )
        today_exp = float(
            expenses_qs.filter(date=today).aggregate(t=Sum('amount'))['t'] or 0
        )

        try:
            from inventory.models import Stock
            low_stock = Stock.objects.filter(
                store__in=all_stores,
                quantity__lte=F('low_stock_threshold'),
                quantity__gt=0,
            ).count()
            out_stock = Stock.objects.filter(store__in=all_stores, quantity=0).count()
        except Exception:
            low_stock = out_stock = 0

        top_stores = list(
            base_qs.filter(created_at__date__gte=since)
            .values('store__name')
            .annotate(rev=Sum('total_amount'), cnt=Count('id'))
            .order_by('-rev')[:5]
        )

        return {
            'schema':         schema_name,
            'company_name':   company.name,
            'period_days':    period_days,
            'today':          str(today),
            'since':          str(since),
            'revenue':        cur_rev,
            'prev_revenue':   prev_rev,
            'rev_growth':     rev_growth,
            'sales_count':    cur_sales,
            'sales_growth':   sales_growth,
            'avg_sale':       float(current['avg_sale'] or 0),
            'today_revenue':  today_rev,
            'today_expenses': today_exp,
            'today_profit':   today_rev - today_exp,
            'expenses':       expenses_cur,
            'pending_exp':    pending_exp,
            'profit':         profit,
            'margin':         margin,
            'low_stock':      low_stock,
            'out_stock':      out_stock,
            'top_stores': [
                {'name': r['store__name'], 'rev': float(r['rev'] or 0), 'count': r['cnt']}
                for r in top_stores
            ],
        }


def build_html_email(data):
    """Render a polished HTML report email from a build_report_data() dict."""
    fmt   = lambda n: f"{float(n):,.0f}"
    pct   = lambda n: f"{float(n):+.1f}%"
    sign  = lambda n: "+" if float(n) >= 0 else ""
    p_col = "#16a34a" if data['profit'] >= 0 else "#dc2626"
    g_col = lambda g: "#16a34a" if float(g) >= 0 else "#dc2626"

    top_rows = "".join(
        f"<tr>"
        f"<td style='padding:8px 12px;border-bottom:1px solid #f0f0f0'>{s['name']}</td>"
        f"<td style='padding:8px 12px;border-bottom:1px solid #f0f0f0;text-align:right;"
        f"font-weight:600'>{fmt(s['rev'])}</td>"
        f"<td style='padding:8px 12px;border-bottom:1px solid #f0f0f0;text-align:right;"
        f"color:#6b7280'>{s['count']}</td>"
        f"</tr>"
        for s in data['top_stores']
    ) or "<tr><td colspan='3' style='padding:12px;color:#9ca3af;text-align:center'>No sales data</td></tr>"

    inv_alert = (
        f"<tr><td style='padding:12px 32px 0'>"
        f"<div style='background:#fffbeb;border-left:4px solid #d97706;border-radius:4px;"
        f"padding:10px 14px;font-size:13px;color:#92400e'>"
        f"⚠️ <strong>{data['low_stock']} low stock</strong> · "
        f"<strong>{data['out_stock']} out of stock</strong> items need attention"
        f"</div></td></tr>"
    ) if (data['low_stock'] or data['out_stock']) else ''

    p_bg  = '#f0fdf4' if data['profit'] >= 0 else '#fef2f2'
    p_bdr = '#bbf7d0' if data['profit'] >= 0 else '#fecaca'
    p_lbl = '#14532d' if data['profit'] >= 0 else '#991b1b'

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:'Segoe UI',Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:32px 16px">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08)">

  <!-- Header -->
  <tr><td style="background:linear-gradient(135deg,#1e40af,#7c3aed);padding:28px 32px">
    <h1 style="color:#fff;margin:0;font-size:22px;font-weight:700">📊 {data['company_name']}</h1>
    <p style="color:rgba(255,255,255,.8);margin:6px 0 0;font-size:14px">
      {data['period_days']}-Day Report &nbsp;·&nbsp; {data['since']} → {data['today']}
    </p>
  </td></tr>

  <!-- KPI cards -->
  <tr><td style="padding:24px 32px 0">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td width="33%" style="padding-right:8px">
        <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:16px;text-align:center">
          <div style="font-size:22px;font-weight:700;color:#d97706">{fmt(data['revenue'])}</div>
          <div style="font-size:11px;color:#92400e;text-transform:uppercase;letter-spacing:.05em;margin-top:4px">
            Revenue ({data['period_days']}d)</div>
          <div style="font-size:12px;color:{g_col(data['rev_growth'])};margin-top:4px;font-weight:600">
            {pct(data['rev_growth'])} vs prev</div>
        </div>
      </td>
      <td width="33%" style="padding:0 4px">
        <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:16px;text-align:center">
          <div style="font-size:22px;font-weight:700;color:#dc2626">{fmt(data['expenses'])}</div>
          <div style="font-size:11px;color:#991b1b;text-transform:uppercase;letter-spacing:.05em;margin-top:4px">
            Expenses ({data['period_days']}d)</div>
          <div style="font-size:12px;color:#6b7280;margin-top:4px">{data['pending_exp']} pending</div>
        </div>
      </td>
      <td width="33%" style="padding-left:8px">
        <div style="background:{p_bg};border:1px solid {p_bdr};border-radius:8px;padding:16px;text-align:center">
          <div style="font-size:22px;font-weight:700;color:{p_col}">{sign(data['profit'])}{fmt(data['profit'])}</div>
          <div style="font-size:11px;color:{p_lbl};text-transform:uppercase;letter-spacing:.05em;margin-top:4px">
            Net Profit</div>
          <div style="font-size:12px;color:{p_col};margin-top:4px;font-weight:600">
            Margin: {data['margin']}%</div>
        </div>
      </td>
    </tr></table>
  </td></tr>

  <!-- Today strip -->
  <tr><td style="padding:16px 32px 0">
    <div style="background:#f8faff;border:1px solid #dbeafe;border-radius:8px;padding:14px 18px">
      <table width="100%"><tr>
        <td style="font-size:12px;color:#6b7280">Today Revenue</td>
        <td style="font-size:12px;color:#6b7280">Today Expenses</td>
        <td style="font-size:12px;color:#6b7280">Today Profit</td>
        <td style="font-size:12px;color:#6b7280">Sales ({data['period_days']}d)</td>
      </tr><tr>
        <td style="font-size:16px;font-weight:700;color:#d97706">{fmt(data['today_revenue'])}</td>
        <td style="font-size:16px;font-weight:700;color:#dc2626">{fmt(data['today_expenses'])}</td>
        <td style="font-size:16px;font-weight:700;color:{p_col}">{sign(data['today_profit'])}{fmt(data['today_profit'])}</td>
        <td style="font-size:16px;font-weight:700;color:#2563eb">{data['sales_count']:,}</td>
      </tr></table>
    </div>
  </td></tr>

  {inv_alert}

  <!-- Top stores -->
  <tr><td style="padding:20px 32px 0">
    <h3 style="font-size:13px;font-weight:600;color:#374151;text-transform:uppercase;
               letter-spacing:.06em;margin:0 0 10px">Top Stores by Revenue</h3>
    <table width="100%" style="border-collapse:collapse;font-size:13px">
      <thead><tr style="background:#f9fafb">
        <th style="padding:8px 12px;text-align:left;font-size:11px;color:#6b7280;
                   font-weight:600;border-bottom:2px solid #e5e7eb">Store</th>
        <th style="padding:8px 12px;text-align:right;font-size:11px;color:#6b7280;
                   font-weight:600;border-bottom:2px solid #e5e7eb">Revenue</th>
        <th style="padding:8px 12px;text-align:right;font-size:11px;color:#6b7280;
                   font-weight:600;border-bottom:2px solid #e5e7eb">Sales</th>
      </tr></thead>
      <tbody>{top_rows}</tbody>
    </table>
  </td></tr>

  <!-- Footer -->
  <tr><td style="padding:24px 32px;border-top:1px solid #f3f4f6;margin-top:20px">
    <p style="margin:0;font-size:12px;color:#9ca3af;text-align:center">
      {settings.SITE_NAME} · Automated report · {data['today']}<br>
      <a href="{settings.FRONTEND_URL}" style="color:#2563eb;text-decoration:none">Open Dashboard</a>
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def get_report_recipients(schema_name):
    """
    Return list of admin email addresses to receive broadcast reports for this
    tenant.  Queries company_admin users with valid emails.
    """
    with schema_context(schema_name):
        from accounts.models import CustomUser
        return list(
            CustomUser.objects.filter(
                is_active=True,
                is_hidden=False,
                company_admin=True,
                email__isnull=False,
            ).exclude(email='').values_list('email', flat=True)
        )


@shared_task(bind=True, name='reports.tasks.send_daily_report', max_retries=3)
def send_daily_report(self, schema_name, recipient_override=None):
    """
    Send a 30-day revenue/expense/profit summary email for a single tenant.
    """
    logger.info(f'[reports] send_daily_report starting  schema={schema_name}')
    try:
        data = build_report_data(schema_name, period_days=30)
        if not data:
            logger.warning(f'[reports] No company in schema={schema_name}, skipping')
            return {'status': 'skipped', 'reason': 'no_company'}

        recipients = [recipient_override] if recipient_override else get_report_recipients(schema_name)
        if not recipients:
            logger.warning(f'[reports] No recipients for schema={schema_name}')
            return {'status': 'skipped', 'reason': 'no_recipients'}

        subject = f"📊 Daily Report — {data['company_name']} — {data['today']}"
        html    = build_html_email(data)
        plain   = (
            f"Daily Report: {data['company_name']}\n"
            f"Period: {data['since']} → {data['today']}\n\n"
            f"Revenue:   {data['revenue']:>14,.0f}  ({data['rev_growth']:+.1f}% vs prev)\n"
            f"Expenses:  {data['expenses']:>14,.0f}\n"
            f"Profit:    {data['profit']:>14,.0f}  (Margin: {data['margin']}%)\n\n"
            f"Today Revenue:  {data['today_revenue']:>10,.0f}\n"
            f"Today Expenses: {data['today_expenses']:>10,.0f}\n"
            f"Today Profit:   {data['today_profit']:>10,.0f}\n\n"
            f"Low Stock: {data['low_stock']}   Out of Stock: {data['out_stock']}\n"
        )

        send_mail(
            subject=subject,
            message=plain,
            html_message=html,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )

        logger.info(f'[reports] Daily report sent to {recipients}  schema={schema_name}')
        return {'status': 'sent', 'recipients': recipients, 'schema': schema_name}

    except Exception as exc:
        logger.error(f'[reports] send_daily_report failed  schema={schema_name}: {exc}', exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, name='reports.tasks.send_weekly_report', max_retries=3)
def send_weekly_report(self, schema_name, recipient_override=None):
    """
    Send a 7-day summary email for a single tenant.
    """
    logger.info(f'[reports] send_weekly_report starting  schema={schema_name}')
    try:
        data = build_report_data(schema_name, period_days=7)
        if not data:
            return {'status': 'skipped', 'reason': 'no_company'}

        recipients = [recipient_override] if recipient_override else get_report_recipients(schema_name)
        if not recipients:
            return {'status': 'skipped', 'reason': 'no_recipients'}

        subject = f"📈 Weekly Report — {data['company_name']} — {data['today']}"
        html    = build_html_email(data)
        plain   = (
            f"Weekly Report: {data['company_name']}\n"
            f"Period: last 7 days\n\n"
            f"Revenue:  {data['revenue']:,.0f}\n"
            f"Expenses: {data['expenses']:,.0f}\n"
            f"Profit:   {data['profit']:,.0f}  ({data['margin']}% margin)\n"
            f"Sales:    {data['sales_count']}\n"
        )

        send_mail(
            subject=subject,
            message=plain,
            html_message=html,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )

        logger.info(f'[reports] Weekly report sent to {recipients}  schema={schema_name}')
        return {'status': 'sent', 'recipients': recipients}

    except Exception as exc:
        logger.error(f'[reports] send_weekly_report failed  schema={schema_name}: {exc}', exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(name='reports.tasks.dispatch_daily_reports')
def dispatch_daily_reports():
    """
    Master Beat task: fan-out send_daily_report to every active tenant.
    """
    tenants = get_all_tenants()
    count   = 0
    for tenant in tenants:
        send_daily_report.delay(tenant.schema_name)
        count += 1
    logger.info(f'[reports] dispatch_daily_reports queued {count} tenant tasks')
    return {'queued': count}


@shared_task(name='reports.tasks.dispatch_weekly_reports')
def dispatch_weekly_reports():
    """
    Master Beat task: fan-out send_weekly_report to every active tenant.
    """
    tenants = get_all_tenants()
    count   = 0
    for tenant in tenants:
        send_weekly_report.delay(tenant.schema_name)
        count += 1
    logger.info(f'[reports] dispatch_weekly_reports queued {count} tenant tasks')
    return {'queued': count}