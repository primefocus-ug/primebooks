from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.conf import settings
import logging

from .tenant_lookup import (
    find_user_tenant_by_email,
    verify_user_credentials,
    get_tenant_login_url,
    create_login_token,
    verify_login_token
)

logger = logging.getLogger(__name__)



@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def public_login_router(request):
    if request.user.is_authenticated:
        if hasattr(request, 'tenant') and request.tenant.schema_name != 'public':
            from accounts.views import get_dashboard_url
            return redirect(get_dashboard_url(request.user))

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')

        if not email or not password:
            messages.error(request, 'Please provide both email and password')
            return render(request, 'public_router/login.html')

        # Find user's tenant
        tenant_schema, tenant = find_user_tenant_by_email(email)

        if not tenant_schema:
            messages.error(
                request,
                'No account found with this email. Please contact your organization administrator.'
            )
            logger.warning(f"Login attempt with non-existent email: {email}")
            return render(request, 'public_router/login.html')

        # Verify credentials in tenant
        user = verify_user_credentials(email, password, tenant_schema)

        if not user:
            messages.error(request, 'Invalid email or password')
            logger.warning(f"Failed login attempt for {email} in tenant {tenant_schema}")
            return render(request, 'public_router/login.html')

        # Create login token
        token = create_login_token(email, tenant_schema)

        # Store in session and redirect to bridge page
        request.session['login_token'] = token
        request.session['tenant_schema'] = tenant_schema
        request.session['tenant_name'] = tenant.display_name

        # Redirect to bridge page on PUBLIC schema
        return redirect('public_router:login_bridge')

    # GET request
    context = {
        'google_oauth_enabled': 'allauth.socialaccount.providers.google' in settings.INSTALLED_APPS,
        'page_title': 'Login to Your Account'
    }

    return render(request, 'public_router/login.html', context)


@never_cache
def login_bridge(request):
    """
    Bridge page that redirects to tenant subdomain
    Runs on public schema
    """
    token = request.session.pop('login_token', None)
    tenant_schema = request.session.pop('tenant_schema', None)
    tenant_name = request.session.pop('tenant_name', None)

    if not token or not tenant_schema:
        messages.error(request, 'Invalid login session')
        return redirect('public_router:login')

    # Generate tenant URL
    tenant_url = get_tenant_login_url(tenant_schema, token)

    if not tenant_url:
        messages.error(request, 'Error redirecting to your account')
        return redirect('public_router:login')

    context = {
        'tenant_url': tenant_url,
        'tenant_name': tenant_name,
        'tenant_schema': tenant_schema,
    }

    return render(request, 'public_router/login_bridge.html', context)


@require_http_methods(["GET", "POST"])
def api_find_tenant(request):
    import json

    if request.method == "GET":
        return JsonResponse({
            "detail": "This endpoint only supports POST requests. Please send a JSON payload with an email."
        }, status=405)

    try:
        data = json.loads(request.body)
        email = data.get('email', '').strip().lower()

        if not email:
            return JsonResponse({'error': 'Email required'}, status=400)

        tenant_schema, tenant = find_user_tenant_by_email(email)

        if tenant:
            tenant_url = get_tenant_login_url(tenant_schema)
            return JsonResponse({
                'exists': True,
                'tenant_url': tenant_url,
                'tenant_name': tenant.display_name,
                'tenant_schema': tenant_schema
            })

        return JsonResponse({
            'exists': False,
            'message': 'No account found with this email'
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in api_find_tenant: {e}")
        return JsonResponse({'error': 'Server error'}, status=500)


