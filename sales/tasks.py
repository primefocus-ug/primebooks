from celery import shared_task
from .models import Sale
from django.conf import settings
from django.utils import timezone
from django.core.mail import send_mail
from django.db import connection, transaction
import logging
import uuid
from django_tenants.utils import tenant_context, schema_context, get_tenant_model
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from invoices.models import Invoice
from efris.services import EFRISInvoiceService, create_efris_service
from efris.models import EFRISAPILog, FiscalizationAudit

logger = logging.getLogger(__name__)


class TenantResolver:
    @staticmethod
    def get_current_schema():
        try:
            return connection.schema_name
        except AttributeError:
            try:
                return getattr(connection, 'schema_name', None)
            except Exception:
                return None

    @staticmethod
    def get_all_tenant_schemas():
        current_schema = TenantResolver.get_current_schema()

        try:
            with schema_context('public'):
                tenant_model = get_tenant_model()
                schemas = list(tenant_model.objects.exclude(
                    schema_name='public'
                ).values_list('schema_name', flat=True))

            if current_schema and current_schema != 'public':
                try:
                    connection.set_schema(current_schema)
                except Exception as restore_error:
                    logger.warning(f"Could not restore schema {current_schema}: {restore_error}")

            logger.debug(f"Found {len(schemas)} tenant schemas (current: {current_schema})")
            return schemas

        except Exception as e:
            logger.error(f"Error getting tenant schemas: {e}", exc_info=True)
            return []

    @staticmethod
    def find_sale_schema(sale_id):
        """Find the tenant schema for a sale — last resort, prefer passing schema_name explicitly."""
        current_schema = TenantResolver.get_current_schema()
        schemas = TenantResolver.get_all_tenant_schemas()

        if current_schema and current_schema != 'public':
            try:
                with schema_context(current_schema):
                    sale = Sale.objects.select_related(
                        'store__company', 'created_by', 'customer'
                    ).prefetch_related('items').get(id=sale_id)
                    logger.info(f"Found sale {sale_id} in current schema: {current_schema}")
                    return sale, current_schema
            except Sale.DoesNotExist:
                logger.debug(f"Sale {sale_id} not in current schema {current_schema}, searching others")
            except Exception as e:
                logger.debug(f"Error checking current schema {current_schema} for sale {sale_id}: {e}")

        for schema_name in schemas:
            if schema_name == current_schema:
                continue

            try:
                with schema_context(schema_name):
                    sale = Sale.objects.select_related(
                        'store__company', 'created_by', 'customer'
                    ).prefetch_related('items').get(id=sale_id)
                    logger.info(f"Found sale {sale_id} in schema: {schema_name}")

                    if current_schema and current_schema != 'public':
                        try:
                            connection.set_schema(current_schema)
                        except Exception:
                            pass

                    return sale, schema_name
            except Sale.DoesNotExist:
                continue
            except Exception as e:
                logger.debug(f"Error checking schema {schema_name} for sale {sale_id}: {e}")
                continue

        logger.error(f"Sale {sale_id} not found in any tenant schema")

        if current_schema and current_schema != 'public':
            try:
                connection.set_schema(current_schema)
            except Exception:
                pass

        return None, None

    @staticmethod
    def resolve_company_from_sale(sale):
        if sale.store and hasattr(sale.store, 'company'):
            return sale.store.company
        return None


@shared_task(bind=True, max_retries=3, default_retry_delay=30, queue='critical')
def process_receipt_async(self, sale_id, user_id=None, schema_name=None):
    """
    Process receipt asynchronously — handles notifications and EFRIS only.

    DUPLICATE STOCK MOVEMENT FIX:
    Stock is already deducted synchronously by SaleItem.save() inside the
    atomic request transaction. This task must NEVER touch stock again.
    update_stock_for_receipt() has been removed from this task entirely.
    The idempotency guard in update_stock_for_receipt() was suppressing the
    duplicate with a WARNING, but the root cause was calling the function at
    all in a second code path. Removing the call eliminates both the duplicate
    StockMovement and the spurious warning.

    RACE CONDITION FIX:
    The signal now dispatches via transaction.on_commit(), so by the time this
    task executes the sale and all its items are guaranteed committed.

    SCHEMA FIX:
    schema_name is always passed by the signal, so the expensive full-schema
    scan (find_sale_schema) only runs as a last resort on legacy callers.
    """
    initial_schema = TenantResolver.get_current_schema()

    try:
        if schema_name:
            tenant_schema = schema_name
        else:
            _, tenant_schema = TenantResolver.find_sale_schema(sale_id)

        if not tenant_schema:
            logger.error(f"Receipt {sale_id} not found in any tenant schema")
            return {'success': False, 'message': 'Receipt not found'}

        with schema_context(tenant_schema):
            sale = Sale.objects.select_related(
                'store__company', 'customer', 'created_by'
            ).prefetch_related('items__product').get(id=sale_id)

            if sale.document_type != 'RECEIPT':
                return {
                    'success': False,
                    'message': f'Not a receipt: {sale.document_type}'
                }

            logger.info(f"Processing receipt {sale.document_number} in background")

            results = {
                'stock_updated': True,   # Already done synchronously by SaleItem.save()
                'notifications_sent': False,
                'efris_processed': False,
            }

            # 1. Send notifications
            try:
                send_receipt_notification.delay(sale_id, schema_name=tenant_schema)
                results['notifications_sent'] = True
            except Exception as e:
                logger.warning(f"Failed to queue receipt notification: {e}")

            # 2. Process EFRIS if enabled
            store_config = sale.store.effective_efris_config
            if (store_config.get('enabled', False) and
                    store_config.get('auto_fiscalize_receipts', False)):
                try:
                    fiscalize_invoice_async.delay(sale_id, user_id)
                    results['efris_processed'] = True
                except Exception as e:
                    logger.warning(f"Failed to queue receipt fiscalization: {e}")

            return {
                'success': True,
                'message': f'Receipt {sale.document_number} processed successfully',
                'results': results,
                'schema': tenant_schema
            }

    except Exception as e:
        logger.error(f"Error processing receipt {sale_id}: {e}", exc_info=True)
        return {'success': False, 'message': str(e)}

    finally:
        if initial_schema and initial_schema != 'public':
            try:
                connection.set_schema(initial_schema)
            except Exception:
                pass


