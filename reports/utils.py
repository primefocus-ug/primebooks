import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from django.conf import settings
from django.core.mail import send_mail, EmailMessage
from django.template.loader import render_to_string
from django.utils.translation import gettext as _
from django.db.models import Q, Sum, Count, Avg
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import pandas as pd
import requests
from .models import SavedReport, GeneratedReport, EFRISReportTemplate

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Advanced report generation utility with multiple format support"""
    
    def __init__(self, saved_report: SavedReport, user):
        self.saved_report = saved_report
        self.user = user
        self.data = None
        self.report_path = None
        
    def generate(self, file_format: str = 'PDF', include_charts: bool = True, 
                efris_verify: bool = False) -> GeneratedReport:
        """Generate report in specified format"""
        
        try:
            # Get report data
            self.data = self._get_report_data()
            
            # Generate file based on format
            if file_format.upper() == 'PDF':
                self.report_path = self._generate_pdf(include_charts)
            elif file_format.upper() == 'XLSX':
                self.report_path = self._generate_excel(include_charts)
            elif file_format.upper() == 'CSV':
                self.report_path = self._generate_csv()
            elif file_format.upper() == 'JSON':
                self.report_path = self._generate_json()
            else:
                raise ValueError(f"Unsupported format: {file_format}")
            
            # Create GeneratedReport record
            generated_report = GeneratedReport.objects.create(
                report=self.saved_report,
                generated_by=self.user,
                parameters={
                    'format': file_format,
                    'include_charts': include_charts,
                    'filters': self.saved_report.filters,
                    'columns': self.saved_report.columns
                },
                file_path=self.report_path,
                file_format=file_format.upper()
            )
            
            # EFRIS verification if requested
            if efris_verify and self.saved_report.is_efris_approved:
                efris = EFRISIntegration()
                verification_result = efris.verify_report(generated_report)
                if verification_result['success']:
                    generated_report.is_efris_verified = True
                    generated_report.efris_verification_code = verification_result['code']
                    generated_report.save()
            
            logger.info(f"Report generated successfully: {self.report_path}")
            return generated_report
            
        except Exception as e:
            logger.error(f"Report generation failed: {str(e)}")
            raise
    
    def get_preview_data(self, limit: int = 10) -> Dict[str, Any]:
        """Get preview data for report configuration"""
        
        try:
            data = self._get_report_data(limit=limit)
            return {
                'success': True,
                'rows': data['rows'][:limit],
                'columns': data['columns'],
                'total_count': data['total_count']
            }
        except Exception as e:
            logger.error(f"Preview generation failed: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def email_report(self, generated_report: GeneratedReport, recipients: List[str]):
        """Email generated report to recipients"""
        
        try:
            subject = f"Report: {self.saved_report.name}"
            
            # Render email template
            context = {
                'report': self.saved_report,
                'generated_report': generated_report,
                'user': self.user,
                'download_url': f"{settings.SITE_URL}/reports/download/{generated_report.id}/"
            }
            
            html_content = render_to_string('reports/email/report_notification.html', context)
            text_content = render_to_string('reports/email/report_notification.txt', context)
            
            # Create email with attachment
            email = EmailMessage(
                subject=subject,
                body=text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=recipients
            )
            
            # Attach report file
            if os.path.exists(generated_report.file_path):
                with open(generated_report.file_path, 'rb') as f:
                    email.attach(
                        f"{self.saved_report.name}.{generated_report.file_format.lower()}",
                        f.read(),
                        self._get_content_type(generated_report.file_format)
                    )
            
            email.send()
            logger.info(f"Report emailed to {len(recipients)} recipients")
            
        except Exception as e:
            logger.error(f"Email sending failed: {str(e)}")
            raise
    
    def _get_report_data(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """Get data for report based on type and filters"""
        
        report_type = self.saved_report.report_type
        filters = self.saved_report.filters or {}
        columns = self.saved_report.columns or []
        
        # Dynamic data fetching based on report type
        if report_type == 'SALES_SUMMARY':
            return self._get_sales_summary_data(filters, columns, limit)
        elif report_type == 'PRODUCT_PERFORMANCE':
            return self._get_product_performance_data(filters, columns, limit)
        elif report_type == 'INVENTORY_STATUS':
            return self._get_inventory_status_data(filters, columns, limit)
        elif report_type == 'TAX_REPORT':
            return self._get_tax_report_data(filters, columns, limit)
        elif report_type == 'Z_REPORT':
            return self._get_z_report_data(filters, columns, limit)
        elif report_type == 'EFRIS_COMPLIANCE':
            return self._get_efris_compliance_data(filters, columns, limit)
        else:
            raise ValueError(f"Unsupported report type: {report_type}")
    
    def _get_sales_summary_data(self, filters: Dict, columns: List, limit: Optional[int]) -> Dict:
        """Get sales summary data - replace with actual model queries"""
        
        # This would typically query your Sales/Transaction models
        # For demonstration, returning mock data
        
        date_from = filters.get('date_from')
        date_to = filters.get('date_to')
        
        # Mock data - replace with actual database queries
        mock_data = [
            {
                'date': '2024-01-15',
                'total_sales': 15420.50,
                'tax_amount': 2313.08,
                'net_amount': 13107.42,
                'transaction_count': 45,
                'average_sale': 342.68
            },
            {
                'date': '2024-01-16',
                'total_sales': 18750.25,
                'tax_amount': 2812.54,
                'net_amount': 15937.71,
                'transaction_count': 52,
                'average_sale': 360.58
            },
            # Add more mock data...
        ]
        
        if limit:
            mock_data = mock_data[:limit]
        
        return {
            'rows': mock_data,
            'columns': ['Date', 'Total Sales', 'Tax Amount', 'Net Amount', 'Transactions', 'Avg Sale'],
            'total_count': len(mock_data),
            'summary': {
                'total_sales': sum(row['total_sales'] for row in mock_data),
                'total_tax': sum(row['tax_amount'] for row in mock_data),
                'total_transactions': sum(row['transaction_count'] for row in mock_data)
            }
        }
    
    def _get_product_performance_data(self, filters: Dict, columns: List, limit: Optional[int]) -> Dict:
        """Get product performance data"""
        
        # Mock data - replace with actual product/sales queries
        mock_data = [
            {
                'product_name': 'Premium Coffee Beans',
                'quantity_sold': 125,
                'revenue': 3750.00,
                'profit_margin': 45.2,
                'category': 'Beverages',
                'cost_of_goods': 2062.50
            },
            {
                'product_name': 'Organic Tea Bags',
                'quantity_sold': 89,
                'revenue': 1780.00,
                'profit_margin': 38.5,
                'category': 'Beverages',
                'cost_of_goods': 1095.30
            },
            # Add more mock data...
        ]
        
        if limit:
            mock_data = mock_data[:limit]
        
        return {
            'rows': mock_data,
            'columns': ['Product', 'Qty Sold', 'Revenue', 'Profit %', 'Category', 'COGS'],
            'total_count': len(mock_data)
        }
    
    def _get_inventory_status_data(self, filters: Dict, columns: List, limit: Optional[int]) -> Dict:
        """Get inventory status data"""
        
        # Mock data - replace with actual inventory queries
        mock_data = [
            {
                'product_name': 'Premium Coffee Beans',
                'current_stock': 245,
                'reorder_level': 50,
                'last_updated': '2024-01-15 10:30:00',
                'stock_value': 4900.00,
                'supplier': 'Coffee Direct Ltd'
            },
            # Add more mock data...
        ]
        
        if limit:
            mock_data = mock_data[:limit]
        
        return {
            'rows': mock_data,
            'columns': ['Product', 'Stock', 'Reorder Level', 'Last Updated', 'Value', 'Supplier'],
            'total_count': len(mock_data)
        }
    
    def _get_tax_report_data(self, filters: Dict, columns: List, limit: Optional[int]) -> Dict:
        """Get tax report data"""
        
        # Mock data for tax transactions
        mock_data = [
            {
                'transaction_date': '2024-01-15',
                'invoice_number': 'INV-2024-001',
                'tax_type': 'VAT',
                'tax_rate': 18.0,
                'tax_amount': 324.50,
                'efris_code': 'EFR2024001234'
            },
            {
                'transaction_date': '2024-01-15',
                'invoice_number': 'INV-2024-002',
                'tax_type': 'VAT',
                'tax_rate': 18.0,
                'tax_amount': 180.00,
                'efris_code': 'EFR2024001235'
            },
            # Add more mock data...
        ]
        
        if limit:
            mock_data = mock_data[:limit]
        
        return {
            'rows': mock_data,
            'columns': ['Date', 'Invoice', 'Tax Type', 'Rate %', 'Amount', 'EFRIS Code'],
            'total_count': len(mock_data)
        }
    
    def _get_z_report_data(self, filters: Dict, columns: List, limit: Optional[int]) -> Dict:
        """Get Z report (end-of-day) data"""
        
        mock_data = [
            {
                'date': '2024-01-15',
                'opening_balance': 1500.00,
                'total_sales': 15420.50,
                'total_tax': 2313.08,
                'closing_balance': 16920.50,
                'cash_payments': 8500.00,
                'card_payments': 6920.50
            },
            # Add more mock data...
        ]
        
        if limit:
            mock_data = mock_data[:limit]
        
        return {
            'rows': mock_data,
            'columns': ['Date', 'Opening', 'Sales', 'Tax', 'Closing', 'Cash', 'Cards'],
            'total_count': len(mock_data)
        }
    
    def _get_efris_compliance_data(self, filters: Dict, columns: List, limit: Optional[int]) -> Dict:
        """Get EFRIS compliance data"""
        
        mock_data = [
            {
                'invoice_number': 'INV-2024-001',
                'efris_status': 'Verified',
                'verification_code': 'EFR2024001234',
                'submission_date': '2024-01-15 14:30:00',
                'error_message': None
            },
            {
                'invoice_number': 'INV-2024-002',
                'efris_status': 'Pending',
                'verification_code': None,
                'submission_date': '2024-01-15 15:00:00',
                'error_message': 'Network timeout - retrying'
            },
            # Add more mock data...
        ]
        
        if limit:
            mock_data = mock_data[:limit]
        
        return {
            'rows': mock_data,
            'columns': ['Invoice', 'Status', 'Verification Code', 'Submitted', 'Error'],
            'total_count': len(mock_data)
        }
    
    def _generate_pdf(self, include_charts: bool = True) -> str:
        """Generate PDF report using ReportLab"""
        
        filename = f"report_{self.saved_report.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        filepath = os.path.join(settings.MEDIA_ROOT, 'reports', filename)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Create PDF document
        doc = SimpleDocTemplate(filepath, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            textColor=colors.HexColor('#2563eb')
        )
        story.append(Paragraph(self.saved_report.name, title_style))
        
        # Report metadata
        meta_data = [
            ['Report Type:', self.saved_report.get_report_type_display()],
            ['Generated By:', self.user.get_full_name() or self.user.username],
            ['Generated On:', datetime.now().strftime('%B %d, %Y at %I:%M %p')],
        ]
        
        meta_table = Table(meta_data, colWidths=[2*inch, 4*inch])
        meta_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.grey),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        
        story.append(meta_table)
        story.append(Spacer(1, 20))
        
        # Data table
        if self.data and self.data['rows']:
            # Prepare table data
            table_data = [self.data['columns']]  # Header row
            
            for row in self.data['rows']:
                table_data.append([str(value) for value in row.values()])
            
            # Create table
            data_table = Table(table_data)
            data_table.setStyle(TableStyle([
                # Header styling
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                
                # Data styling
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
            ]))
            
            story.append(data_table)
        
        # Summary section (if available)
        if self.data and 'summary' in self.data:
            story.append(Spacer(1, 20))
            story.append(Paragraph("Summary", styles['Heading2']))
            
            summary_data = []
            for key, value in self.data['summary'].items():
                summary_data.append([key.replace('_', ' ').title() + ':', f"{value:,.2f}" if isinstance(value, (int, float)) else str(value)])
            
            summary_table = Table(summary_data, colWidths=[2*inch, 2*inch])
            summary_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 11),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f1f5f9')),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ]))
            
            story.append(summary_table)
        
        # Build PDF
        doc.build(story)
        
        return filepath
    
    def _generate_excel(self, include_charts: bool = True) -> str:
        """Generate Excel report using pandas and openpyxl"""
        
        filename = f"report_{self.saved_report.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        filepath = os.path.join(settings.MEDIA_ROOT, 'reports', filename)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Create DataFrame
        if self.data and self.data['rows']:
            df = pd.DataFrame(self.data['rows'])
            
            # Write to Excel with formatting
            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                # Write main data
                df.to_excel(writer, sheet_name='Report Data', index=False)
                
                # Get workbook and worksheet
                workbook = writer.book
                worksheet = writer.sheets['Report Data']
                
                # Format header row
                from openpyxl.styles import Font, PatternFill, Alignment
                
                header_font = Font(bold=True, color='FFFFFF')
                header_fill = PatternFill(start_color='2563eb', end_color='2563eb', fill_type='solid')
                header_alignment = Alignment(horizontal='center', vertical='center')
                
                for cell in worksheet[1]:
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = header_alignment
                
                # Auto-adjust column widths
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width
                
                # Add summary sheet if available
                if 'summary' in self.data:
                    summary_df = pd.DataFrame(list(self.data['summary'].items()), 
                                            columns=['Metric', 'Value'])
                    summary_df.to_excel(writer, sheet_name='Summary', index=False)
        
        return filepath
    
    def _generate_csv(self) -> str:
        """Generate CSV report"""
        
        filename = f"report_{self.saved_report.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = os.path.join(settings.MEDIA_ROOT, 'reports', filename)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        if self.data and self.data['rows']:
            df = pd.DataFrame(self.data['rows'])
            df.to_csv(filepath, index=False)
        
        return filepath
    
    def _generate_json(self) -> str:
        """Generate JSON report"""
        
        filename = f"report_{self.saved_report.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(settings.MEDIA_ROOT, 'reports', filename)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Prepare JSON data
        json_data = {
            'report_metadata': {
                'name': self.saved_report.name,
                'type': self.saved_report.report_type,
                'generated_by': self.user.username,
                'generated_at': datetime.now().isoformat(),
                'filters': self.saved_report.filters,
                'columns': self.saved_report.columns
            },
            'data': self.data
        }
        
        with open(filepath, 'w') as f:
            json.dump(json_data, f, indent=2, default=str)
        
        return filepath
    
    def _get_content_type(self, file_format: str) -> str:
        """Get MIME content type for file format"""
        
        content_types = {
            'PDF': 'application/pdf',
            'XLSX': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'CSV': 'text/csv',
            'JSON': 'application/json'
        }
        
        return content_types.get(file_format.upper(), 'application/octet-stream')


class EFRISIntegration:
    """Integration with Uganda Revenue Authority EFRIS system"""
    
    def __init__(self):
        self.base_url = getattr(settings, 'EFRIS_API_URL', 'https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation')
        self.api_key = getattr(settings, 'EFRIS_API_KEY', '')
        self.timeout = 30
    
    def verify_report(self, generated_report: GeneratedReport) -> Dict[str, Any]:
        """Submit report to EFRIS for verification"""
        
        try:
            # Prepare verification payload
            payload = {
                'report_type': generated_report.report.report_type,
                'report_data': self._prepare_efris_data(generated_report),
                'business_tin': getattr(settings, 'BUSINESS_TIN', ''),
                'generated_at': generated_report.generated_at.isoformat(),
                'checksum': self._calculate_checksum(generated_report)
            }
            
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
                'X-API-Version': '1.0'
            }
            
            # Submit to EFRIS
            response = requests.post(
                f"{self.base_url}/reports/verify",
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                return {
                    'success': True,
                    'code': result.get('verification_code'),
                    'message': result.get('message', 'Report verified successfully')
                }
            else:
                error_msg = response.json().get('error', f'HTTP {response.status_code}')
                logger.error(f"EFRIS verification failed: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg
                }
                
        except requests.exceptions.RequestException as e:
            logger.error(f"EFRIS connection error: {str(e)}")
            return {
                'success': False,
                'error': 'Connection to EFRIS failed. Please try again later.'
            }
        except Exception as e:
            logger.error(f"EFRIS verification error: {str(e)}")
            return {
                'success': False,
                'error': 'Verification failed due to technical error.'
            }
    
    def _prepare_efris_data(self, generated_report: GeneratedReport) -> Dict[str, Any]:
        """Prepare report data in EFRIS format"""
        
        # This would convert your report data to EFRIS-required format
        # The exact format depends on URA specifications
        
        return {
            'report_id': generated_report.id,
            'business_tin': getattr(settings, 'BUSINESS_TIN', ''),
            'period_start': generated_report.report.filters.get('date_from'),
            'period_end': generated_report.report.filters.get('date_to'),
            'currency': 'UGX',
            'total_transactions': 0,  # Calculate from actual data
            'total_tax_amount': 0,    # Calculate from actual data
            'total_gross_amount': 0,  # Calculate from actual data
        }
    
    def _calculate_checksum(self, generated_report: GeneratedReport) -> str:
        """Calculate data integrity checksum"""
        
        import hashlib
        
        # Create checksum from report data
        data_string = f"{generated_report.id}{generated_report.generated_at}{generated_report.file_path}"
        return hashlib.sha256(data_string.encode()).hexdigest()
    
    def get_compliance_status(self, business_tin: str) -> Dict[str, Any]:
        """Get overall EFRIS compliance status"""
        
        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            
            response = requests.get(
                f"{self.base_url}/compliance/status/{business_tin}",
                headers=headers,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {'success': False, 'error': 'Failed to get compliance status'}
                
        except Exception as e:
            logger.error(f"EFRIS compliance check error: {str(e)}")
            return {'success': False, 'error': str(e)}


class ReportScheduler:
    """Utility for managing and executing report schedules"""
    
    @staticmethod
    def execute_scheduled_reports():
        """Execute all due scheduled reports - call this from management command or Celery task"""
        
        from django.utils import timezone
        from .models import ReportSchedule
        
        due_schedules = ReportSchedule.objects.filter(
            is_active=True,
            next_scheduled__lte=timezone.now()
        )
        
        for schedule in due_schedules:
            try:
                ReportScheduler._execute_schedule(schedule)
                ReportScheduler._update_next_scheduled(schedule)
                logger.info(f"Executed scheduled report: {schedule.report.name}")
                
            except Exception as e:
                logger.error(f"Failed to execute schedule {schedule.id}: {str(e)}")
    
    @staticmethod
    def _execute_schedule(schedule):
        """Execute a single schedule"""
        
        # Generate report
        generator = ReportGenerator(schedule.report, None)  # System user
        generated_report = generator.generate(
            file_format='PDF',  # Default format for scheduled reports
            include_charts=True,
            efris_verify=schedule.include_efris
        )
        
        # Email to recipients
        recipients = [email.strip() for email in schedule.recipients.split(',')]
        if schedule.cc_recipients:
            cc_recipients = [email.strip() for email in schedule.cc_recipients.split(',')]
            recipients.extend(cc_recipients)
        
        generator.email_report(generated_report, recipients)
        
        # Update last sent
        from django.utils import timezone
        schedule.last_sent = timezone.now()
        schedule.save(update_fields=['last_sent'])
    
    @staticmethod
    def _update_next_scheduled(schedule):
        """Calculate and update next scheduled run time"""
        
        from django.utils import timezone
        from dateutil.relativedelta import relativedelta
        
        now = timezone.now()
        
        if schedule.frequency == 'DAILY':
            next_run = now + timedelta(days=1)
        elif schedule.frequency == 'WEEKLY':
            days_ahead = schedule.day_of_week - now.weekday()
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            next_run = now + timedelta(days=days_ahead)
        elif schedule.frequency == 'MONTHLY':
            next_run = now.replace(day=schedule.day_of_month)
            if next_run <= now:
                next_run = next_run + relativedelta(months=1)
        elif schedule.frequency == 'QUARTERLY':
            next_run = now + relativedelta(months=3)
        elif schedule.frequency == 'YEARLY':
            next_run = now + relativedelta(years=1)
        else:
            next_run = now + timedelta(days=1)  # Default fallback
        
        schedule.next_scheduled = next_run
        schedule.save(update_fields=['next_scheduled'])