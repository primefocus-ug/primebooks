from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from errors import views
from accounts import views as view
from django.core.exceptions import ObjectDoesNotExist
from accounts.models import CustomUser
# 🔥 NEW: Import for desktop API endpoint
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.core import serializers
import json
from django.views.decorators.cache import never_cache
from onboarding.search import palette_search
import logging
from django.shortcuts import render
from django.http import HttpResponse


logger = logging.getLogger(__name__)


# 🔥 NEW: Desktop API endpoint - Add this function
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_current_user_for_desktop(request):
    """
    Get current authenticated user's data for desktop sync
    This runs in the TENANT schema (e.g., pada.localhost:8000)
    """
    user = request.user

    logger.info(f"Desktop sync - Fetching user data: {user.email} (ID: {user.id})")

    try:
        # Serialize the user with ALL fields
        serialized = serializers.serialize('json', [user])
        data = json.loads(serialized)[0]

        # Extract fields
        user_data = data['fields'].copy()
        user_data['id'] = data['pk']

        # Keep password hash for desktop import
        # Remove only truly sensitive fields
        user_data.pop('backup_codes', None)
        user_data.pop('failed_login_attempts', None)
        user_data.pop('last_login', None)

        # Handle company foreign key
        if hasattr(request, 'tenant'):
            user_data['company_id'] = request.tenant.company_id
            user_data.pop('company', None)
        elif user.company:
            user_data['company_id'] = user.company.company_id
            user_data.pop('company', None)

        logger.info(f"✓ Returning user data for {user.email} (ID: {user.id})")

        return Response({
            'success': True,
            'user': user_data
        })

    except Exception as e:
        logger.error(f"Error fetching user data: {e}", exc_info=True)
        return Response(
            {'error': str(e)},
            status=500
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sync_user(request, email):
    """
    Sync a specific user to desktop - includes password hash
    🔥 CRITICAL: This endpoint returns password hashes for desktop sync
    Only accessible with valid auth token

    URL: /api/desktop/sync/user/<email>/
    """
    try:
        logger.info(f"Desktop sync request for user: {email}")
        logger.info(f"Requested by: {request.user.email}")

        # Verify the requesting user has permission
        # (either requesting their own data or is admin/staff)
        if request.user.email != email and not (request.user.is_staff or request.user.is_superuser):
            logger.warning(f"Permission denied: {request.user.email} tried to sync {email}")
            return Response(
                {'error': 'Permission denied'},
                status=403
            )

        # Fetch the user
        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            logger.error(f"User not found in database: {email}")
            return Response(
                {'error': f'User not found: {email}'},
                status=404
            )

        # Get role ID safely
        role_id = None
        if hasattr(user, 'role') and user.role:
            role_id = user.role.id if hasattr(user.role, 'id') else None

        # Serialize user data INCLUDING password hash
        user_data = {
            'id': user.id,
            'email': user.email,
            'username': user.username,
            'first_name': user.first_name or '',
            'last_name': user.last_name or '',
            'is_active': user.is_active,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
            'phone_number': getattr(user, 'phone_number', ''),
            'password': user.password,  # 🔥 Include password hash
            'role': role_id,
            'date_joined': user.date_joined.isoformat() if hasattr(user, 'date_joined') else None,
        }

        logger.info(f"✅ Successfully prepared user data for desktop sync: {email}")
        logger.info(f"   - User ID: {user.id}")
        logger.info(f"   - Has password: {bool(user.password)}")
        logger.info(f"   - Role ID: {role_id}")

        return Response(user_data)

    except Exception as e:
        logger.error(f"❌ Error syncing user {email}: {e}", exc_info=True)
        return Response(
            {'error': str(e)},
            status=500
        )


@never_cache
def pushalert_sw(request):
    """
    Serve PushAlert's sw.js at root scope for every tenant subdomain.
    Django-tenants routes all subdomains through the same urlpatterns,
    so this single view covers pada.primebooks.sale, rem.primebooks.sale, etc.

    The file lives at BASE_DIR/static/sw.js — download it from the
    PushAlert dashboard (the 'Files: sw.js' link) and place it there.
    Content-Type MUST be application/javascript for SW registration to work.
    """
    import os
    sw_path = os.path.join(settings.BASE_DIR, 'static', 'sw.js')
    try:
        with open(sw_path, 'rb') as f:
            content = f.read()
        response = HttpResponse(content, content_type='application/javascript; charset=utf-8')
        # Service workers must not be cached — always serve fresh
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Service-Worker-Allowed'] = '/'
        return response
    except FileNotFoundError:
        return HttpResponse(
            '// PushAlert sw.js not found. Download from PushAlert dashboard and place at static/sw.js',
            content_type='application/javascript',
            status=404
        )


# Main URL patterns (accessible without language prefix)
urlpatterns = [
    # ── PushAlert service worker at root scope ──────────────────────────────────
    # Must be served from / (not /static/) so it can control all pages.
    # Works for every tenant subdomain: pada.primebooks.sale, rem.primebooks.sale, etc.
    path('sw.js', pushalert_sw, name='pushalert_sw'),

    path('admin/', admin.site.urls),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/company/', include('company.api_urls')),
    path('pos/', include('pos_app.urls')),
    path('push/', include('push_notifications.urls', namespace='push_notifications')),
    path("api/v1/",       include("sync.urls")),
    path("api/desk/",  include("sync.desktop_urls")),
    path('new', include('changelog.urls')),
    path('suggestions/', include('suggestions.urls')),
    path('onboarding/', include('onboarding.urls')),
    path('search/palette/', palette_search, name='palette_search'),
    path('driving-school/', include('driving_school.urls', namespace='driving_school')),
    path('support/',include('support_widget.urls')),
    path('api/support/', include('support_widget.api_urls')),
    path('nav-preferences/', include('core.urls', namespace='nav_preferences')),
    path('api/', include('accounts.api_urls')),
    path('api/', include('primebooks.api_urls')),
    path('api/v1/', include('sales.api_urls')),
    path('api/v1/', include('invoices.api_urls')),
    path('api/v1/', include('inventory.api_endpoints')),
    path('i18n/', include('django.conf.urls.i18n')),
    #path('api/messaging/', include('messaging.api_urls')),

    # 🔥 DESKTOP API ENDPOINTS - Must be under /api/desktop/ path
    path('api/desktop/sync/current-user/',
         get_current_user_for_desktop,
         name='web_desktop_current_user'),

    # 🔥 FIXED: Correct path for user sync endpoint
    path('api/desktop/sync/user/<str:email>/',
         sync_user,
         name='desktop_sync_user'),
]

error_patterns = [
    path('403/', views.error_403_view, name='error_403'),
    path('404/', views.error_404_view, name='error_404'),
    path('500/', views.error_500_view, name='error_500'),
    path('502/', views.error_502_view, name='error_502'),
    path('503/', views.error_503_view, name='error_503'),
    path('error/<str:error_code>/', views.generic_error_view, name='generic_error'),
]

# Testing URLs (only in DEBUG mode)
if settings.DEBUG:
    error_patterns += [
        path('test-errors/', views.test_error_view, name='test_errors'),
        path('test-errors/<str:error_code>/', views.test_error_view, name='test_specific_error'),
    ]

urlpatterns += i18n_patterns(
    path('prime-book/', include('company.urls')),
    path('legal/', include('company.legal')),
    path('invoices/', include('invoices.urls')),
    path('accounts/', include('accounts.urls')),
    path('inventory/', include('inventory.urls')),
    path('sales/', include('sales.urls')),
    path('stores/', include('stores.urls')),
    path('notifications/', include('notifications.urls')),
    path('customers/', include('customers.urls')),
    path('reports/', include('reports.urls')),
    path('expenses/', include('expenses.urls')),
    path('efris-man/', include('efris.ford')),
    path('efris/', include('efris.urls')),
    path('errors/', include((error_patterns, 'errors'), namespace='errors')),
    path('', view.user_dashboard, name='user_dashboard'),
)

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = 'errors.views.error_403_view'
handler404 = 'errors.views.error_404_view'
handler500 = 'errors.views.error_500_view'

if settings.IS_DESKTOP:
    urlpatterns += [
        path('desktop/', include('primebooks.urls')),
    ]