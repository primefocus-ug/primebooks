"""
Celery Tasks for Asynchronous Report Generation
"""
from celery import shared_task
from django.core.cache import cache
from django.utils import timezone
from django.conf import settings
from django.core.mail import EmailMessage
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django_tenants.utils import schema_context, tenant_context
from django.db import connection
import os
import time
import logging

logger = logging.getLogger(__name__)


def get_tenant_from_schema(schema_name):
    """Helper function to get tenant object from schema name"""
    from company.models import Company  # Company is in shared_apps
    try:
        return Company.objects.get(schema_name=schema_name)
    except Company.DoesNotExist:
        logger.error(f"Tenant not found for schema: {schema_name}")
        return None


@shared_task(bind=True, max_retries=3)
def generate_report_async(self, report_id, user_id, schema_name, **kwargs):
    """
    Asynchronously generate report with progress tracking

    Args:
        report_id: ID of the SavedReport
        user_id: ID of the user
        schema_name: Tenant schema name to execute in
    """
    tenant = get_tenant_from_schema(schema_name)
    if not tenant:
        logger.error(f"Cannot generate report: tenant not found for schema {schema_name}")
        return {'success': False, 'error': 'Tenant not found'}

    with tenant_context(tenant):
        from .models import SavedReport, GeneratedReport
        from accounts.models import CustomUser
        from .services.report_generator import ReportGeneratorService
        from .services.pdf_export import PDFExportService
        from .services.excel_export import ExcelExportService
        from .consumers import send_report_progress, send_report_complete, send_report_failed

        try:
            # Get report and user
            report = SavedReport.objects.get(id=report_id)
            user = CustomUser.objects.get(id=user_id)

            # Create GeneratedReport record
            generated_report = GeneratedReport.objects.create(
                report=report,
                generated_by=user,
                parameters=kwargs,
                file_format=kwargs.get('format', 'PDF'),
                status='PROCESSING',
                task_id=self.request.id
            )

            # Send progress: Starting
            async_to_sync(send_report_progress)(
                generated_report.id, 10, 'Initializing report generation...', 'processing'
            )

            # Generate report data
            logger.info(f"Starting report generation: {report.name} for user {user.id} in schema {schema_name}")
            start_time = time.time()

            generator = ReportGeneratorService(user, report)

            # Send progress: Fetching data
            async_to_sync(send_report_progress)(
                generated_report.id, 30, 'Fetching data from database...', 'processing'
            )

            report_data = generator.generate(**kwargs)

            # Send progress: Processing data
            async_to_sync(send_report_progress)(
                generated_report.id, 50, 'Processing report data...', 'processing'
            )

            # Get company info for export
            company_info = {
                'name': user.company.name if user.company else 'Company',
                'address': user.company.physical_address if user.company else '',
                'phone': user.company.phone if user.company else '',
                'email': user.company.email if user.company else '',
                'tin': user.company.tin if user.company else '',
                'logo_path': user.company.logo.path if user.company and user.company.logo else None,
                'watermark': kwargs.get('watermark', 'PRIME BOOKS UG') if kwargs.get('confidential') else '',
                'confidential': kwargs.get('confidential', False),
            }

            # Generate file based on format
            file_format = kwargs.get('format', 'PDF')

            # Send progress: Generating file
            async_to_sync(send_report_progress)(
                generated_report.id, 70, f'Generating {file_format} file...', 'processing'
            )

            if file_format == 'PDF':
                orientation = report.pdf_orientation if report.pdf_orientation != 'auto' else 'auto'
                pdf_service = PDFExportService(report_data, report.name, company_info, orientation)
                file_buffer = pdf_service.generate_pdf()
                file_extension = 'pdf'

            elif file_format == 'XLSX':
                excel_service = ExcelExportService(report_data, report.name, company_info)
                file_buffer = excel_service.generate_excel()
                file_extension = 'xlsx'

            elif file_format == 'CSV':
                from .services.csv_export import CSVExportService
                csv_service = CSVExportService(report_data, report.name)
                file_buffer = csv_service.generate_csv()
                file_extension = 'csv'

            elif file_format == 'JSON':
                import json
                from io import BytesIO
                file_buffer = BytesIO()
                file_buffer.write(json.dumps(report_data, default=str, indent=2).encode('utf-8'))
                file_buffer.seek(0)
                file_extension = 'json'

            else:
                raise ValueError(f"Unsupported format: {file_format}")

            # Save file
            async_to_sync(send_report_progress)(
                generated_report.id, 85, 'Saving file...', 'processing'
            )

            timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{report.name.replace(' ', '_')}_{timestamp}.{file_extension}"

            # Create tenant-specific reports directory
            reports_dir = os.path.join(settings.MEDIA_ROOT, 'generated_reports', schema_name)
            os.makedirs(reports_dir, exist_ok=True)

            file_path = os.path.join(reports_dir, filename)

            with open(file_path, 'wb') as f:
                f.write(file_buffer.getvalue())

            file_size = os.path.getsize(file_path)
            generation_time = time.time() - start_time

            # Count rows
            row_count = 0
            if 'grouped_data' in report_data:
                row_count = len(report_data['grouped_data'])
            elif 'products' in report_data:
                row_count = len(report_data['products'])
            elif 'inventory' in report_data:
                row_count = len(report_data['inventory'])

            # Update generated report
            generated_report.mark_as_completed(file_path, file_size, row_count, generation_time)

            # Send progress: Complete
            async_to_sync(send_report_progress)(
                generated_report.id, 100, 'Report generated successfully!', 'completed'
            )

            download_url = f'/reports/download/{generated_report.id}/'

            async_to_sync(send_report_complete)(
                generated_report.id,
                generated_report.id,
                download_url,
                file_size,
                row_count
            )

            logger.info(f"Report generated successfully: {report.name} (ID: {generated_report.id})")

            # Send email if requested
            if kwargs.get('email_report'):
                send_report_email.delay(generated_report.id, kwargs.get('email_recipients'), schema_name)

            # Invalidate cache
            cache.delete(f'dashboard_stats_{user.id}')

            return {
                'success': True,
                'generated_report_id': generated_report.id,
                'file_path': file_path,
                'file_size': file_size,
                'generation_time': generation_time
            }

        except Exception as e:
            logger.error(f"Error generating report in schema {schema_name}: {str(e)}", exc_info=True)

            try:
                generated_report.mark_as_failed(str(e))

                async_to_sync(send_report_failed)(
                    generated_report.id,
                    str(e)
                )
            except:
                pass

            # Retry on certain errors
            if 'database' in str(e).lower() or 'timeout' in str(e).lower():
                raise self.retry(exc=e, countdown=60)

            raise


