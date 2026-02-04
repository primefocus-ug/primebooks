# invoices/api_views.py
"""
REST API Views for Invoices Application
"""

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Sum, Count, Avg
from django.utils import timezone
from django.shortcuts import get_object_or_404
from decimal import Decimal
from datetime import datetime, timedelta
import logging

from .models import Invoice, InvoicePayment, InvoiceTemplate
from .serializers import (
    InvoiceListSerializer,
    InvoiceDetailSerializer,
    InvoiceCreateSerializer,
    InvoiceUpdateSerializer,
    InvoiceFiscalizationSerializer,
    InvoicePaymentSerializer,
    InvoiceTemplateSerializer,
    InvoiceStatsSerializer,
    BulkFiscalizationSerializer
)
from stores.models import Store
from stores.utils import validate_store_access, get_user_accessible_stores

logger = logging.getLogger(__name__)


class StandardResultsSetPagination(PageNumberPagination):
    """Standard pagination for list views"""
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100


class InvoiceViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing invoices

    Provides:
    - list: Get all invoices with filtering
    - retrieve: Get specific invoice details
    - create: Create new invoice
    - update/partial_update: Modify existing invoice
    - destroy: Delete invoice (only non-fiscalized)
    - fiscalize: Send invoice to EFRIS
    - add_payment: Add payment to invoice
    - stats: Get invoice statistics
    """
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_fiscalized', 'business_type', 'efris_document_type', 'fiscalization_status']
    search_fields = ['invoice_number', 'fiscal_document_number', 'sale__customer__name']
    ordering_fields = ['created_at', 'issue_date', 'due_date', 'total_amount']
    ordering = ['-created_at']

    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.action == 'list':
            return InvoiceListSerializer
        elif self.action in ['create']:
            return InvoiceCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return InvoiceUpdateSerializer
        return InvoiceDetailSerializer

    def get_queryset(self):
        """Filter invoices by user's accessible stores"""
        user = self.request.user
        accessible_stores = get_user_accessible_stores(user)

        queryset = Invoice.objects.filter(
            sale__store__in=accessible_stores
        ).select_related(
            'sale', 'sale__store', 'sale__customer', 'created_by', 'fiscalized_by'
        ).prefetch_related('payments')

        # Additional filters
        payment_status = self.request.query_params.get('payment_status')
        if payment_status == 'PAID':
            queryset = queryset.filter(amount_outstanding__lte=0)
        elif payment_status == 'PENDING':
            queryset = queryset.filter(amount_outstanding__gt=0, due_date__gte=timezone.now().date())
        elif payment_status == 'OVERDUE':
            queryset = queryset.filter(amount_outstanding__gt=0, due_date__lt=timezone.now().date())

        # Date range filtering
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')

        if date_from:
            try:
                date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
                queryset = queryset.filter(issue_date__gte=date_from)
            except ValueError:
                pass

        if date_to:
            try:
                date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
                queryset = queryset.filter(issue_date__lte=date_to)
            except ValueError:
                pass

        return queryset

    def perform_create(self, serializer):
        """Set created_by to current user"""
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        """Only allow deletion of non-fiscalized invoices"""
        invoice = self.get_object()

        if invoice.is_fiscalized:
            return Response({
                'success': False,
                'error': 'Cannot delete fiscalized invoices'
            }, status=status.HTTP_400_BAD_REQUEST)

        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def fiscalize(self, request, pk=None):
        """
        Fiscalize an invoice (send to EFRIS)

        POST /api/v1/invoices/{id}/fiscalize/
        Body: {
            "confirm": true,
            "notes": "Optional notes"
        }
        """
        invoice = self.get_object()

        serializer = InvoiceFiscalizationSerializer(
            data=request.data,
            context={'invoice': invoice}
        )

        if not serializer.is_valid():
            return Response({
                'success': False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Queue fiscalization task
            from .tasks import fiscalize_invoice_async
            task_result = fiscalize_invoice_async.delay(invoice.pk, request.user.pk)

            return Response({
                'success': True,
                'message': f'Fiscalization queued for invoice {invoice.invoice_number}',
                'task_id': task_result.id
            }, status=status.HTTP_202_ACCEPTED)

        except ImportError:
            # Fallback to synchronous fiscalization if tasks not available
            try:
                from efris.services import EFRISInvoiceService
                service = EFRISInvoiceService(invoice.sale.store.company)
                success, message = service.fiscalize_invoice(invoice, request.user)

                if success:
                    return Response({
                        'success': True,
                        'message': 'Invoice fiscalized successfully',
                        'fiscal_document_number': invoice.fiscal_document_number
                    })
                else:
                    return Response({
                        'success': False,
                        'error': message
                    }, status=status.HTTP_400_BAD_REQUEST)

            except Exception as e:
                logger.error(f"Fiscalization error: {e}")
                return Response({
                    'success': False,
                    'error': 'Fiscalization service unavailable'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def add_payment(self, request, pk=None):
        """
        Add payment to invoice

        POST /api/v1/invoices/{id}/add_payment/
        Body: {
            "amount": 50000,
            "payment_method": "MOBILE_MONEY",
            "transaction_reference": "MM123456",
            "notes": "Payment received"
        }
        """
        invoice = self.get_object()

        # Add invoice to request data
        data = request.data.copy()
        data['invoice'] = invoice.id
        data['processed_by'] = request.user.id

        serializer = InvoicePaymentSerializer(data=data)

        if not serializer.is_valid():
            return Response({
                'success': False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        # Check if payment exceeds outstanding amount
        amount = serializer.validated_data['amount']
        if amount > invoice.amount_outstanding:
            return Response({
                'success': False,
                'error': f'Payment amount ({amount}) exceeds outstanding amount ({invoice.amount_outstanding})'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            payment = serializer.save(processed_by=request.user)

            # Update sale payment status
            invoice.sale.update_payment_status()

            return Response({
                'success': True,
                'message': 'Payment added successfully',
                'payment': InvoicePaymentSerializer(payment).data,
                'remaining_balance': invoice.amount_outstanding
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Error adding payment: {e}")
            return Response({
                'success': False,
                'error': 'Failed to add payment'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def stats(self, request):
        """
        Get invoice statistics

        GET /api/v1/invoices/stats/?date_from=2024-01-01&date_to=2024-01-31
        """
        try:
            date_from = request.query_params.get('date_from')
            date_to = request.query_params.get('date_to')

            if not date_from:
                date_from = timezone.now().date() - timedelta(days=30)
            else:
                date_from = datetime.strptime(date_from, '%Y-%m-%d').date()

            if not date_to:
                date_to = timezone.now().date()
            else:
                date_to = datetime.strptime(date_to, '%Y-%m-%d').date()

            queryset = self.get_queryset().filter(
                issue_date__gte=date_from,
                issue_date__lte=date_to
            )

            total_invoices = queryset.count()
            total_amount = queryset.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0')
            pending_amount = queryset.filter(amount_outstanding__gt=0).aggregate(
                Sum('amount_outstanding')
            )['amount_outstanding__sum'] or Decimal('0')

            overdue_count = queryset.filter(
                amount_outstanding__gt=0,
                due_date__lt=timezone.now().date()
            ).count()

            fiscalized_count = queryset.filter(is_fiscalized=True).count()

            fiscalization_rate = (fiscalized_count / total_invoices * 100) if total_invoices > 0 else 0
            collection_rate = ((total_amount - pending_amount) / total_amount * 100) if total_amount > 0 else 0
            avg_invoice_amount = queryset.aggregate(Avg('total_amount'))['total_amount__avg'] or Decimal('0')

            stats_data = {
                'total_invoices': total_invoices,
                'total_amount': total_amount,
                'pending_amount': pending_amount,
                'overdue_count': overdue_count,
                'fiscalized_count': fiscalized_count,
                'fiscalization_rate': round(fiscalization_rate, 2),
                'collection_rate': round(collection_rate, 2),
                'avg_invoice_amount': avg_invoice_amount
            }

            serializer = InvoiceStatsSerializer(data=stats_data)
            serializer.is_valid(raise_exception=True)

            return Response({
                'success': True,
                'period': {
                    'from': date_from,
                    'to': date_to
                },
                'stats': serializer.data
            })

        except Exception as e:
            logger.error(f"Error generating stats: {e}")
            return Response({
                'success': False,
                'error': 'Failed to generate statistics'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def bulk_fiscalize(self, request):
        """
        Bulk fiscalize invoices

        POST /api/v1/invoices/bulk_fiscalize/
        Body: {
            "invoice_ids": [1, 2, 3],
            "confirm": true
        }
        """
        serializer = BulkFiscalizationSerializer(data=request.data)

        if not serializer.is_valid():
            return Response({
                'success': False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        invoice_ids = serializer.validated_data['invoice_ids']

        # Get invoices
        invoices = self.get_queryset().filter(id__in=invoice_ids)

        # Check which can be fiscalized
        fiscalizable = []
        errors = []

        for invoice in invoices:
            can_fiscalize, message = invoice.can_fiscalize()
            if can_fiscalize:
                fiscalizable.append(invoice)
            else:
                errors.append({
                    'invoice_id': invoice.id,
                    'invoice_number': invoice.invoice_number,
                    'error': message
                })

        if not fiscalizable:
            return Response({
                'success': False,
                'error': 'No invoices can be fiscalized',
                'errors': errors
            }, status=status.HTTP_400_BAD_REQUEST)

        # Queue fiscalization tasks
        try:
            from .tasks import fiscalize_invoice_async

            task_ids = []
            for invoice in fiscalizable:
                task_result = fiscalize_invoice_async.delay(invoice.pk, request.user.pk)
                task_ids.append({
                    'invoice_id': invoice.id,
                    'invoice_number': invoice.invoice_number,
                    'task_id': task_result.id
                })

            return Response({
                'success': True,
                'message': f'{len(fiscalizable)} invoices queued for fiscalization',
                'queued': task_ids,
                'errors': errors
            }, status=status.HTTP_202_ACCEPTED)

        except Exception as e:
            logger.error(f"Bulk fiscalization error: {e}")
            return Response({
                'success': False,
                'error': 'Failed to queue bulk fiscalization'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def overdue(self, request):
        from django.db.models import F, ExpressionWrapper, DecimalField
        """
        Get overdue invoices

        GET /api/v1/invoices/overdue/
        """
        queryset = self.get_queryset().annotate(
            # Sum all payments related to this invoice
            total_paid=Sum('payments__amount')
        ).annotate(
            # Compute outstanding from related sale total_amount minus total_paid
            amount_outstanding_calc=ExpressionWrapper(
                F('sale__total_amount') - F('total_paid'),
                output_field=DecimalField(max_digits=12, decimal_places=2)
            )
        ).filter(
            amount_outstanding_calc__gt=0,  # unpaid invoices
            sale__due_date__lt=timezone.now().date()  # overdue by due_date on sale
        )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = InvoiceListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = InvoiceListSerializer(queryset, many=True)
        return Response({
            'success': True,
            'invoices': serializer.data
        })


class InvoicePaymentViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing invoice payments
    """
    serializer_class = InvoicePaymentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['invoice', 'payment_method']
    ordering_fields = ['created_at', 'payment_date', 'amount']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        accessible_stores = get_user_accessible_stores(user)

        return InvoicePayment.objects.filter(
            invoice__sale__store__in=accessible_stores
        ).select_related('invoice', 'processed_by')

    def perform_create(self, serializer):
        """Set processed_by to current user"""
        serializer.save(processed_by=self.request.user)


class InvoiceTemplateViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing invoice templates
    """
    serializer_class = InvoiceTemplateSerializer
    permission_classes = [IsAuthenticated]
    queryset = InvoiceTemplate.objects.all()

    def perform_create(self, serializer):
        """Set created_by to current user"""
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def set_default(self, request, pk=None):
        """Set template as default"""
        template = self.get_object()

        # Remove default from all other templates
        InvoiceTemplate.objects.filter(is_default=True).update(is_default=False)

        # Set this as default
        template.is_default = True
        template.save()

        return Response({
            'success': True,
            'message': f'Template "{template.name}" set as default'
        })