from django.views.decorators.csrf import csrf_protect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.views.generic import CreateView, TemplateView
from django.urls import reverse_lazy
from django.core.cache import cache
from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from django.urls import reverse
from .models import TenantSignupRequest, TenantApprovalWorkflow, TenantNotificationLog
import secrets
import string
import logging
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


def tenant_signup_view(request):
    """Public-facing tenant signup form"""
    if request.method == 'POST':
        form = TenantSignupForm(request.POST)

        if form.is_valid():
            try:
                with transaction.atomic():
                    # Save signup request
                    signup_request = form.save(commit=False)

                    # Capture request metadata
                    signup_request.ip_address = get_client_ip(request)
                    signup_request.user_agent = request.META.get('HTTP_USER_AGENT', '')
                    signup_request.referral_source = request.GET.get('ref', '')

                    signup_request.save()

                    logger.info(f"New tenant signup: {signup_request.company_name}")

                    # Redirect to success page
                    return redirect('public_router:signup_success', request_id=signup_request.request_id)

            except Exception as e:
                logger.error(f"Signup error: {str(e)}")
                messages.error(request, f'An error occurred: {str(e)}')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = TenantSignupForm()

    return render(request, 'public_router/signup.html', {
        'form': form,
        'title': 'Try Primebooks - Sign Up'
    })


def signup_success_view(request, request_id):
    """Show success message after signup"""
    signup_request = get_object_or_404(TenantSignupRequest, request_id=request_id)

    return render(request, 'public_router/signup_success.html', {
        'signup': signup_request,
        'support_email': 'primefocusug@gmail.com',
        'support_phone': '+256 XXX XXX XXX',
        'whatsapp_link': 'https://wa.me/256XXXXXXXXX',
        'title': 'Signup Successful'
    })


def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


# ============================================
# ADMIN VIEWS (for public_admin panel)
# ============================================

@login_required(login_url='public_accounts:login')
def admin_tenant_signups_list(request):
    """List all tenant signup requests"""
    status_filter = request.GET.get('status', 'PENDING')

    signups = TenantSignupRequest.objects.select_related(
        'approval_workflow'
    ).order_by('-created_at')

    if status_filter and status_filter != 'ALL':
        signups = signups.filter(status=status_filter)

    return render(request, 'public_admin/tenant_signups/list.html', {
        'signups': signups,
        'status_filter': status_filter,
        'title': 'Tenant Signups'
    })


@login_required(login_url='public_accounts:login')
def admin_tenant_signup_detail(request, request_id):
    """View and manage individual signup request"""
    signup = get_object_or_404(
        TenantSignupRequest.objects.select_related('approval_workflow'),
        request_id=request_id
    )

    workflow = signup.approval_workflow
    notifications = signup.notification_logs.all()[:10]

    return render(request, 'public_admin/tenant_signups/detail.html', {
        'signup': signup,
        'workflow': workflow,
        'notifications': notifications,
        'title': f'Signup: {signup.company_name}'
    })


@login_required(login_url='public_accounts:login')
def admin_approve_signup(request, request_id):
    """Approve tenant signup and create company"""
    signup = get_object_or_404(TenantSignupRequest, request_id=request_id)

    if request.method == 'POST':
        approval_notes = request.POST.get('approval_notes', '')

        try:
            with transaction.atomic():
                # Update signup status
                signup.status = 'PROCESSING'
                signup.save()

                # Create tenant company
                company = create_tenant_company(signup)

                # Generate login credentials
                password = generate_secure_password()

                # Create admin user in tenant schema
                admin_user = create_tenant_admin_user(company, signup, password)

                # Update signup request
                signup.status = 'COMPLETED'
                signup.tenant_created = True
                signup.created_company_id = company.company_id
                signup.created_schema_name = company.schema_name
                signup.completed_at = timezone.now()
                signup.save()

                # Update workflow
                workflow = signup.approval_workflow
                workflow.reviewed_by = request.user
                workflow.reviewed_at = timezone.now()
                workflow.approval_notes = approval_notes
                workflow.generated_password = password
                workflow.login_url = company.get_absolute_url()
                workflow.save()

                # Send approval email to client
                send_approval_email(signup, password, company)

                messages.success(
                    request,
                    f'Tenant "{company.display_name}" created successfully! '
                    f'Login credentials sent to {signup.admin_email}'
                )

                return redirect('public_admin:tenant_signup_detail', request_id=request_id)

        except Exception as e:
            logger.error(f"Approval failed: {str(e)}")
            signup.status = 'FAILED'
            signup.error_message = str(e)
            signup.retry_count += 1
            signup.save()

            messages.error(request, f'Failed to approve signup: {str(e)}')
            return redirect('public_admin:tenant_signup_detail', request_id=request_id)

    return redirect('public_admin:tenant_signup_detail', request_id=request_id)


def generate_secure_password(length=12):
    """Generate a secure random password"""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(alphabet) for i in range(length))
    return password