@shared_task
def send_report_email(generated_report_id, recipients, schema_name):
    """Send generated report via email"""
    tenant = get_tenant_from_schema(schema_name)
    if not tenant:
        return

    with tenant_context(tenant):
        from .models import GeneratedReport

        try:
            report = GeneratedReport.objects.get(id=generated_report_id)

            if not os.path.exists(report.file_path):
                logger.error(f"Report file not found: {report.file_path}")
                return

            # Parse recipients
            if isinstance(recipients, str):
                recipients = [email.strip() for email in recipients.split(',')]

            subject = f"Report: {report.report.name}"
            body = f"""
            Hello,

            Your requested report "{report.report.name}" has been generated successfully.

            Report Details:
            - Generated At: {report.generated_at.strftime('%B %d, %Y %I:%M %p')}
            - Format: {report.file_format}
            - File Size: {report.file_size / 1024:.2f} KB
            - Rows: {report.row_count:,}

            Please find the report attached to this email.

            Best regards,
            {report.generated_by.company.name if report.generated_by.company else 'System'}
            """

            email = EmailMessage(
                subject=subject,
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=recipients
            )

            email.attach_file(report.file_path)
            email.send()

            logger.info(f"Report emailed successfully to {recipients}")

        except Exception as e:
            logger.error(f"Error sending report email: {str(e)}", exc_info=True)