@shared_task(bind=True, max_retries=3, queue='efris')
def fiscalize_export_invoice_async(self, sale_id, user_id, export_data, schema_name=None):
    """Asynchronously fiscalize an export invoice via EFRIS"""
    initial_schema = TenantResolver.get_current_schema()
    try:
        from django.contrib.auth import get_user_model

        sale, tenant_schema = TenantResolver.find_sale_schema(sale_id)
        if not sale or not tenant_schema:
            logger.error(f"Sale {sale_id} not found in any tenant schema for export fiscalization")
            return {'success': False, 'error': 'Sale not found'}

        with schema_context(tenant_schema):
            from sales.models import Sale as SaleModel
            User = get_user_model()
            sale = SaleModel.objects.select_related('store', 'customer').get(pk=sale_id)
            user = User.objects.get(pk=user_id)

            logger.info(f"Starting export fiscalization for sale {sale.document_number}")

            export_service = create_efris_service(
                sale.store.company,
                'export',
                sale.store
            )

            hs_codes = []
            for item in sale.items.filter(item_type='PRODUCT'):
                if item.product and hasattr(item.product, 'hs_code') and item.product.hs_code:
                    hs_codes.append(item.product.hs_code)

            if not hs_codes:
                raise Exception("No HS codes found on products. Configure products for export first.")

            result = export_service.fiscalize_export_sale(
                sale_or_invoice=sale,
                delivery_terms=export_data['delivery_terms'],
                hs_codes=hs_codes,
                total_weight=export_data['total_weight'],
                buyer_country=export_data['buyer_country'],
                buyer_passport=export_data.get('buyer_passport'),
                foreign_currency=export_data.get('foreign_currency'),
                exchange_rate=export_data.get('exchange_rate'),
                user=user
            )

            if result.get('success'):
                logger.info(f"Export invoice {sale.document_number} fiscalized successfully")
                return {
                    'success': True,
                    'invoice_no': result['data']['invoice_no'],
                    'fiscal_code': result['data'].get('fiscal_code')
                }
            else:
                logger.error(f"Export fiscalization failed: {result.get('error')}")
                raise Exception(result.get('error'))

    except Exception as e:
        logger.error(f"Export fiscalization task failed: {e}", exc_info=True)
        raise self.retry(exc=e, countdown=60)

    finally:
        if initial_schema and initial_schema != 'public':
            try:
                connection.set_schema(initial_schema)
            except Exception:
                pass


