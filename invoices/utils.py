import csv
import io
from django.http import HttpResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import qrcode
from django.conf import settings
from PIL import Image
import base64

def generate_invoice_pdf(invoice):
    """Generate PDF for a single invoice"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()
    
    # Company Header
    company_style = ParagraphStyle(
        'CompanyHeader',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=30,
        textColor=colors.darkblue
    )
    
    company_info = settings.INVOICE_SETTINGS['COMPANY_INFO']
    elements.append(Paragraph(company_info['name'], company_style))
    elements.append(Paragraph(f"{company_info['address']}<br/>{company_info['phone']}<br/>{company_info['email']}", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    # Invoice Header
    invoice_data = [
        ['Invoice Number:', invoice.invoice_number],
        ['Issue Date:', str(invoice.issue_date)],
        ['Due Date:', str(invoice.due_date)],
        ['Status:', invoice.get_status_display()],
    ]
    
    invoice_table = Table(invoice_data, colWidths=[2*inch, 3*inch])
    invoice_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    elements.append(invoice_table)
    elements.append(Spacer(1, 30))
    
    # Customer Information
    if invoice.sale and invoice.sale.customer:
        customer = invoice.sale.customer
        elements.append(Paragraph('Bill To:', styles['Heading2']))
        customer_info = f"{customer.name}<br/>{customer.address}<br/>{customer.phone}<br/>{customer.email}"
        elements.append(Paragraph(customer_info, styles['Normal']))
        elements.append(Spacer(1, 20))
    
    # Line Items
    line_data = [['Description', 'Qty', 'Unit Price', 'Total']]
    
    for item in invoice.sale.items.all():
        line_data.append([
            item.product.name,
            str(item.quantity),
            f"UGX {item.unit_price:,.2f}",
            f"UGX {item.total_price:,.2f}"
        ])
    
    # Totals
    line_data.extend([
        ['', '', 'Subtotal:', f"UGX {invoice.subtotal:,.2f}"],
        ['', '', 'Tax:', f"UGX {invoice.tax_amount:,.2f}"],
        ['', '', 'Discount:', f"-UGX {invoice.discount_amount:,.2f}"],
        ['', '', 'Total:', f"UGX {invoice.total_amount:,.2f}"],
    ])
    
    line_table = Table(line_data, colWidths=[3*inch, 1*inch, 1.5*inch, 1.5*inch])
    line_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, -4), (-1, -1), colors.beige),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    elements.append(line_table)
    
    # Fiscalization Info
    if invoice.is_fiscalized:
        elements.append(Spacer(1, 30))
        elements.append(Paragraph('URA EFRIS Fiscalization', styles['Heading2']))
        fisc_data = [
            ['Fiscal Number:', invoice.fiscal_number],
            ['Verification Code:', invoice.verification_code],
            ['Fiscalization Date:', str(invoice.fiscalization_time)],
        ]
        
        fisc_table = Table(fisc_data, colWidths=[2*inch, 4*inch])
        fisc_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(fisc_table)
    
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf


def export_invoices_csv(queryset):
    """Export invoice queryset to CSV"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="invoices.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Invoice Number', 'Document Type', 'Customer', 'Issue Date', 'Due Date',
        'Status', 'Subtotal', 'Tax', 'Discount', 'Total', 'Amount Paid',
        'Outstanding', 'Is Overdue', 'Fiscalized', 'Created By'
    ])
    
    for invoice in queryset:
        writer.writerow([
            invoice.invoice_number,
            invoice.get_document_type_display(),
            invoice.sale.customer.name if invoice.sale and invoice.sale.customer else '',
            invoice.issue_date,
            invoice.due_date,
            invoice.get_status_display(),
            invoice.subtotal,
            invoice.tax_amount,
            invoice.discount_amount,
            invoice.total_amount,
            invoice.amount_paid,
            invoice.amount_outstanding,
            invoice.is_overdue,
            invoice.is_fiscalized,
            invoice.created_by.username if invoice.created_by else ''
        ])
    
    return response


def generate_qr_code(data):
    """Generate QR code for invoice"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    
    return base64.b64encode(buffer.getvalue()).decode()