@shared_task
def process_scheduled_reports():
    """Process due scheduled reports for all tenants"""
    from company.models import Company
    from django.utils import timezone

    now = timezone.now()

    # Get all active tenants
    tenants = Company.objects.filter(is_active=True).exclude(schema_name='public')

    for tenant in tenants:
        with tenant_context(tenant):
            from .models import ReportSchedule

            # Get due schedules for this tenant
            due_schedules = ReportSchedule.objects.filter(
                is_active=True,
                next_scheduled__lte=now
            ).select_related('report')

            for schedule in due_schedules:
                try:
                    logger.info(f"Processing scheduled report: {schedule.report.name} for tenant {tenant.schema_name}")

                    # Get report creator
                    user = schedule.report.created_by

                    # Generate report
                    kwargs = schedule.report.filters or {}
                    kwargs['format'] = schedule.format
                    kwargs['email_report'] = True
                    kwargs['email_recipients'] = schedule.recipients

                    # Start async generation with schema_name
                    generate_report_async.delay(
                        schedule.report.id,
                        user.id,
                        tenant.schema_name,  # Pass schema name
                        **kwargs
                    )

                    # Update schedule
                    schedule.last_sent = now
                    schedule.calculate_next_run()
                    schedule.retry_count = 0
                    schedule.save()

                except Exception as e:
                    logger.error(f"Error processing scheduled report {schedule.id}: {str(e)}")

                    schedule.retry_count += 1
                    if schedule.retry_count >= schedule.max_retries:
                        schedule.is_active = False
                        logger.error(f"Deactivating schedule {schedule.id} after max retries")

                    schedule.save()


@shared_task
def cleanup_expired_reports():
    """Clean up expired generated reports for all tenants"""
    from company.models import Company
    from django.utils import timezone

    now = timezone.now()
    total_count = 0

    # Get all active tenants
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
                    # Delete file
                    if os.path.exists(report.file_path):
                        os.remove(report.file_path)
                        logger.info(f"Deleted expired report file: {report.file_path}")

                    # Delete record
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

    # Get all active tenants
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
                        is_completed=True
                    ).aggregate(total=Sum('total_amount'))['total'] or 0),

                    'sales_week': float(Sale.objects.filter(
                        store__in=stores,
                        created_at__date__gte=week_ago,
                        is_completed=True
                    ).aggregate(total=Sum('total_amount'))['total'] or 0),

                    'transactions_today': Sale.objects.filter(
                        store__in=stores,
                        created_at__date=today,
                        is_completed=True
                    ).count(),

                    'low_stock_count': Stock.objects.filter(
                        store__in=stores,
                        quantity__lte=F('low_stock_threshold')
                    ).count(),

                    'pending_fiscalization': Sale.objects.filter(
                        store__in=stores,
                        is_completed=True,
                        is_fiscalized=False,
                        created_at__date__gte=week_ago
                    ).count(),
                }

                # Broadcast to connected clients
                from .consumers import broadcast_dashboard_update
                async_to_sync(broadcast_dashboard_update)(tenant.company_id, stats)

            except Exception as e:
                logger.error(f"Error updating dashboard cache for tenant {tenant.schema_name}: {str(e)}")


