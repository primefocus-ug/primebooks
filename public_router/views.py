from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.conf import settings
from django.views.generic import CreateView, TemplateView
from django.urls import reverse_lazy
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from django_tenants.utils import schema_context
from django.core.cache import cache
import logging
from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator

from .forms import TenantSignupForm
from .tasks import create_tenant_async
from .models import TenantSignupRequest
from company.models import Company, Domain, SubscriptionPlan
from accounts.models import CustomUser


from .tenant_lookup import (
    find_user_tenant_by_email,
    verify_user_credentials,
    get_tenant_login_url,
    create_login_token,
    verify_login_token
)

logger = logging.getLogger(__name__)



@method_decorator(ratelimit(key='ip', rate='5/h', method='POST'), name='post')
@method_decorator(ratelimit(key='ip', rate='10/h', method='GET'), name='get')
class TenantSignupView(CreateView):
    model = TenantSignupRequest
    form_class = TenantSignupForm
    template_name = 'public_router/signup.html'
    success_url = reverse_lazy('public_router:signup_processing')

    def dispatch(self, request, *args, **kwargs):
        # Check if rate limited
        from django_ratelimit.exceptions import Ratelimited

        try:
            response = super().dispatch(request, *args, **kwargs)
            return response
        except Ratelimited:
            messages.error(
                request,
                'You have exceeded the signup rate limit. Please try again in an hour.'
            )
            return redirect('public_router:signup')

    def form_valid(self, form):
        try:
            # Use atomic transaction with timeout
            with transaction.atomic():
                # Double-check subdomain with database-level lock
                subdomain = form.cleaned_data['subdomain']
                schema_name = f"tenant_{subdomain}"

                # Use SELECT FOR UPDATE NOWAIT to fail fast instead of blocking
                try:
                    existing = Company.objects.select_for_update(nowait=True).filter(
                        schema_name=schema_name
                    ).exists()

                    if existing:
                        messages.error(
                            self.request,
                            'This subdomain was just taken. Please choose another.'
                        )
                        return self.form_invalid(form)

                except Exception as e:
                    # Lock couldn't be acquired (another request is processing this subdomain)
                    logger.warning(f"Lock conflict for subdomain {subdomain}: {str(e)}")
                    messages.error(
                        self.request,
                        'This subdomain is currently being processed. Please try a different one.'
                    )
                    return self.form_invalid(form)

                # Check for duplicate pending requests from same IP
                ip = self.get_client_ip()
                recent_requests = TenantSignupRequest.objects.filter(
                    ip_address=ip,
                    status__in=['PENDING', 'PROCESSING'],
                    created_at__gte=timezone.now() - timezone.timedelta(minutes=10)
                ).count()

                if recent_requests >= 2:
                    messages.error(
                        self.request,
                        'You have pending signup requests. Please wait for them to complete.'
                    )
                    return self.form_invalid(form)

                # Create signup request with idempotency key
                password = form.cleaned_data['password']

                # Generate idempotency key from email + subdomain
                import hashlib
                idempotency_key = hashlib.md5(
                    f"{form.cleaned_data['admin_email']}:{subdomain}".encode()
                ).hexdigest()

                # Check for duplicate requests with same idempotency key
                existing_request = TenantSignupRequest.objects.filter(
                    subdomain=subdomain,
                    admin_email=form.cleaned_data['admin_email'],
                    status__in=['PENDING', 'PROCESSING', 'COMPLETED'],
                    created_at__gte=timezone.now() - timezone.timedelta(hours=24)
                ).first()

                if existing_request:
                    if existing_request.status == 'COMPLETED':
                        messages.info(
                            self.request,
                            f'A workspace with this subdomain already exists. '
                            f'Please login or use a different subdomain.'
                        )
                    else:
                        messages.info(
                            self.request,
                            'Your signup request is already being processed. '
                            'Please check your email.'
                        )
                        self.request.session['signup_request_id'] = str(existing_request.request_id)
                        return redirect('public_router:signup_processing')

                # Create new signup request
                signup_request = form.save(commit=False)
                signup_request.status = 'PENDING'
                signup_request.ip_address = ip
                signup_request.user_agent = self.request.META.get('HTTP_USER_AGENT', '')[:500]
                signup_request.referral_source = self.request.GET.get('ref', '')[:100]
                signup_request.save()

            # Queue async tenant creation (outside transaction)
            task = create_tenant_async.apply_async(
                args=[str(signup_request.request_id), password],
                countdown=2,  # Wait 2 seconds before starting
                expires=600,  # Task expires in 10 minutes
            )

            # Store task ID for tracking
            cache.set(
                f'signup_task_{signup_request.request_id}',
                task.id,
                timeout=3600
            )

            # Store request ID in session
            self.request.session['signup_request_id'] = str(signup_request.request_id)
            self.request.session.set_expiry(600)  # 10 minutes

            messages.success(
                self.request,
                'Your workspace is being created! This usually takes 30-60 seconds.'
            )

            logger.info(
                f"Signup request created: {signup_request.request_id} "
                f"(subdomain: {subdomain}, task: {task.id})"
            )

            return super().form_valid(form)

        except Exception as e:
            logger.error(
                f"Signup request creation failed: {str(e)}",
                exc_info=True,
                extra={
                    'subdomain': form.cleaned_data.get('subdomain'),
                    'email': form.cleaned_data.get('admin_email'),
                }
            )
            messages.error(
                self.request,
                'Sorry, there was an error processing your request. Please try again.'
            )
            return self.form_invalid(form)

    def get_client_ip(self):
        """Get client IP address with proxy support"""
        x_forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            # Get the first IP (client IP)
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = self.request.META.get('REMOTE_ADDR')
        return ip

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['plans'] = SubscriptionPlan.objects.filter(
            is_active=True
        ).order_by('sort_order')
        context['base_domain'] = getattr(settings, 'BASE_DOMAIN', 'localhost')
        return context