@shared_task(queue='default')
def send_receipt_notification(sale_id, schema_name=None):
    """
    Send receipt notifications asynchronously.

    Responsibilities:
      1. Customer receipt email (if email on file)
      2. WebSocket update for the open POS tab
      3. FCM push notification to all staff subscribed to 'sale_created'
         (belt-and-suspenders — the signal already calls notify_event() directly,
         but this task runs after transaction.on_commit() so the sale is
         guaranteed committed by the time FCM fires)
    """
    initial_schema = TenantResolver.get_current_schema()

    try:
        if schema_name:
            tenant_schema = schema_name
        else:
            _, tenant_schema = TenantResolver.find_sale_schema(sale_id)

        if not tenant_schema:
            return

        with schema_context(tenant_schema):
            sale = Sale.objects.select_related(
                'customer', 'created_by', 'store__company'
            ).get(id=sale_id)

            if sale.document_type != 'RECEIPT':
                return

            # ── 1. Customer receipt email ──────────────────────────────────────
            if sale.customer and sale.customer.email:
                try:
                    send_mail(
                        subject=f"Receipt {sale.document_number}",
                        message=(
                            f"Your receipt {sale.document_number} for "
                            f"{sale.total_amount} {sale.currency} has been processed."
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[sale.customer.email],
                        fail_silently=True
                    )
                    logger.info(f"Receipt email sent to {sale.customer.email}")
                except Exception as e:
                    logger.error(f"Failed to send receipt email: {e}")

            # ── 2. WebSocket update for the open POS tab ───────────────────────
            try:
                channel_layer = get_channel_layer()
                if channel_layer is None:
                    logger.debug(
                        "WebSocket channel layer not configured — "
                        "skipping receipt notification WS update"
                    )
                else:
                    async_to_sync(channel_layer.group_send)(
                        f'pos_{sale.store.id}',
                        {
                            'type': 'receipt.completed',
                            'data': {
                                'receipt_number': sale.document_number,
                                'customer': (
                                    sale.customer.name if sale.customer else 'Walk-in'
                                ),
                                'total': float(sale.total_amount),
                                'timestamp': timezone.now().isoformat()
                            }
                        }
                    )
            except Exception as e:
                logger.warning(f"Failed to send WebSocket notification: {e}")

            # ── 3. FCM push to all staff subscribed to 'sale_created' ──────────
            # notify_event() is schema-aware — it reads connection.schema_name,
            # which is already set to tenant_schema inside schema_context().
            # This is correct here (unlike in signals where we must call it
            # BEFORE schema_context). Inside a Celery task the connection starts
            # fresh, so schema_context() is the authoritative setter.
            try:
                from push_notifications.tasks import notify_event
                notify_event(
                    notification_type_code='sale_created',
                    title='New Sale 🛒',
                    body=(
                        f"Receipt {sale.document_number} — "
                        f"UGX {sale.total_amount:,.0f}"
                    ),
                    url=f"/sales/{sale.pk}/",
                )
                logger.info(
                    f"FCM push dispatched for receipt {sale.document_number} "
                    f"in schema '{tenant_schema}'"
                )
            except Exception as e:
                logger.warning(
                    f"FCM push failed for receipt {sale.pk} "
                    f"in schema '{tenant_schema}': {e}"
                )

    except Exception as e:
        logger.error(f"Error in send_receipt_notification: {e}")

    finally:
        if initial_schema and initial_schema != 'public':
            try:
                connection.set_schema(initial_schema)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# PRICE REDUCTION APPROVAL — email + FCM push to admins
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=30, queue='default')
def notify_admins_price_reduction(self, request_id, schema_name):
    """
    Fired when an employee with NOTIFY policy reduces an item price at POS.
    Sends:
      1. Email to every company_admin in the tenant
      2. FCM push via the existing notify_event() mechanism

    Args:
        request_id  : UUID string of the PriceReductionRequest
        schema_name : tenant schema_name (always passed by the signal/view)

    Follows the same schema / finally-restore pattern as every other task here.
    """
    initial_schema = TenantResolver.get_current_schema()

    try:
        with schema_context(schema_name):
            from sales.models import PriceReductionRequest
            from accounts.models import CustomUser

            # ── Load request ──────────────────────────────────────────────────
            try:
                req = PriceReductionRequest.objects.select_related(
                    'employee', 'store', 'store__company'
                ).get(id=request_id)
            except PriceReductionRequest.DoesNotExist:
                logger.warning(
                    f'notify_admins_price_reduction: request {request_id} '
                    f'not found in {schema_name} — skipping'
                )
                return {'success': False, 'reason': 'request_not_found'}

            if req.status != PriceReductionRequest.STATUS_PENDING:
                logger.info(
                    f'notify_admins_price_reduction: request {request_id} '
                    f'already {req.status} — skipping'
                )
                return {'success': False, 'reason': 'already_resolved'}

            # ── Get all active admins for this tenant ─────────────────────────
            admins = CustomUser.objects.filter(
                company=req.store.company,
                company_admin=True,
                is_active=True,
                is_hidden=False,
            )

            if not admins.exists():
                logger.warning(
                    f'notify_admins_price_reduction: no admins for '
                    f'{req.store.company.name} — skipping notify'
                )
                return {'success': False, 'reason': 'no_admins'}

            company     = req.store.company
            employee    = req.employee
            store       = req.store
            base_url    = getattr(settings, 'FRONTEND_URL', 'https://primebooks.sale')
            approve_url = f'{base_url}/sales/price-reduction-requests/{req.id}/approve/?token={req.id}'
            reject_url  = f'{base_url}/sales/price-reduction-requests/{req.id}/reject/?token={req.id}'

            # ── 1. Email ──────────────────────────────────────────────────────
            email_sent = False
            try:
                recipient_list = list(admins.values_list('email', flat=True))

                subject = (
                    f'[{company.name}] Price reduction needs approval — '
                    f'{req.item_name} ({req.reduction_pct}% off)'
                )

                text_body = (
                    f'Price Reduction Approval Request\n'
                    f'{"=" * 45}\n\n'
                    f'Employee  : {employee.get_full_name() or employee.email}\n'
                    f'Store     : {store.name}\n'
                    f'Item      : {req.item_name}\n'
                    f'Original  : {req.original_price}\n'
                    f'Requested : {req.requested_price} '
                    f'({req.reduction_pct}% reduction, saves {req.reduction_amount})\n'
                    f'Quantity  : {req.quantity}\n'
                    f'Note      : {req.employee_note or "None"}\n\n'
                    f'APPROVE : {approve_url}\n'
                    f'REJECT  : {reject_url}\n\n'
                    f'This request expires in 30 minutes.\n'
                    f'The employee can continue adding other items while waiting.'
                )

                # HTML template — optional, falls back silently to plain text
                html_body = None
                try:
                    from django.template.loader import render_to_string
                    html_body = render_to_string(
                        'sales/emails/price_reduction_request.html',
                        {
                            'req':         req,
                            'approve_url': approve_url,
                            'reject_url':  reject_url,
                            'company':     company,
                        }
                    )
                except Exception:
                    pass  # No template yet — plain text is fine

                send_mail(
                    subject=subject,
                    message=text_body,
                    html_message=html_body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=recipient_list,
                    fail_silently=False,
                )
                email_sent = True
                logger.info(
                    f'Price reduction email sent to {recipient_list} '
                    f'for request {req.id} in {schema_name}'
                )
            except Exception as e:
                logger.error(
                    f'Price reduction email failed for request {req.id}: {e}',
                    exc_info=True
                )

            # ── 2. FCM push via notify_event ──────────────────────────────────
            # notify_event() reads connection.schema_name internally.
            # We are already inside schema_context(schema_name) so this is
            # correct — the connection is on the right schema (unlike signals
            # where notify_event must be called BEFORE schema_context).
            push_sent = False
            try:
                from push_notifications.tasks import notify_event
                notify_event(
                    notification_type_code='sale_created',   # broadest admin-visible type
                    title=f'Price approval needed — {store.name}',
                    body=(
                        f'{employee.get_full_name() or employee.email} wants to sell '
                        f'{req.item_name} at {req.requested_price} '
                        f'(was {req.original_price}, {req.reduction_pct}% off)'
                    ),
                    url=f'/sales/price-reduction-requests/?status=PENDING',
                )
                push_sent = True
                logger.info(
                    f'FCM push dispatched for price reduction request {req.id} '
                    f'in schema {schema_name}'
                )
            except Exception as e:
                logger.warning(
                    f'FCM push failed for price reduction request {req.id}: {e}'
                )

            # ── Update sent flags ─────────────────────────────────────────────
            update_fields = ['updated_at']
            if email_sent:
                req.email_sent = True
                update_fields.append('email_sent')
            if push_sent:
                req.push_sent = True
                update_fields.append('push_sent')
            req.save(update_fields=update_fields)

            return {
                'success':    True,
                'email_sent': email_sent,
                'push_sent':  push_sent,
                'schema':     schema_name,
            }

    except Exception as exc:
        logger.error(
            f'notify_admins_price_reduction failed for request {request_id} '
            f'in {schema_name}: {exc}',
            exc_info=True
        )
        raise self.retry(exc=exc)

    finally:
        if initial_schema and initial_schema != 'public':
            try:
                connection.set_schema(initial_schema)
            except Exception:
                pass


