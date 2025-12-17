import json
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from django.core.serializers.json import DjangoJSONEncoder


class DecimalEncoder(DjangoJSONEncoder):
    """Custom JSON encoder to handle Decimal types"""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


class CompanyDashboardConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time company dashboard updates
    """

    async def connect(self):
        self.company_id = self.scope['url_route']['kwargs']['company_id']
        self.room_group_name = f'company_dashboard_{self.company_id}'

        # Check if user has permission to access this company
        user = self.scope["user"]
        if not await self.user_can_access_company(user, self.company_id):
            await self.close()
            return

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # Send initial data
        await self.send_initial_data()

        # Start periodic updates
        asyncio.create_task(self.periodic_updates())

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'request_store_analytics':
                store_id = data.get('store_id')
                await self.send_branch_analytics(store_id)
            elif message_type == 'request_performance_update':
                await self.send_performance_update()
            elif message_type == 'ping':
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'timestamp': timezone.now().isoformat()
                }))
        except json.JSONDecodeError:
            await self.send_error("Invalid JSON format")

    async def send_initial_data(self):
        """Send initial dashboard data when connection is established"""
        company_data = await self.get_company_data()
        await self.send(text_data=json.dumps({
            'type': 'initial_data',
            'data': company_data
        }, cls=DecimalEncoder))

    async def periodic_updates(self):
        """Send periodic updates every 30 seconds"""
        while True:
            try:
                await asyncio.sleep(30)  # Update every 30 seconds

                # Get updated metrics
                metrics = await self.get_real_time_metrics()

                await self.send(text_data=json.dumps({
                    'type': 'metrics_update',
                    'data': metrics,
                    'timestamp': timezone.now().isoformat()
                }, cls=DecimalEncoder))

            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log error but continue
                print(f"Error in periodic updates: {e}")
                continue

    @database_sync_to_async
    def user_can_access_company(self, user, company_id):
        """Check if user can access the company dashboard"""
        from .models import Company

        if not user.is_authenticated:
            return False

        if user.is_saas_admin or user.can_access_all_companies:
            return True

        try:
            company = Company.objects.get(company_id=company_id)
            return user.company == company
        except Company.DoesNotExist:
            return False

    @database_sync_to_async
    def get_company_data(self):
        """Get initial company dashboard data"""
        from django.db.models import Sum, Count, Avg
        from .models import Company
        from sales.models import Sale
        from stores.models import Store
        from accounts.models import CustomUser

        try:
            company = Company.objects.select_related('plan').get(company_id=self.company_id)
            thirty_days_ago = timezone.now().date() - timedelta(days=30)

            # Basic company stats
            stores = Store.objects.filter(company=company)
            employees = CustomUser.objects.filter(company=company, is_hidden=False)

            # Revenue data
            store_ids = stores.values_list('id', flat=True)

            revenue_data = Sale.objects.filter(
                store_id__in=store_ids,
                created_at__date__gte=thirty_days_ago,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                total_revenue=Sum('total_amount'),
                total_sales=Count('id'),
                avg_sale=Avg('total_amount')
            )

            # Get main store
            main_store = stores.filter(is_main_branch=True).first()
            main_store_name = main_store.name if main_store else "No Main Store"

            return {
                'company_id': company.company_id,
                'company_name': company.name,
                'main_store_name': main_store_name,
                'total_stores': stores.count(),
                'active_stores': stores.filter(is_active=True).count(),
                'total_employees': employees.count(),
                'active_employees': employees.filter(is_active=True).count(),
                'total_revenue_30d': float(revenue_data['total_revenue'] or 0),
                'total_sales_30d': revenue_data['total_sales'] or 0,
                'avg_sale_amount': float(revenue_data['avg_sale'] or 0),
                'subscription_status': company.status,
                'last_updated': timezone.now().isoformat()
            }

        except Exception as e:
            return {'error': str(e)}

    @database_sync_to_async
    def get_real_time_metrics(self):
        """Get real-time metrics for periodic updates"""
        from django.db.models import Sum, Count, F
        from .models import Company
        from sales.models import Sale
        from stores.models import Store, DeviceOperatorLog
        from accounts.models import CustomUser
        from inventory.models import Stock

        try:
            company = Company.objects.get(company_id=self.company_id)
            now = timezone.now()
            today = now.date()
            thirty_days_ago = today - timedelta(days=30)

            # Get all stores for the company
            all_stores = Store.objects.filter(company=company)
            store_ids = all_stores.values_list('id', flat=True)

            # Current day sales
            today_sales = Sale.objects.filter(
                store_id__in=store_ids,
                created_at__date=today,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                revenue=Sum('total_amount'),
                count=Count('id')
            )

            # Recent activity (last hour)
            recent_activities = []
            hour_ago = now - timedelta(hours=1)

            # Recent sales
            recent_sales = Sale.objects.filter(
                store_id__in=store_ids,
                created_at__gte=hour_ago,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).select_related('store', 'store__company').order_by('-created_at')[:5]

            for sale in recent_sales:
                recent_activities.append({
                    'type': 'sale',
                    'description': f"Sale of {float(sale.total_amount)} at {sale.store.name}",
                    'timestamp': sale.created_at.isoformat(),
                    'amount': float(sale.total_amount),
                    'store_name': sale.store.name,
                    'company_name': sale.store.company.name if sale.store.company else ''
                })

            # Recent device activities
            recent_logs = DeviceOperatorLog.objects.filter(
                device__store__in=all_stores,
                timestamp__gte=hour_ago
            ).select_related('user', 'device__store__company').order_by('-timestamp')[:3]

            for log in recent_logs:
                recent_activities.append({
                    'type': 'device_activity',
                    'description': f"{log.user.get_full_name()} {log.action.replace('_', ' ').lower()}",
                    'timestamp': log.timestamp.isoformat(),
                    'user_name': log.user.get_full_name(),
                    'store_name': log.store.name,
                    'company_name': log.store.company.name if log.store.company else ''
                })

            # Sort activities by timestamp
            recent_activities.sort(key=lambda x: x['timestamp'], reverse=True)

            # Inventory alerts
            low_stock_count = Stock.objects.filter(
                store__in=all_stores,
                quantity__lte=F('low_stock_threshold')
            ).count()

            out_of_stock_count = Stock.objects.filter(
                store__in=all_stores,
                quantity=0
            ).count()

            # Active users across all stores
            active_users_count = CustomUser.objects.filter(
                company__company_id=self.company_id,
                is_active=True,
                last_activity_at__gte=now - timedelta(minutes=15)
            ).count()

            return {
                'today_revenue': float(today_sales['revenue'] or 0),
                'today_sales_count': today_sales['count'] or 0,
                'recent_activities': recent_activities[:8],
                'inventory_alerts': {
                    'low_stock_items': low_stock_count,
                    'out_of_stock_items': out_of_stock_count
                },
                'active_users_count': active_users_count,
                'timestamp': now.isoformat()
            }

        except Exception as e:
            return {'error': str(e)}

    async def send_branch_analytics(self, store_id):
        """Send detailed analytics for a specific store"""
        if not store_id:
            return

        try:
            analytics_data = await self.get_branch_analytics_data(store_id)
            await self.send(text_data=json.dumps({
                'type': 'store_analytics',
                'store_id': store_id,
                'data': analytics_data
            }, cls=DecimalEncoder))
        except Exception as e:
            await self.send_error(f"Failed to load store analytics: {str(e)}")

    @database_sync_to_async
    def get_branch_analytics_data(self, store_id):
        """Get detailed analytics data for a specific store"""
        from django.db.models import Sum, Count, Avg
        from sales.models import Sale
        from stores.models import Store

        try:
            store = Store.objects.get(id=store_id, company__company_id=self.company_id)
            thirty_days_ago = timezone.now().date() - timedelta(days=30)

            # Store performance metrics
            metrics = Sale.objects.filter(
                store=store,
                created_at__date__gte=thirty_days_ago,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                total_revenue=Sum('total_amount'),
                total_sales=Count('id'),
                avg_sale=Avg('total_amount')
            )

            # Daily revenue for last 7 days
            daily_revenue = []
            for i in range(7):
                date = timezone.now().date() - timedelta(days=6 - i)
                day_revenue = Sale.objects.filter(
                    store=store,
                    created_at__date=date,
                    is_voided=False,
                    status__in=['COMPLETED', 'PAID']
                ).aggregate(total=Sum('total_amount'))['total'] or 0

                daily_revenue.append({
                    'date': date.isoformat(),
                    'revenue': float(day_revenue)
                })

            # Get store devices summary
            devices_summary = store.get_device_summary()

            return {
                'store_id': store.id,
                'store_name': store.name,
                'store_type': store.store_type,
                'is_main_branch': store.is_main_branch,
                'metrics': {
                    'total_revenue': float(metrics['total_revenue'] or 0),
                    'total_sales': metrics['total_sales'] or 0,
                    'avg_sale': float(metrics['avg_sale'] or 0),
                    'staff_count': store.get_staff_count(),
                    'active_devices': devices_summary['total_devices']
                },
                'daily_revenue': daily_revenue,
                'efris_status': store.efris_status,
                'can_fiscalize': store.can_fiscalize,
                'last_updated': timezone.now().isoformat()
            }

        except Store.DoesNotExist:
            raise Exception("Store not found")
        except Exception as e:
            raise Exception(f"Error fetching store analytics: {str(e)}")

    async def send_performance_update(self):
        """Send updated performance metrics"""
        try:
            performance_data = await self.get_performance_data()
            await self.send(text_data=json.dumps({
                'type': 'performance_update',
                'data': performance_data
            }, cls=DecimalEncoder))
        except Exception as e:
            await self.send_error(f"Failed to load performance data: {str(e)}")

    @database_sync_to_async
    def get_performance_data(self):
        """Get updated performance data"""
        from django.db.models import Sum, Count
        from .models import Company
        from stores.models import Store
        from sales.models import Sale

        try:
            company = Company.objects.get(company_id=self.company_id)
            stores = Store.objects.filter(company=company, is_active=True)
            thirty_days_ago = timezone.now().date() - timedelta(days=30)

            store_performances = []

            for store in stores:
                metrics = Sale.objects.filter(
                    store=store,
                    created_at__date__gte=thirty_days_ago,
                    is_voided=False,
                    status__in=['COMPLETED', 'PAID']
                ).aggregate(
                    revenue=Sum('total_amount'),
                    sales_count=Count('id')
                )

                revenue = float(metrics['revenue'] or 0)
                sales_count = metrics['sales_count'] or 0

                # Calculate performance score based on store type
                performance_score = 0
                if sales_count > 0:
                    if store.store_type == 'MAIN':
                        # Main store has higher targets
                        sales_score = min(40, (sales_count / 100) * 40)
                        revenue_score = min(40, (revenue / 1000000) * 40)
                    elif store.store_type == 'WAREHOUSE':
                        # Warehouses might have fewer sales
                        sales_score = min(40, (sales_count / 20) * 40)
                        revenue_score = min(40, (revenue / 200000) * 40)
                    else:
                        # Regular stores
                        sales_score = min(40, (sales_count / 50) * 40)
                        revenue_score = min(40, (revenue / 500000) * 40)

                    # Add bonus for EFRIS enabled stores
                    efris_bonus = 5 if store.efris_enabled else 0
                    performance_score = min(100, sales_score + revenue_score + efris_bonus)

                store_performances.append({
                    'store_id': store.id,
                    'store_name': store.name,
                    'store_type': store.store_type,
                    'is_main_branch': store.is_main_branch,
                    'revenue': revenue,
                    'sales_count': sales_count,
                    'efris_enabled': store.efris_enabled,
                    'performance_score': round(performance_score, 1)
                })

            # Sort by performance score
            store_performances.sort(key=lambda x: x['performance_score'], reverse=True)

            # Calculate overall performance
            overall_performance = 0
            if store_performances:
                overall_performance = round(
                    sum(s['performance_score'] for s in store_performances) / len(store_performances), 1
                )

            return {
                'overall_performance_score': overall_performance,
                'top_performing_stores': store_performances[:3],
                'all_stores_performance': store_performances,
                'last_updated': timezone.now().isoformat()
            }

        except Exception as e:
            return {'error': str(e)}

    async def send_error(self, message):
        """Send error message to client"""
        await self.send(text_data=json.dumps({
            'type': 'error',
            'message': message,
            'timestamp': timezone.now().isoformat()
        }))

    # Message handlers for group messages
    async def dashboard_update(self, event):
        """Handle dashboard update messages from group"""
        await self.send(text_data=json.dumps({
            'type': 'dashboard_update',
            'data': event['data']
        }, cls=DecimalEncoder))

    async def store_update(self, event):
        """Handle store update messages from group"""
        await self.send(text_data=json.dumps({
            'type': 'store_update',
            'store_id': event['store_id'],
            'data': event['data']
        }, cls=DecimalEncoder))

    async def alert_notification(self, event):
        """Handle alert notifications from group"""
        await self.send(text_data=json.dumps({
            'type': 'alert',
            'alert_type': event['alert_type'],
            'message': event['message'],
            'data': event.get('data', {})
        }))


class BranchAnalyticsConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time store-specific analytics
    (Formerly BranchAnalyticsConsumer, renamed for consistency)
    """

    async def connect(self):
        self.store_id = self.scope['url_route']['kwargs']['store_id']
        self.room_group_name = f'store_analytics_{self.store_id}'

        # Check permissions
        user = self.scope["user"]
        if not await self.user_can_access_store(user, self.store_id):
            await self.close()
            return

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # Send initial analytics data
        await self.send_initial_analytics()

        # Start periodic updates every 15 seconds for store-specific data
        asyncio.create_task(self.periodic_analytics_updates())

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    @database_sync_to_async
    def user_can_access_store(self, user, store_id):
        """Check if user can access store analytics"""
        from stores.models import Store

        if not user.is_authenticated:
            return False

        if user.is_saas_admin:
            return True

        try:
            store = Store.objects.select_related('company').get(id=store_id)

            # Check if user's company matches store's company
            if user.company != store.company:
                return False

            # Check store-specific access
            if store.accessible_by_all:
                return True

            # Check if user is assigned to the store
            return user.stores.filter(id=store_id).exists() or user.managed_stores.filter(id=store_id).exists()

        except Store.DoesNotExist:
            return False

    async def send_initial_analytics(self):
        """Send initial store analytics data"""
        analytics_data = await self.get_detailed_store_analytics()
        await self.send(text_data=json.dumps({
            'type': 'initial_analytics',
            'data': analytics_data
        }, cls=DecimalEncoder))

    async def periodic_analytics_updates(self):
        """Send periodic analytics updates"""
        while True:
            try:
                await asyncio.sleep(15)  # Update every 15 seconds

                analytics_data = await self.get_real_time_store_metrics()

                await self.send(text_data=json.dumps({
                    'type': 'analytics_update',
                    'data': analytics_data,
                    'timestamp': timezone.now().isoformat()
                }, cls=DecimalEncoder))

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in store analytics updates: {e}")
                continue

    @database_sync_to_async
    def get_detailed_store_analytics(self):
        """Get comprehensive store analytics data"""
        from django.db.models import Sum, Count, Avg
        from stores.models import Store
        from sales.models import Sale
        from inventory.models import Stock

        try:
            store = Store.objects.select_related('company').get(id=self.store_id)
            thirty_days_ago = timezone.now().date() - timedelta(days=30)

            # Comprehensive metrics
            metrics = Sale.objects.filter(
                store=store,
                created_at__date__gte=thirty_days_ago,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                total_revenue=Sum('total_amount'),
                total_sales=Count('id'),
                avg_sale=Avg('total_amount'),
                unique_customers=Count('customer', distinct=True)
            )

            # Hourly sales pattern (last 24 hours)
            hourly_sales = []
            now = timezone.now()
            for i in range(24):
                hour_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23 - i)
                hour_end = hour_start + timedelta(hours=1)

                hour_sales = Sale.objects.filter(
                    store=store,
                    created_at__range=[hour_start, hour_end],
                    is_voided=False,
                    status__in=['COMPLETED', 'PAID']
                ).count()

                hourly_sales.append({
                    'hour': hour_start.strftime('%H:%M'),
                    'sales_count': hour_sales
                })

            # Inventory summary
            inventory_summary = store.get_inventory_summary()

            # Get device summary
            device_summary = store.get_device_summary()

            return {
                'store_id': store.id,
                'store_name': store.name,
                'store_type': store.store_type,
                'is_main_branch': store.is_main_branch,
                'comprehensive_metrics': {
                    'total_revenue': float(metrics['total_revenue'] or 0),
                    'total_sales': metrics['total_sales'] or 0,
                    'avg_sale': float(metrics['avg_sale'] or 0),
                    'unique_customers': metrics['unique_customers'] or 0,
                    'staff_count': store.get_staff_count()
                },
                'inventory_summary': inventory_summary,
                'device_summary': device_summary,
                'hourly_pattern': hourly_sales,
                'efris_config': {
                    'enabled': store.efris_enabled,
                    'status': store.efris_status,
                    'can_fiscalize': store.can_fiscalize,
                    'use_company_efris': store.use_company_efris,
                    'config_status': store.efris_config_status
                },
                'last_updated': timezone.now().isoformat()
            }

        except Exception as e:
            return {'error': str(e)}

    @database_sync_to_async
    def get_real_time_store_metrics(self):
        """Get real-time store metrics for updates"""
        from django.db.models import Sum, Count
        from stores.models import Store
        from sales.models import Sale
        from inventory.models import Stock

        try:
            store = Store.objects.get(id=self.store_id)
            now = timezone.now()
            today = now.date()

            # Today's metrics
            today_metrics = Sale.objects.filter(
                store=store,
                created_at__date=today,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                revenue=Sum('total_amount'),
                sales_count=Count('id')
            )

            # Last hour metrics
            hour_ago = now - timedelta(hours=1)
            last_hour_sales = Sale.objects.filter(
                store=store,
                created_at__gte=hour_ago,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).count()

            # Current inventory alerts
            inventory_alerts = {
                'low_stock': Stock.objects.filter(
                    store=store,
                    quantity__lte=models.F('low_stock_threshold')
                ).count(),
                'out_of_stock': Stock.objects.filter(
                    store=store,
                    quantity=0
                ).count()
            }

            # Check if store is currently open
            is_open_now = store.is_open_now()

            return {
                'today_revenue': float(today_metrics['revenue'] or 0),
                'today_sales_count': today_metrics['sales_count'] or 0,
                'last_hour_sales': last_hour_sales,
                'inventory_alerts': inventory_alerts,
                'is_open_now': is_open_now,
                'store_status': {
                    'is_active': store.is_active,
                    'allows_sales': store.allows_sales,
                    'allows_inventory': store.allows_inventory,
                    'efris_enabled': store.efris_enabled
                },
                'timestamp': now.isoformat()
            }

        except Exception as e:
            return {'error': str(e)}

    # For backward compatibility - handle branch_id references
    async def receive(self, text_data):
        """Handle incoming WebSocket messages with backward compatibility"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            # Handle legacy branch_id parameter
            if 'branch_id' in data:
                data['store_id'] = data.pop('branch_id')

            if message_type == 'request_branch_analytics':
                # Legacy support for branch analytics
                store_id = data.get('store_id')
                await self.send_legacy_branch_analytics(store_id)
            elif message_type == 'ping':
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'timestamp': timezone.now().isoformat()
                }))
        except json.JSONDecodeError:
            await self.send_error("Invalid JSON format")

    async def send_legacy_branch_analytics(self, store_id):
        """Send analytics in legacy format for backward compatibility"""
        try:
            analytics_data = await self.get_detailed_store_analytics()

            # Transform to legacy format
            legacy_data = {
                'branch_id': store_id,
                'branch_name': analytics_data.get('store_name', ''),
                'metrics': {
                    'total_revenue': analytics_data.get('comprehensive_metrics', {}).get('total_revenue', 0),
                    'total_sales': analytics_data.get('comprehensive_metrics', {}).get('total_sales', 0),
                    'avg_sale': analytics_data.get('comprehensive_metrics', {}).get('avg_sale', 0),
                }
            }

            await self.send(text_data=json.dumps({
                'type': 'branch_analytics',
                'data': legacy_data
            }, cls=DecimalEncoder))
        except Exception as e:
            await self.send_error(f"Failed to load branch analytics: {str(e)}")