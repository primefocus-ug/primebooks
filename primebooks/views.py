# primebooks/views.py
"""
Desktop Views - PostgreSQL Version
✅ Simplified for PostgreSQL multi-tenancy
✅ No more SQLite database checks
"""
from django.shortcuts import render, redirect
from django.views import View
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.http import JsonResponse
from company.models import Company
from primebooks.auth import DesktopAuthManager
import threading
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Global sync status
sync_status = {
    'in_progress': False,
    'progress': 0,
    'message': '',
    'step': '',
    'complete': False,
    'success': False,
}


class DesktopLoginView(View):
    """
    Desktop login view
    ✅ Updated for PostgreSQL - no database file checks
    """
    template_name = 'desktop/login.html'

    def get(self, request):
        # Show login form
        return render(request, self.template_name)

    def post(self, request):
        global sync_status

        email = request.POST.get('email')
        password = request.POST.get('password')
        subdomain = request.POST.get('subdomain') or 'pada'

        if not email or not password:
            return render(request, self.template_name, {
                'error': 'Email and password are required'
            })

        # Authenticate with server
        auth_manager = DesktopAuthManager()
        result = auth_manager.authenticate(email, password, subdomain)

        if not result['success']:
            return render(request, self.template_name, {
                'error': result.get('error', 'Authentication failed')
            })

        # Get company data
        company_data = result.get('company', {})
        company_id = company_data.get('company_id')

        if not company_id:
            return render(request, self.template_name, {
                'error': 'No company information returned'
            })

        # Set tenant in session
        request.session['tenant_id'] = company_id
        request.session['company_name'] = company_data.get('name', '')
        request.session['schema_name'] = company_data.get('schema_name', '')

        # ✅ CHECK IF SCHEMA EXISTS (not database file anymore)
        needs_sync = self.check_if_sync_needed(company_id, company_data.get('schema_name'))

        if not needs_sync:
            # Schema exists, go straight to dashboard
            logger.info(f"✅ Schema exists for {company_id}, skipping sync")
            messages.success(request, 'Login successful!')
            return redirect('user_dashboard')

        # Schema doesn't exist, need to sync
        logger.info(f"📦 Schema not found for {company_id}, starting sync...")

        # Reset sync status
        sync_status = {
            'in_progress': True,
            'progress': 10,
            'message': 'Preparing to sync...',
            'step': 'sync',
            'complete': False,
            'success': False,
        }

        # Start data sync in background thread
        def run_sync():
            global sync_status
            try:
                sync_status['progress'] = 20
                sync_status['message'] = 'Syncing company data...'

                auth_manager = DesktopAuthManager()
                token = result['token']

                # Sync company data
                company = auth_manager.sync_company_from_server(
                    company_data,
                    token,
                    subdomain
                )

                if company:
                    sync_status['progress'] = 100
                    sync_status['message'] = 'Sync complete!'
                    sync_status['complete'] = True
                    sync_status['success'] = True
                    logger.info(f"✅ Sync completed successfully for {company.name}")
                else:
                    sync_status['message'] = 'Sync failed - no company returned'
                    sync_status['complete'] = True
                    sync_status['success'] = False
                    logger.error("Sync failed - no company returned")

            except Exception as e:
                sync_status['message'] = f'Sync error: {str(e)}'
                sync_status['complete'] = True
                sync_status['success'] = False
                logger.error(f"Sync error: {e}", exc_info=True)
            finally:
                sync_status['in_progress'] = False

        # Start sync thread
        sync_thread = threading.Thread(target=run_sync, daemon=True)
        sync_thread.start()

        # Redirect to syncing page
        return redirect('primebooks:syncing')

    def check_if_sync_needed(self, company_id, schema_name):
        """
        Check if tenant schema needs to be synced
        ✅ PostgreSQL version - checks schema existence

        Returns:
            True if sync is needed, False if schema exists
        """
        if not company_id or not schema_name:
            return True

        try:
            from django.db import connection

            # Check if schema exists in PostgreSQL
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT schema_name 
                    FROM information_schema.schemata 
                    WHERE schema_name = %s
                """, [schema_name])

                schema_exists = cursor.fetchone() is not None

            if not schema_exists:
                logger.info(f"Schema not found: {schema_name}")
                return True

            # Check if schema has tables
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_schema = %s
                """, [schema_name])

                table_count = cursor.fetchone()[0]

            if table_count < 10:  # Should have at least 10 tables
                logger.warning(f"Schema {schema_name} has only {table_count} tables")
                return True

            logger.info(f"✅ Schema is valid: {schema_name} ({table_count} tables)")
            return False

        except Exception as e:
            logger.error(f"Error checking schema: {e}")
            return True


class DesktopSyncingView(View):
    """Show syncing progress"""
    template_name = 'desktop/syncing.html'

    def get(self, request):
        # Check if user is authenticated
        if not request.user.is_authenticated:
            messages.error(request, 'Please log in first')
            return redirect('primebooks:login')

        return render(request, self.template_name)