@shared_task(queue='default')
def expire_stale_price_reduction_requests():
    """
    Expire PENDING PriceReductionRequests older than 30 minutes.
    Registered in CELERY_BEAT_SCHEDULE — runs every 5 minutes.
    Loops all tenant schemas using the same TenantResolver pattern.
    """
    cutoff = timezone.now() - timezone.timedelta(minutes=30)
    schemas = TenantResolver.get_all_tenant_schemas()
    total_expired = 0

    for schema in schemas:
        try:
            with schema_context(schema):
                from sales.models import PriceReductionRequest
                stale = PriceReductionRequest.objects.filter(
                    status=PriceReductionRequest.STATUS_PENDING,
                    created_at__lt=cutoff,
                )
                for req in stale:
                    try:
                        req.expire()
                        total_expired += 1
                        logger.info(
                            f'Expired price reduction request {req.id} '
                            f'({req.item_name}) in {schema}'
                        )
                    except Exception as e:
                        logger.error(
                            f'Failed to expire request {req.id} in {schema}: {e}'
                        )
        except Exception as e:
            logger.error(
                f'expire_stale_price_reduction_requests: error in {schema}: {e}'
            )

    logger.info(f'Expired {total_expired} stale price reduction requests across all tenants')
    return {'expired': total_expired}


