import logging
from datetime import datetime, timedelta
from django.db.models import Sum, Count, Avg, F, Q
from django.utils import timezone

logger = logging.getLogger(__name__)


class StoreReportHelper:
    """Helper class for generating store reports with common calculations"""

    @staticmethod
    def get_store_summary_data(stores, start_date, end_date):
        """Get summary data for stores"""
        summary_data = []

        for store in stores:
            # Calculate inventory value
            from inventory.models import Stock
            inventory_value = Stock.objects.filter(
                store=store
            ).aggregate(
                total=Sum(F('quantity') * F('product__cost_price'))
            )['total'] or 0

            # Get staff count
            staff_count = store.staff.filter(is_hidden=False).count()

            # Get device count
            device_count = store.devices.filter(is_active=True).count()

            # Get low stock count
            low_stock_count = Stock.objects.filter(
                store=store,
                quantity__lte=F('low_stock_threshold')
            ).count()

            # Get sales data if available
            try:
                from sales.models import Sale
                sales_data = Sale.objects.filter(
                    store=store,
                    created_at__date__gte=start_date,
                    created_at__date__lte=end_date,
                    is_completed=True
                ).aggregate(
                    total_sales=Sum('total_amount'),
                    total_transactions=Count('id'),
                    avg_transaction=Avg('total_amount')
                )
            except:
                sales_data = {
                    'total_sales': 0,
                    'total_transactions': 0,
                    'avg_transaction': 0
                }

            summary_data.append({
                'store': store,
                'inventory_value': inventory_value,
                'staff_count': staff_count,
                'device_count': device_count,
                'low_stock_count': low_stock_count,
                'sales_data': sales_data,
            })

        return summary_data

    @staticmethod
    def get_inventory_summary(stores, start_date, end_date):
        """Get inventory summary for stores"""
        from inventory.models import Stock

        inventory_data = []

        for store in stores:
            stock_items = Stock.objects.filter(
                store=store
            ).select_related('product', 'product__category')

            # Calculate totals
            total_items = stock_items.count()
            total_quantity = stock_items.aggregate(Sum('quantity'))['quantity__sum'] or 0
            total_value = stock_items.aggregate(
                total=Sum(F('quantity') * F('product__cost_price'))
            )['total'] or 0

            # Low stock items
            low_stock = stock_items.filter(
                quantity__lte=F('low_stock_threshold'),
                quantity__gt=0
            )

            # Out of stock items
            out_of_stock = stock_items.filter(quantity=0)

            inventory_data.append({
                'store': store,
                'total_items': total_items,
                'total_quantity': total_quantity,
                'total_value': total_value,
                'low_stock_items': low_stock,
                'low_stock_count': low_stock.count(),
                'out_of_stock_items': out_of_stock,
                'out_of_stock_count': out_of_stock.count(),
                'items': stock_items,
            })

        return inventory_data

    @staticmethod
    def get_device_summary(stores):
        """Get device summary for stores"""
        device_data = []

        for store in stores:
            devices = store.devices.all()

            active_devices = devices.filter(is_active=True)
            inactive_devices = devices.filter(is_active=False)

            # Devices needing maintenance
            maintenance_due = devices.filter(
                last_maintenance__lt=timezone.now() - timedelta(days=90)
            ) if devices.filter(last_maintenance__isnull=False).exists() else devices.none()

            device_data.append({
                'store': store,
                'total_devices': devices.count(),
                'active_devices': active_devices.count(),
                'inactive_devices': inactive_devices.count(),
                'maintenance_due': maintenance_due.count(),
                'devices': devices,
            })

        return device_data

    @staticmethod
    def get_staff_summary(stores):
        """Get staff summary for stores"""
        staff_data = []

        for store in stores:
            staff = store.staff.filter(is_hidden=False)

            active_staff = staff.filter(is_active=True)
            inactive_staff = staff.filter(is_active=False)

            # Group by user type if available
            staff_by_type = {}
            for member in staff:
                user_type = getattr(member, 'user_type', 'STAFF')
                if user_type not in staff_by_type:
                    staff_by_type[user_type] = 0
                staff_by_type[user_type] += 1

            staff_data.append({
                'store': store,
                'total_staff': staff.count(),
                'active_staff': active_staff.count(),
                'inactive_staff': inactive_staff.count(),
                'staff_by_type': staff_by_type,
                'staff': staff,
            })

        return staff_data

    @staticmethod
    def format_currency(amount, currency='UGX'):
        """Format currency value"""
        try:
            return f"{currency} {amount:,.2f}"
        except:
            return f"{currency} 0.00"

    @staticmethod
    def calculate_percentage_change(current, previous):
        """Calculate percentage change"""
        if previous == 0:
            return 100 if current > 0 else 0

        return ((current - previous) / previous) * 100

    @staticmethod
    def get_date_range_label(start_date, end_date):
        """Get formatted date range label"""
        if start_date == end_date:
            return start_date.strftime('%B %d, %Y')

        if start_date.year == end_date.year:
            if start_date.month == end_date.month:
                return f"{start_date.strftime('%B %d')} - {end_date.strftime('%d, %Y')}"
            else:
                return f"{start_date.strftime('%B %d')} - {end_date.strftime('%B %d, %Y')}"
        else:
            return f"{start_date.strftime('%B %d, %Y')} - {end_date.strftime('%B %d, %Y')}"

    @staticmethod
    def validate_date_range(start_date, end_date, max_days=365):
        """Validate date range"""
        if start_date > end_date:
            return False, "Start date must be before end date"

        date_diff = (end_date - start_date).days
        if date_diff > max_days:
            return False, f"Date range cannot exceed {max_days} days"

        if date_diff < 0:
            return False, "Invalid date range"

        return True, "Valid date range"

    @staticmethod
    def get_report_filename(report_type, format_type, timestamp=None):
        """Generate report filename"""
        if timestamp is None:
            timestamp = datetime.now()

        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
        report_type_clean = report_type.lower().replace(' ', '_')

        return f"store_report_{report_type_clean}_{timestamp_str}.{format_type}"


