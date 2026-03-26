"""
Legal views — add these to public_router/views.py
Also copy terms_of_service.pdf and privacy_policy.pdf into:
    public_router/static/public_router/legal/
"""

import datetime
import os
from django.shortcuts import render
from django.http import FileResponse, Http404
from django.conf import settings


def terms_view(request):
    """Terms of Service page."""
    return render(request, 'public_router/terms.html', {
        'title': 'Terms of Service — Primebooks',
        'effective_date': 'March 2025',
    })


def privacy_view(request):
    """Privacy Policy page."""
    return render(request, 'public_router/privacy.html', {
        'title': 'Privacy Policy — Primebooks',
        'effective_date': 'March 2025',
    })


def terms_pdf_view(request):
    """Serve the Terms of Service PDF for download."""
    pdf_path = os.path.join(
        settings.BASE_DIR,
        'public_router', 'static', 'public_router', 'legal', 'terms_of_service.pdf'
    )
    if not os.path.exists(pdf_path):
        raise Http404("PDF not found.")
    return FileResponse(
        open(pdf_path, 'rb'),
        content_type='application/pdf',
        as_attachment=True,
        filename='Primebooks_Terms_of_Service.pdf',
    )


def privacy_pdf_view(request):
    """Serve the Privacy Policy PDF for download."""
    pdf_path = os.path.join(
        settings.BASE_DIR,
        'public_router', 'static', 'public_router', 'legal', 'privacy_policy.pdf'
    )
    if not os.path.exists(pdf_path):
        raise Http404("PDF not found.")
    return FileResponse(
        open(pdf_path, 'rb'),
        content_type='application/pdf',
        as_attachment=True,
        filename='Primebooks_Privacy_Policy.pdf',
    )