@shared_task(bind=True)
def create_sale_background(self, form_data, user_id, task_id):
    """
    Create sale in background with progress updates and export sale support.
    """
    initial_schema = TenantResolver.get_current_schema()

    try:
        from django.contrib.auth import get_user_model
        from stores.models import Store
        from django.db import transaction
        from decimal import Decimal
        from inventory.models import Product, Service
        from sales.models import SaleItem, Payment
        from .signals import send_receipt_ws_update
        from .views import create_stock_movements
        import json

        User = get_user_model()

        user, user_schema = TenantResolver.find_user_schema(user_id)
        if not user or not user_schema:
            return {'success': False, 'error': 'User not found'}

        with schema_context(user_schema):
            update_task_progress(task_id, 20, 'Validating data...')

            company = get_current_tenant_from_user(user)

            update_task_progress(task_id, 30, 'Validating store and items...')

            try:
                store = Store.objects.get(
                    id=form_data['store'],
                    company=company,
                    is_active=True
                )
            except Store.DoesNotExist:
                update_task_progress(task_id, 100, 'Error: Invalid store', 'error')
                return {'success': False, 'error': 'Invalid store'}

            try:
                items_data = json.loads(form_data.get('items_data', '[]'))
                if not items_data:
                    update_task_progress(task_id, 100, 'Error: No items', 'error')
                    return {'success': False, 'error': 'No items'}
            except json.JSONDecodeError:
                update_task_progress(task_id, 100, 'Error: Invalid items data', 'error')
                return {'success': False, 'error': 'Invalid items data'}

            is_export_sale = form_data.get('is_export_sale') == 'true'

            update_task_progress(task_id, 40, 'Creating sale record...')

            with transaction.atomic():
                sale = Sale.objects.create(
                    store=store,
                    created_by=user,
                    customer_id=form_data.get('customer') if form_data.get('customer') else None,
                    document_type=form_data.get('document_type', 'RECEIPT'),
                    payment_method=form_data.get('payment_method', 'CASH'),
                    currency='UGX',
                    discount_amount=Decimal(form_data.get('discount_amount', '0')),
                    notes=form_data.get('notes', ''),
                    due_date=form_data.get('due_date'),
                    status='DRAFT',
                )

                update_task_progress(task_id, 50, 'Adding items to sale...')

                for item_data in items_data:
                    try:
                        item_type = item_data.get('item_type', 'PRODUCT')

                        export_fields = {}
                        if is_export_sale:
                            export_fields = {
                                'export_total_weight': Decimal(str(item_data['export_total_weight'])) if item_data.get('export_total_weight') else None,
                                'export_piece_qty': int(item_data['export_piece_qty']) if item_data.get('export_piece_qty') else None,
                                'export_piece_measure_unit': item_data.get('export_piece_measure_unit', ''),
                            }

                        if item_type == 'PRODUCT':
                            product = Product.objects.get(id=item_data['product_id'], is_active=True)
                            SaleItem.objects.create(
                                sale=sale,
                                item_type='PRODUCT',
                                product=product,
                                quantity=Decimal(str(item_data.get('quantity', 1))),
                                unit_price=Decimal(str(item_data.get('unit_price', 0))),
                                tax_rate=item_data.get('tax_rate', 'A'),
                                discount=Decimal(str(item_data.get('discount', 0))),
                                **export_fields
                            )
                        elif item_type == 'SERVICE':
                            service = Service.objects.get(id=item_data['service_id'], is_active=True)
                            SaleItem.objects.create(
                                sale=sale,
                                item_type='SERVICE',
                                service=service,
                                quantity=Decimal(str(item_data.get('quantity', 1))),
                                unit_price=Decimal(str(item_data.get('unit_price', 0))),
                                tax_rate=item_data.get('tax_rate', 'A'),
                                discount=Decimal(str(item_data.get('discount', 0))),
                                **export_fields
                            )
                    except (Product.DoesNotExist, Service.DoesNotExist) as e:
                        logger.error(f"Item not found: {e}")
                        continue

                update_task_progress(task_id, 70, 'Calculating totals...')

                sale.update_totals()
                sale.status = 'COMPLETED' if sale.document_type == 'RECEIPT' else 'PENDING_PAYMENT'
                sale.save()

                if form_data.get('payment_amount'):
                    try:
                        amount = Decimal(form_data['payment_amount'])
                        if amount > 0:
                            Payment.objects.create(
                                sale=sale,
                                store=sale.store,
                                amount=amount,
                                payment_method=sale.payment_method,
                                transaction_reference=form_data.get('payment_reference', ''),
                                is_confirmed=True,
                                confirmed_at=timezone.now(),
                                created_by=sale.created_by
                            )
                    except Exception as e:
                        logger.error(f"Payment creation failed: {e}")

                update_task_progress(task_id, 80, 'Sending notifications...')
                send_receipt_ws_update(sale)

                sale_pk = sale.pk
                sale_document_type = sale.document_type
                sale_document_number = sale.document_number
                sale_total_amount = float(sale.total_amount)

                store_config = sale.store.effective_efris_config
                efris_enabled = store_config.get('enabled', False)

                update_task_progress(task_id, 90, 'Queueing background tasks...')

                _schema = user_schema

                if sale_document_type == 'RECEIPT':
                    transaction.on_commit(
                        lambda: process_receipt_async.delay(
                            sale_pk, user_id, schema_name=_schema)
                    )
                elif sale_document_type == 'INVOICE':
                    create_stock_movements(sale)

                    if efris_enabled:
                        transaction.on_commit(
                            lambda: fiscalize_invoice_async.delay(
                                sale_pk, user_id, schema_name=_schema)
                        )

            success_message = f'{sale_document_type} #{sale_document_number} created successfully!'
            if is_export_sale:
                success_message += ' [EXPORT INVOICE]'

            update_task_progress(
                task_id,
                100,
                success_message,
                'completed',
                sale_id=sale_pk
            )

            return {
                'success': True,
                'sale_id': sale_pk,
                'document_number': sale_document_number,
                'total_amount': sale_total_amount,
                'is_export_sale': is_export_sale
            }

    except Exception as e:
        logger.error(f"Background sale creation failed: {e}", exc_info=True)
        update_task_progress(task_id, 100, f'Error: {str(e)}', 'error')
        return {'success': False, 'error': str(e)}

    finally:
        if initial_schema and initial_schema != 'public':
            try:
                connection.set_schema(initial_schema)
            except Exception:
                pass