@shared_task
def check_stock_alerts():
    """Check for stock alerts and notify for all tenants"""
    from company.models import Company
    from django.db.models import F

    # Get all active tenants
    tenants = Company.objects.filter(is_active=True).exclude(schema_name='public')

    for tenant in tenants:
        with tenant_context(tenant):
            from inventory.models import Stock
            from .consumers import broadcast_alert

            # Check for critical low stock
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

            # Check for out of stock
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

    # Get all active tenants
    tenants = Company.objects.filter(is_active=True).exclude(schema_name='public')

    for tenant in tenants:
        with tenant_context(tenant):
            from sales.models import Sale
            from stores.models import Store
            from .consumers import broadcast_alert

            # Get all stores with EFRIS enabled
            stores = Store.objects.filter(efris_enabled=True, is_active=True)

            for store in stores:
                try:
                    # Check pending fiscalization
                    pending = Sale.objects.filter(
                        store=store,
                        is_completed=True,
                        is_fiscalized=False,
                        created_at__date__gte=week_ago
                    ).count()

                    if pending > 10:  # Alert if more than 10 pending
                        async_to_sync(broadcast_alert)(
                            tenant.company_id,
                            'efris_pending',
                            f'{pending} sales pending fiscalization at {store.name}',
                            'warning',
                            {
                                'store_id': store.id,
                                'count': pending
                            }
                        )

                    # Check failed fiscalization
                    failed = Sale.objects.filter(
                        store=store,
                        is_completed=True,
                        fiscalization_failed=True,
                        created_at__date__gte=week_ago
                    ).count()

                    if failed > 0:
                        async_to_sync(broadcast_alert)(
                            tenant.company_id,
                            'efris_failed',
                            f'{failed} sales failed fiscalization at {store.name}',
                            'critical',
                            {
                                'store_id': store.id,
                                'count': failed
                            }
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

            # Generate reports for both periods
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

            # Calculate differences
            comparison_data = calculate_comparison_metrics(
                base_results,
                compare_results,
                comparison.metrics
            )

            # Cache results
            cache_key = f'report_comparison_{comparison_id}'
            cache.set(cache_key, comparison_data, 3600)  # Cache for 1 hour

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

            # Get sales in period
            sales = Sale.objects.filter(
                store=store,
                is_completed=True,
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
                'pending': sales.filter(is_fiscalized=False, fiscalization_failed=False).count(),
                'failed': sales.filter(fiscalization_failed=True).count(),
            }

            # Calculate compliance rate
            if compliance_data['total_sales'] > 0:
                compliance_data['compliance_rate'] = (
                        compliance_data['fiscalized'] / compliance_data['total_sales'] * 100
                )
            else:
                compliance_data['compliance_rate'] = 0

            # Get failed sales details
            failed_sales = sales.filter(fiscalization_failed=True).values(
                'id', 'sale_number', 'total_amount', 'created_at', 'fiscalization_error'
            )[:50]

            compliance_data['failed_details'] = list(failed_sales)

            # Cache results
            cache_key = f'efris_compliance_{schema_name}_{store_id}_{start_date}_{end_date}'
            cache.set(cache_key, compliance_data, 1800)  # Cache for 30 minutes

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

            # Get appropriate EFRIS template
            template = EFRISReportTemplate.objects.filter(
                report_type=report.report.report_type,
                is_active=True,
                is_default=True
            ).first()

            if not template:
                raise ValueError(f"No EFRIS template found for report type {report.report.report_type}")

            # Load report data
            with open(report.file_path, 'r') as f:
                if report.file_format == 'JSON':
                    report_data = json.load(f)
                else:
                    raise ValueError("Only JSON reports can be converted to EFRIS format")

            # Transform to EFRIS format
            efris_data = transform_to_efris_format(report_data, template)

            # Save EFRIS-compliant file
            efris_filename = report.file_path.replace('.json', '_efris.json')
            with open(efris_filename, 'w') as f:
                json.dump(efris_data, f, indent=2)

            # Update report
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

    # Get all active tenants
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
                        # Move to archive
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


# Periodic task to run every 5 minutes
@shared_task
def update_real_time_dashboard():
    """Update real-time dashboard data"""
    update_dashboard_cache.delay()
    check_stock_alerts.delay()
    check_efris_compliance.delay()