def create_tenant_company(signup):
    """Create Company (Tenant) from signup request"""
    from company.models import Company, Domain, SubscriptionPlan
    from django.utils.text import slugify
    from django_tenants.utils import tenant_context

    # Get or create plan
    plan = SubscriptionPlan.objects.filter(name=signup.selected_plan).first()
    if not plan:
        plan = SubscriptionPlan.objects.get(name='FREE')

    # Create company
    company = Company()
    company.name = signup.company_name
    company.trading_name = signup.trading_name or signup.company_name
    company.email = signup.email
    company.phone = signup.phone
    company.physical_address = f"{signup.country}"
    company.plan = plan
    company.status = 'TRIAL' if signup.selected_plan == 'FREE' else 'ACTIVE'
    company.is_trial = signup.selected_plan == 'FREE'

    # Set trial period
    if company.is_trial:
        from datetime import timedelta
        company.trial_ends_at = timezone.now().date() + timedelta(days=plan.trial_days)

    # Generate schema name
    base_schema = slugify(signup.subdomain).replace('-', '_')[:50]
    schema_name = f"tenant_{base_schema}"
    counter = 1
    while Company.objects.filter(schema_name=schema_name).exists():
        schema_name = f"tenant_{base_schema}_{counter}"
        counter += 1

    company.schema_name = schema_name
    company.save()

    logger.info(f"Created company: {company.company_id}")

    # Create domain
    base_domain = getattr(settings, 'BASE_DOMAIN', 'localhost')
    base_domain_clean = base_domain.split(':')[0]
    domain_name = f"{signup.subdomain}.{base_domain_clean}"

    domain = Domain()
    domain.domain = domain_name
    domain.tenant = company
    domain.is_primary = True
    domain.ssl_enabled = True
    domain.save()

    logger.info(f"Created domain: {domain.domain}")

    # Run migrations for tenant
    try:
        from django.core.management import call_command
        call_command('migrate_schemas',
                     schema_name=company.schema_name,
                     interactive=False,
                     verbosity=1)
        logger.info(f"Migrations completed for {company.schema_name}")
    except Exception as e:
        logger.warning(f"Migration warning: {str(e)}")

    return company


def create_tenant_admin_user(company, signup, password):
    """Create admin user in tenant schema"""
    from django_tenants.utils import schema_context
    from accounts.models import CustomUser, Role
    from django.contrib.auth.models import Group

    with schema_context(company.schema_name):
        # Create user
        user = CustomUser.objects.create(
            email=signup.admin_email,
            username=signup.admin_email.split('@')[0],
            first_name=signup.first_name,
            last_name=signup.last_name,
            phone_number=signup.admin_phone,
            company=company,
            is_active=True,
            is_staff=False,
            company_admin=True,
            email_verified=False
        )
        user.set_password(password)
        user.save()

        # Assign Company Admin role
        try:
            admin_group, _ = Group.objects.get_or_create(name='Company Admin')
            admin_role, _ = Role.objects.get_or_create(
                group=admin_group,
                company=company,
                defaults={
                    'description': 'Full administrative access to company',
                    'is_system_role': False,
                    'priority': 100,
                    'is_active': True
                }
            )
            user.groups.add(admin_group)
            user.primary_role = admin_role
            user.save()
        except Exception as e:
            logger.warning(f"Could not assign role: {str(e)}")

        logger.info(f"Created admin user: {user.email}")

        return user


def send_approval_email(signup, password, company):
    """Send approval and login credentials to client"""
    from django.core.mail import send_mail
    from django.template.loader import render_to_string

    try:
        subject = f"🎉 Your Primebooks Account is Ready!"

        context = {
            'signup': signup,
            'company': company,
            'password': password,
            'login_url': company.get_absolute_url(),
            'support_email': 'primefocusug@gmail.com'
        }

        html_message = render_to_string(
            'public_router/emails/approval_notification.html',
            context
        )

        plain_message = render_to_string(
            'public_router/emails/approval_notification.txt',
            context
        )

        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[signup.admin_email],
            html_message=html_message,
            fail_silently=False,
        )

        # Log notification
        TenantNotificationLog.objects.create(
            signup_request=signup,
            notification_type='APPROVAL_TO_CLIENT',
            recipient_email=signup.admin_email,
            subject=subject,
            sent_successfully=True
        )

        # Update workflow
        workflow = signup.approval_workflow
        workflow.approval_notification_sent = True
        workflow.approval_notification_sent_at = timezone.now()
        workflow.save()

        logger.info(f"Approval email sent to {signup.admin_email}")

    except Exception as e:
        logger.error(f"Failed to send approval email: {str(e)}")
        TenantNotificationLog.objects.create(
            signup_request=signup,
            notification_type='APPROVAL_TO_CLIENT',
            recipient_email=signup.admin_email,
            subject=subject,
            sent_successfully=False,
            error_message=str(e)
        )

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