class ReportExportHelper:
    """Helper class for exporting reports in different formats"""

    @staticmethod
    def prepare_csv_data(data, columns):
        """Prepare data for CSV export"""
        rows = []
        rows.append(columns)  # Header row

        for item in data:
            row = [item.get(col, '') for col in columns]
            rows.append(row)

        return rows

    @staticmethod
    def apply_excel_styling(worksheet, header_color='366092'):
        """Apply standard Excel styling"""
        from openpyxl.styles import Font, PatternFill, Alignment

        # Style header row
        for cell in worksheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(
                start_color=header_color,
                end_color=header_color,
                fill_type="solid"
            )
            cell.alignment = Alignment(horizontal="center")

        return worksheet

    @staticmethod
    def auto_adjust_column_widths(worksheet, max_width=50):
        """Auto-adjust column widths in Excel"""
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter

            for cell in column:
                try:
                    if cell.value and len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass

            adjusted_width = min(max_length + 2, max_width)
            worksheet.column_dimensions[column_letter].width = adjusted_width

        return worksheet


class ReportCacheHelper:
    """Helper class for caching report data"""

    @staticmethod
    def get_cache_key(user_id, report_type, **kwargs):
        """Generate cache key for report data"""
        from hashlib import md5

        cache_params = f"{user_id}_{report_type}"
        for key, value in sorted(kwargs.items()):
            cache_params += f"_{key}_{value}"

        cache_hash = md5(cache_params.encode()).hexdigest()
        return f"store_report_{cache_hash}"

    @staticmethod
    def cache_report_data(cache_key, data, timeout=300):
        """Cache report data"""
        from django.core.cache import cache

        try:
            cache.set(cache_key, data, timeout)
            return True
        except Exception as e:
            logger.error(f"Error caching report data: {e}")
            return False

    @staticmethod
    def get_cached_report_data(cache_key):
        """Get cached report data"""
        from django.core.cache import cache

        try:
            return cache.get(cache_key)
        except Exception as e:
            logger.error(f"Error retrieving cached report data: {e}")
            return None

    @staticmethod
    def invalidate_cache(user_id=None, report_type=None):
        """Invalidate cached report data"""
        from django.core.cache import cache

        try:
            if user_id and report_type:
                # Invalidate specific user's report type
                pattern = f"store_report_*{user_id}*{report_type}*"
            elif user_id:
                # Invalidate all reports for user
                pattern = f"store_report_*{user_id}*"
            else:
                # Invalidate all reports
                pattern = "store_report_*"

            # Note: This requires cache backend that supports pattern deletion
            cache.delete_pattern(pattern)
            return True
        except Exception as e:
            logger.error(f"Error invalidating cache: {e}")
            return False