def update_task_progress(task_id, progress, message, status='processing', sale_id=None):
    """Update task progress via cache + WebSocket."""
    from django.core.cache import cache

    task_data = {
        'status': status,
        'message': message,
        'progress': progress,
        'sale_id': sale_id,
        'updated_at': timezone.now().isoformat()
    }

    cache.set(f'sale_task_{task_id}', task_data, 600)

    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.debug("WebSocket channel layer not configured — skipping task progress WS update")
            return
        async_to_sync(channel_layer.group_send)(
            f'task_progress_{task_id}',
            {
                'type': 'task.progress',
                'data': task_data
            }
        )
    except Exception as e:
        logger.debug(f"WebSocket update failed: {e}")


def update_stock_for_receipt(sale):
    """
    Update stock for products in receipt — idempotent.

    NOTE: This function is intentionally NOT called from process_receipt_async.
    Stock deduction happens synchronously inside SaleItem.save() during the
    request transaction. This function is kept here only for explicit callers
    that create sales without going through SaleItem.save() (e.g. imports,
    data migrations). Calling it from the Celery task was the root cause of
    duplicate StockMovement records.

    REFERENCE KEY FIX:
    The movement reference is now consistently "RECEIPT-{document_number}"
    (e.g. "RECEIPT-RCP-20260324-0007") matching what SaleItem.save() writes.
    The old inventory lookup used just document_number as the key, which caused
    "Sale not found" warnings and incorrect EFRIS sync deferral.
    """
    from inventory.models import Stock, StockMovement
    from django.db.models import F

    for item in sale.items.filter(item_type='PRODUCT'):
        if item.product:
            try:
                # Consistent reference key — must match what SaleItem.save() writes
                movement_ref = f"RECEIPT-{sale.document_number}"

                already_exists = StockMovement.objects.filter(
                    product=item.product,
                    store=sale.store,
                    movement_type='SALE',
                    reference=movement_ref,
                ).exists()

                if already_exists:
                    logger.warning(
                        f"StockMovement already exists for {item.product.name} "
                        f"ref={movement_ref} — skipping"
                    )
                    continue

                updated = Stock.objects.filter(
                    product=item.product,
                    store=sale.store
                ).update(quantity=F('quantity') - item.quantity)

                if updated:
                    stock = Stock.objects.get(product=item.product, store=sale.store)

                    StockMovement.objects.create(
                        product=item.product,
                        store=sale.store,
                        movement_type='SALE',
                        quantity=item.quantity,
                        reference=movement_ref,
                        unit_price=item.unit_price,
                        total_value=item.total_price,
                        created_by=sale.created_by,
                        notes=f"Receipt: {sale.document_number}"
                    )

                    stock.refresh_from_db()
                    logger.debug(f"Updated stock for {item.product.name}: -{item.quantity}")

                else:
                    Stock.objects.create(
                        product=item.product,
                        store=sale.store,
                        quantity=-item.quantity,
                        last_updated=timezone.now()
                    )

                    StockMovement.objects.create(
                        product=item.product,
                        store=sale.store,
                        movement_type='SALE',
                        quantity=item.quantity,
                        reference=movement_ref,
                        unit_price=item.unit_price,
                        total_value=item.total_price,
                        created_by=sale.created_by,
                        notes=f"Receipt: {sale.document_number} (initial stock)"
                    )

                    logger.debug(f"Created stock record for {item.product.name}")

            except Exception as e:
                logger.error(f"Failed to update stock for {item.product.name}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# The remaining tasks below are unchanged — they are reproduced verbatim so
# this file is a complete drop-in replacement.
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=5, default_retry_delay=60, queue='efris')
def fiscalize_invoice_async(self, sale_id, user_id=None, schema_name=None):
    """Fiscalize an invoice/receipt via EFRIS asynchronously."""
    initial_schema = TenantResolver.get_current_schema()
    try:
        if schema_name:
            tenant_schema = schema_name
            with schema_context(tenant_schema):
                sale = Sale.objects.select_related(
                    'store__company', 'customer', 'created_by'
                ).get(id=sale_id)
        else:
            sale, tenant_schema = TenantResolver.find_sale_schema(sale_id)
            if not sale or not tenant_schema:
                logger.error(f"Sale {sale_id} not found in any tenant schema for fiscalization")
                return {'success': False, 'error': 'Sale not found'}

        with schema_context(tenant_schema):
            if sale.is_fiscalized:
                logger.info(f"Sale {sale.document_number} already fiscalized — skipping")
                return {'success': True, 'message': 'Already fiscalized'}

            can_fiscalize, reason = sale.can_fiscalize()
            if not can_fiscalize:
                logger.warning(f"Sale {sale.document_number} cannot be fiscalized: {reason}")
                return {'success': False, 'error': reason}

            efris_service = create_efris_service(sale.store.company, sale.store)
            result = efris_service.fiscalize_sale(sale)

            if result.get('success'):
                logger.info(f"Sale {sale.document_number} fiscalized successfully")
                return {
                    'success': True,
                    'invoice_no': result.get('invoice_no'),
                    'fiscal_code': result.get('fiscal_code'),
                }
            else:
                error_msg = result.get('error', 'Unknown EFRIS error')
                logger.error(f"EFRIS fiscalization failed for {sale.document_number}: {error_msg}")
                raise Exception(error_msg)

    except Exception as e:
        logger.error(f"Fiscalization task error for sale {sale_id}: {e}", exc_info=True)
        raise self.retry(exc=e, countdown=min(60 * (2 ** self.request.retries), 3600))

    finally:
        if initial_schema and initial_schema != 'public':
            try:
                connection.set_schema(initial_schema)
            except Exception:
                pass