class DesktopSyncStatusView(View):
    """API endpoint for sync status"""

    def get(self, request):
        global sync_status
        return JsonResponse(sync_status)


class DesktopManualSyncView(View):
    """
    Manual sync trigger - for when users want to refresh data
    ✅ Updated for PostgreSQL
    """

    def post(self, request):
        global sync_status

        if not request.user.is_authenticated:
            return JsonResponse({
                'success': False,
                'error': 'Not authenticated'
            }, status=401)

        # Check if sync is already in progress
        if sync_status['in_progress']:
            return JsonResponse({
                'success': False,
                'error': 'Sync already in progress'
            }, status=400)

        # Get cached data
        auth_manager = DesktopAuthManager()
        company_data = auth_manager.get_company_info()

        if not company_data:
            return JsonResponse({
                'success': False,
                'error': 'No company information found'
            }, status=400)

        token = auth_manager.get_auth_token()
        subdomain = company_data.get('schema_name', 'pada')

        # Start sync
        sync_status = {
            'in_progress': True,
            'progress': 10,
            'message': 'Starting manual sync...',
            'step': 'sync',
            'complete': False,
            'success': False,
        }

        def run_sync():
            global sync_status
            try:
                sync_status['progress'] = 20
                sync_status['message'] = 'Syncing company data...'

                auth_manager = DesktopAuthManager()
                company = auth_manager.sync_company_from_server(
                    company_data,
                    token,
                    subdomain
                )

                if company:
                    sync_status['progress'] = 100
                    sync_status['message'] = 'Sync complete!'
                    sync_status['complete'] = True
                    sync_status['success'] = True
                else:
                    sync_status['message'] = 'Sync failed'
                    sync_status['complete'] = True
                    sync_status['success'] = False

            except Exception as e:
                sync_status['message'] = f'Sync error: {str(e)}'
                sync_status['complete'] = True
                sync_status['success'] = False
                logger.error(f"Manual sync error: {e}", exc_info=True)
            finally:
                sync_status['in_progress'] = False

        sync_thread = threading.Thread(target=run_sync, daemon=True)
        sync_thread.start()

        return JsonResponse({
            'success': True,
            'message': 'Sync started'
        })


class DesktopDashboardView(View):
    """
    Main dashboard
    ✅ Updated for PostgreSQL - no database file checks
    """
    template_name = 'desktop/dashboard.html'

    def get(self, request):
        # User should be authenticated by middleware
        if not request.user.is_authenticated:
            messages.error(request, 'Please log in first')
            return redirect('primebooks:login')

        tenant_id = request.session.get('tenant_id')

        if not tenant_id:
            messages.error(request, 'No company selected')
            return redirect('primebooks:login')

        # Get company
        try:
            company = Company.objects.get(company_id=tenant_id)
        except Company.DoesNotExist:
            messages.error(request, 'Company not found')
            return redirect('primebooks:login')

        # Check if schema exists
        try:
            from django.db import connection

            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT schema_name 
                    FROM information_schema.schemata 
                    WHERE schema_name = %s
                """, [company.schema_name])

                schema_exists = cursor.fetchone() is not None

            if not schema_exists:
                messages.warning(request, 'Company data needs to be synced')
                return redirect('primebooks:syncing')

        except Exception as e:
            logger.error(f"Error checking schema: {e}")
            messages.error(request, 'Error accessing company data')
            return redirect('primebooks:login')

        context = {
            'company': company,
            'is_desktop': True,
            'user': request.user,
        }

        return render(request, self.template_name, context)


class DesktopLogoutView(View):
    """Logout"""

    def get(self, request):
        from django.contrib.auth import logout as auth_logout

        # Clear authentication
        auth_manager = DesktopAuthManager()
        auth_manager.logout()

        # Django logout
        auth_logout(request)

        # Clear session
        request.session.flush()

        messages.success(request, 'Logged out successfully')
        return redirect('primebooks:login')


class DesktopSyncDataView(View):
    """
    Sync specific data types (invoices, products, etc.)
    ✅ New view for PostgreSQL
    """

    def post(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({
                'success': False,
                'error': 'Not authenticated'
            }, status=401)

        tenant_id = request.session.get('tenant_id')
        schema_name = request.session.get('schema_name')

        if not tenant_id or not schema_name:
            return JsonResponse({
                'success': False,
                'error': 'No tenant information'
            }, status=400)

        try:
            from primebooks.sync import SyncManager

            sync_manager = SyncManager(tenant_id, schema_name)

            # Check if online
            if not sync_manager.is_online():
                return JsonResponse({
                    'success': False,
                    'error': 'Server not reachable. Working offline.'
                })

            # Perform sync
            success = sync_manager.full_sync()

            if success:
                return JsonResponse({
                    'success': True,
                    'message': 'Data synced successfully'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Sync completed with errors'
                })

        except Exception as e:
            logger.error(f"Sync error: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)