class SignupProcessingView(TemplateView):
    """Show processing status with real-time updates"""
    template_name = 'public_router/signup_processing.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request_id = self.request.session.get('signup_request_id')

        if request_id:
            try:
                signup_request = TenantSignupRequest.objects.get(
                    request_id=request_id
                )
                context['signup_request'] = signup_request
            except TenantSignupRequest.DoesNotExist:
                pass

        return context


class CheckSignupStatusView(TemplateView):
    """AJAX endpoint to check signup status"""

    def get(self, request, *args, **kwargs):
        from django.http import JsonResponse

        request_id = request.GET.get('request_id') or request.session.get('signup_request_id')

        if not request_id:
            return JsonResponse({'error': 'No request ID provided'}, status=400)

        try:
            signup_request = TenantSignupRequest.objects.get(request_id=request_id)

            response_data = {
                'status': signup_request.status,
                'company_name': signup_request.company_name,
                'subdomain': signup_request.subdomain,
            }

            if signup_request.status == 'COMPLETED':
                response_data['redirect_url'] = f"https://{signup_request.subdomain}.{self.get_base_domain()}/login/"
                response_data['company_id'] = signup_request.created_company_id

            elif signup_request.status == 'FAILED':
                response_data['error_message'] = signup_request.error_message or 'Unknown error occurred'

            return JsonResponse(response_data)

        except TenantSignupRequest.DoesNotExist:
            return JsonResponse({'error': 'Signup request not found'}, status=404)

    def get_base_domain(self):
        from django.conf import settings
        return getattr(settings, 'BASE_DOMAIN', 'localhost')

@method_decorator(ratelimit(key='ip', rate='30/m', method='GET'), name='get')

class CheckSubdomainView(TemplateView):
    """
    AJAX endpoint to check subdomain availability.
    Rate limited to 30 requests per minute per IP.
    """

    def get(self, request, *args, **kwargs):
        from django.http import JsonResponse
        from django_ratelimit.exceptions import Ratelimited

        try:
            subdomain = request.GET.get('subdomain', '').lower().strip()

            if not subdomain:
                return JsonResponse({
                    'available': False,
                    'message': 'Subdomain is required'
                }, status=400)

            # Quick validation
            import re
            if not re.match(r'^[a-z0-9-]{3,63}$', subdomain):
                return JsonResponse({
                    'available': False,
                    'message': 'Invalid subdomain format'
                })

            # Check cache first
            cache_key = f'subdomain_check_{subdomain}'
            cached_result = cache.get(cache_key)

            if cached_result:
                return JsonResponse(cached_result)

            # Reserved subdomains
            reserved = ['www', 'api', 'admin', 'app', 'mail', 'ftp', 'localhost',
                        'staging', 'dev', 'test', 'demo', 'public', 'static', 'media',
                        'blog', 'support', 'help', 'docs', 'status', 'cdn', 'assets']

            if subdomain in reserved:
                result = {
                    'available': False,
                    'message': 'This subdomain is reserved'
                }
                cache.set(cache_key, result, 300)
                return JsonResponse(result)

            # Check database
            schema_name = f"tenant_{subdomain}"
            exists = Company.objects.filter(schema_name=schema_name).exists()

            if exists:
                result = {
                    'available': False,
                    'message': 'This subdomain is already taken'
                }
                cache.set(cache_key, result, 300)
                return JsonResponse(result)

            # Check pending signups
            pending = TenantSignupRequest.objects.filter(
                subdomain=subdomain,
                status__in=['PENDING', 'PROCESSING']
            ).exists()

            if pending:
                result = {
                    'available': False,
                    'message': 'This subdomain is being processed'
                }
                cache.set(cache_key, result, 60)  # Short cache
                return JsonResponse(result)

            # Available
            from django.conf import settings
            base_domain = getattr(settings, 'BASE_DOMAIN', 'localhost')

            result = {
                'available': True,
                'message': 'This subdomain is available',
                'preview_url': f"https://{subdomain}.{base_domain}"
            }
            cache.set(cache_key, result, 60)  # Cache for 1 minute

            return JsonResponse(result)

        except Ratelimited:
            return JsonResponse({
                'error': 'Too many requests. Please slow down.'
            }, status=429)
        except Exception as e:
            logger.error(f"Subdomain check error: {str(e)}")
            return JsonResponse({
                'error': 'An error occurred'
            }, status=500)

class SignupSuccessView(TemplateView):
    template_name = 'public_router/signup_success.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # You can add any additional context data here if needed
        context['message'] = 'Your tenant account has been created successfully!'
        return context


class HealthCheckView(TemplateView):
    """
    Health check endpoint for monitoring.
    Returns 200 if healthy, 503 if issues detected.
    """

    def get(self, request, *args, **kwargs):
        from django.http import JsonResponse
        from .monitoring import check_signup_health

        health = check_signup_health()

        status_code = 200 if health['healthy'] else 503

        return JsonResponse({
            'status': 'healthy' if health['healthy'] else 'unhealthy',
            'timestamp': timezone.now().isoformat(),
            'issues': health['issues'],
            'metrics': health['metrics'],
        }, status=status_code)

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