@shared_task(bind=True, max_retries=3, queue='default')
def send_document_notification(self, sale_id, notification_type, user_id=None, schema_name=None):
    """Send document-related notifications."""
    initial_schema = TenantResolver.get_current_schema()
    try:
        if schema_name:
            tenant_schema = schema_name
        else:
            _, tenant_schema = TenantResolver.find_sale_schema(sale_id)

        if not tenant_schema:
            return

        with schema_context(tenant_schema):
            from notifications.services import SalesNotifications
            sale = Sale.objects.select_related(
                'customer', 'created_by', 'store__company'
            ).get(id=sale_id)

            if notification_type == 'RECEIPT_CREATED':
                SalesNotifications.notify_receipt_created(sale)
            elif notification_type == 'INVOICE_SENT':
                SalesNotifications.notify_invoice_sent(sale)
            elif notification_type == 'PROFORMA_CREATED':
                SalesNotifications.notify_proforma_created(sale)

    except Exception as e:
        logger.error(f"Error sending notification for sale {sale_id}: {e}", exc_info=True)

    finally:
        if initial_schema and initial_schema != 'public':
            try:
                connection.set_schema(initial_schema)
            except Exception:
                pass


@shared_task(queue='default')
def sync_invoice_with_efris(invoice_id, schema_name=None):
    """Sync a single invoice status with EFRIS."""
    initial_schema = TenantResolver.get_current_schema()
    try:
        if schema_name:
            tenant_schema = schema_name
        else:
            with schema_context('public'):
                from django_tenants.utils import get_tenant_model
                schemas = list(
                    get_tenant_model().objects
                    .exclude(schema_name='public')
                    .values_list('schema_name', flat=True)
                )
            tenant_schema = None
            for s in schemas:
                try:
                    with schema_context(s):
                        if Invoice.objects.filter(pk=invoice_id).exists():
                            tenant_schema = s
                            break
                except Exception:
                    continue

        if not tenant_schema:
            return

        with schema_context(tenant_schema):
            invoice = Invoice.objects.select_related('store__company').get(pk=invoice_id)
            efris_service = create_efris_service(invoice.store.company, invoice.store)
            efris_service.sync_invoice_status(invoice)
            logger.debug(f"Synced EFRIS status for invoice {invoice.pk}")

    except Exception as e:
        logger.error(f"Error syncing invoice {invoice_id} with EFRIS: {e}")

    finally:
        if initial_schema and initial_schema != 'public':
            try:
                connection.set_schema(initial_schema)
            except Exception:
                pass


def update_task_progress(task_id, progress, message, status='processing', sale_id=None):
    """Update task progress via cache + WebSocket."""
    from django.core.cache import cache

    task_data = {
        'status': status,
        'message': message,
        'progress': progress,
        'sale_id': sale_id,
        'updated_at': timezone.now().isoformat()
    }

    cache.set(f'sale_task_{task_id}', task_data, 600)

    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        async_to_sync(channel_layer.group_send)(
            f'task_progress_{task_id}',
            {'type': 'task.progress', 'data': task_data}
        )
    except Exception as e:
        logger.debug(f"WebSocket update failed: {e}")


@shared_task(queue='default')
def bulk_fiscalize_pending_invoices_for_tenant(schema_name):
    """
    Fiscalize all pending sales in a tenant — batched to reduce broker round-trips.
    """
    from celery import group as celery_group

    with schema_context(schema_name):
        ids = list(
            Sale.objects.filter(
                is_fiscalized=False,
                document_type__in=['RECEIPT', 'INVOICE'],
                status='COMPLETED',
                is_voided=False,
            ).values_list('id', flat=True)[:500]
        )

    if not ids:
        logger.info(f"No pending sales to fiscalize in {schema_name}")
        return

    chunk_size = 50
    chunks = [ids[i:i + chunk_size] for i in range(0, len(ids), chunk_size)]
    job = celery_group(
        bulk_fiscalize_batch.s(chunk, schema_name)
        for chunk in chunks
    )
    job.apply_async()
    logger.info(f"Queued {len(chunks)} batch tasks for {len(ids)} sales in {schema_name}")


@shared_task(queue='efris')
def bulk_fiscalize_batch(sale_ids, schema_name):
    """Fiscalize a chunk of sales in a single task."""
    with schema_context(schema_name):
        for sale_id in sale_ids:
            try:
                sale = Sale.objects.select_related(
                    'store__company', 'customer', 'created_by'
                ).prefetch_related('items__product', 'items__service').get(pk=sale_id)

                if sale.is_fiscalized:
                    continue

                efris_service = create_efris_service(sale.store.company, sale.store)
                efris_service.fiscalize_sale(sale)
                logger.info(f"Batch fiscalized sale {sale.document_number} in {schema_name}")

            except Exception as e:
                logger.error(f"Batch fiscalize failed for sale {sale_id} in {schema_name}: {e}")


@shared_task(queue='default')
def refresh_customer_credit_balances(schema_name=None):
    """Periodically recompute credit balances for all credit-enabled customers."""
    from django_tenants.utils import schema_context, get_tenant_model

    if schema_name:
        schemas = [schema_name]
    else:
        with schema_context('public'):
            schemas = list(
                get_tenant_model().objects
                .exclude(schema_name='public')
                .values_list('schema_name', flat=True)
            )

    for schema in schemas:
        try:
            with schema_context(schema):
                from customers.models import Customer
                qs = Customer.objects.filter(allow_credit=True, is_active=True)
                updated = 0
                for customer in qs.iterator(chunk_size=200):
                    try:
                        customer.update_credit_balance()
                        updated += 1
                    except Exception as e:
                        logger.warning(f"Credit balance update failed for customer {customer.id}: {e}")
                logger.info(f"Refreshed credit balances for {updated} customers in {schema}")
        except Exception as e:
            logger.error(f"Error refreshing credit balances in schema {schema}: {e}")


@shared_task
def periodic_bulk_fiscalization():
    """Periodic task to run bulk fiscalization across all tenants."""
    from django_tenants.utils import get_tenant_model
    with schema_context('public'):
        schemas = list(
            get_tenant_model().objects
            .exclude(schema_name='public')
            .values_list('schema_name', flat=True)
        )
    for schema in schemas:
        bulk_fiscalize_pending_invoices_for_tenant.delay(schema)


@shared_task
def periodic_document_reports():
    """Periodic task to generate document reports across all tenants."""
    from datetime import timedelta
    from .services import SalesDocumentService

    initial_schema = TenantResolver.get_current_schema()
    tenant_schemas = TenantResolver.get_all_tenant_schemas()
    yesterday = timezone.now().date() - timedelta(days=1)

    results = {'tenants_processed': 0, 'reports_generated': 0}

    for schema_name in tenant_schemas:
        try:
            with schema_context(schema_name):
                from stores.models import Store
                stores = Store.objects.filter(is_active=True)

                for store in stores:
                    summary = SalesDocumentService.get_document_summary(
                        store=store,
                        start_date=yesterday,
                        end_date=yesterday
                    )
                    logger.info(f"Daily document summary for store {store.name} in {schema_name}: {summary}")
                    results['reports_generated'] += 1

                results['tenants_processed'] += 1

        except Exception as e:
            logger.error(f"Error generating document reports for schema {schema_name}: {e}")

    logger.info(f"Periodic document reports completed: {results}")

    if initial_schema:
        try:
            connection.set_schema(initial_schema)
        except Exception:
            pass

    return results


@shared_task
def periodic_efris_sync():
    """Periodic task to sync EFRIS status for recent invoices across all tenants."""
    from datetime import timedelta

    initial_schema = TenantResolver.get_current_schema()
    tenant_schemas = TenantResolver.get_all_tenant_schemas()
    cutoff_date = timezone.now() - timedelta(hours=24)

    results = {
        'tenants_processed': 0,
        'total_invoices_synced': 0,
        'tenant_results': []
    }

    for schema_name in tenant_schemas:
        try:
            with schema_context(schema_name):
                recent_invoice_ids = list(Invoice.objects.filter(
                    is_fiscalized=True,
                    fiscal_document_number__isnull=False,
                    fiscalization_time__gte=cutoff_date
                ).values_list('id', flat=True)[:50])

                synced_count = 0
                for invoice_id in recent_invoice_ids:
                    sync_invoice_with_efris.delay(invoice_id, schema_name=schema_name)
                    synced_count += 1

                results['tenant_results'].append({'schema': schema_name, 'invoices_synced': synced_count})
                results['total_invoices_synced'] += synced_count

                if synced_count > 0:
                    logger.info(f"Queued {synced_count} invoices for EFRIS sync in {schema_name}")

        except Exception as e:
            logger.error(f"Error syncing EFRIS status for {schema_name}: {e}")
            results['tenant_results'].append({'schema': schema_name, 'error': str(e)})

        results['tenants_processed'] += 1

    logger.info(f"EFRIS sync completed: {results}")

    if initial_schema:
        try:
            connection.set_schema(initial_schema)
        except Exception:
            pass

    return results


@shared_task
def send_payment_reminders():
    """Celery task to send pending payment reminders."""
    from sales.payment_reminders import PaymentReminder
    return PaymentReminder.send_pending_reminders()