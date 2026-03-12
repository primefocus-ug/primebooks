import json
import logging
import re
import secrets
import string
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from django.views.decorators.http import require_http_methods
from django.views.generic import CreateView, TemplateView
from django_ratelimit.decorators import ratelimit

from .forms import TenantSignupForm
from .models import TenantSignupRequest, TenantApprovalWorkflow, TenantNotificationLog
from .tasks import create_tenant_async
from company.models import Company, Domain, SubscriptionPlan
from accounts.models import CustomUser

# NOTE: find_user_tenant_by_email, verify_user_credentials, get_tenant_login_url,
# create_login_token, and validate_and_consume_token are all defined later in this
# file. The tenant_lookup import was removed — those local definitions take
# precedence and make the imported names dead code.

logger = logging.getLogger(__name__)


class TutorialsView(TemplateView):
    """Tutorials and help guides page"""
    template_name = 'public_router/tutorials.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'page_title': 'PRIMEBOOKS - Tutorials & Help Guides',
            'meta_description': 'Learn PrimeBooks with comprehensive video tutorials and step-by-step guides for every feature, from setup to advanced reporting.',
            'active_tab': 'tutorials',
        })
        return context

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
                    ref_code = request.GET.get('ref', '') or request.session.get('referral_code', '')
                    signup_request.referral_source = ref_code

                    if ref_code:
                        request.session['referral_code'] = ref_code

                    signup_request.save()

                    # Create the referral tracking record
                    if ref_code:
                        from referral.models import Partner, ReferralSignup
                        partner = Partner.objects.filter(
                            referral_code=ref_code, is_active=True, is_approved=True
                        ).first()
                        ReferralSignup.objects.create(
                            partner=partner,
                            referral_code_used=ref_code,
                            company_name=signup_request.company_name,
                            company_email=signup_request.email,
                            status='pending',
                        )

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
        'support_phone': '+256 785 230 670',
        'whatsapp_link': 'https://wa.me/256785230670',
        'title': 'Signup Successful'
    })


# get_client_ip is defined later in this module (with .strip() for proxy safety)


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
    from django.db.models import Prefetch

    signup = get_object_or_404(
        TenantSignupRequest.objects.select_related('approval_workflow'),
        request_id=request_id
    )

    # Safely get workflow
    workflow = getattr(signup, 'approval_workflow', None)

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
        approval_notes = request.POST.get('approval_notes', '').strip()

        # Get password or generate if empty
        password = request.POST.get('password', '').strip()
        if not password:
            password = generate_secure_password()

        logger.info(f"Processing approval for signup {request_id}")

        try:
            with transaction.atomic():
                # Check if already processing or completed
                if signup.status in ['PROCESSING', 'COMPLETED']:
                    messages.warning(
                        request,
                        f'This signup is already {signup.status.lower()}.'
                    )
                    return redirect('public_admin:tenant_signup_detail', request_id=request_id)

                # Update signup status
                signup.status = 'PROCESSING'
                signup.save(update_fields=['status', 'updated_at'])

                # Get or create approval workflow
                workflow, created = TenantApprovalWorkflow.objects.get_or_create(
                    signup_request=signup,
                    defaults={
                        'generated_password': password,
                    }
                )

                # Update workflow if it already existed
                if not created:
                    workflow.generated_password = password

                # Set reviewer info
                if hasattr(request.user, 'email'):
                    workflow.reviewed_by = request.user
                workflow.reviewed_at = timezone.now()
                workflow.approval_notes = approval_notes
                workflow.save()

            # Queue the async task to create tenant (OUTSIDE transaction)
            logger.info(f"Queueing tenant creation for {signup.request_id}")

            task = create_tenant_async.apply_async(
                args=[str(signup.request_id)],
                countdown=2,  # Wait 2 seconds before starting
            )

            # Store task info in cache
            cache.set(
                f'signup_task_{signup.request_id}',
                {
                    'task_id': task.id,
                    'started_at': timezone.now().isoformat(),
                    'approved_by': request.user.email if hasattr(request.user, 'email') else 'admin',
                },
                timeout=3600  # 1 hour
            )

            messages.success(
                request,
                f'Tenant creation for "{signup.company_name}" has been queued. '
                f'This usually takes 30-60 seconds. Refresh this page to see the status.'
            )

            logger.info(
                f"Admin {request.user.email if hasattr(request.user, 'email') else 'unknown'} "
                f"approved signup {signup.request_id} (task: {task.id})"
            )

            return redirect('public_router:tenant_signup_detail', request_id=request_id)

        except Exception as e:
            logger.error(f"Approval failed: {str(e)}", exc_info=True)

            # Update signup status
            try:
                with transaction.atomic():
                    signup.status = 'FAILED'
                    signup.error_message = f"Approval error: {str(e)}"
                    signup.retry_count += 1
                    signup.save(update_fields=['status', 'error_message', 'retry_count', 'updated_at'])
            except Exception as save_error:
                logger.error(f"Failed to update signup status: {str(save_error)}")

            messages.error(
                request,
                f'Failed to approve signup: {str(e)}'
            )
            return redirect('public_router:tenant_signup_detail', request_id=request_id)

    # GET request - show confirmation page
    context = {
        'signup': signup,
        'title': f'Approve Signup: {signup.company_name}',
        'generated_password': generate_secure_password(),  # Pre-generate for display
    }

    return render(request, 'public_admin/tenant_signups/approve_confirm.html', context)

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

    # Generate schema name with UUID suffix to prevent TOCTOU races.
    # A counter-based loop has a race window between the EXISTS check and INSERT;
    # UUID suffix makes collisions astronomically unlikely without a blocking loop.
    import uuid as _uuid
    base_schema = slugify(signup.subdomain).replace('-', '_')[:40]
    schema_name = f"tenant_{base_schema}_{str(_uuid.uuid4())[:8]}"
    attempts = 0
    while Company.objects.filter(schema_name=schema_name).exists() and attempts < 5:
        schema_name = f"tenant_{base_schema}_{str(_uuid.uuid4())[:8]}"
        attempts += 1
    if Company.objects.filter(schema_name=schema_name).exists():
        raise ValueError(
            f"Could not generate a unique schema name for subdomain '{signup.subdomain}'"
        )
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
        # Use create_user() so the password is hashed atomically on first INSERT.
        # create() + set_password() + save() would leave the user with an unusable
        # password between the create() and save() calls.
        user = CustomUser.objects.create_user(
            email=signup.admin_email,
            username=signup.admin_email.split('@')[0],
            password=password,
            first_name=signup.first_name,
            last_name=signup.last_name,
            phone_number=signup.admin_phone,
            company=company,
            is_active=True,
            is_staff=False,
            company_admin=True,
            email_verified=False
        )

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
            subject=locals().get('subject', 'Approval notification'),  # subject may not be set yet
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
                    created_at__gte=timezone.now() - timedelta(minutes=10)
                ).count()

                if recent_requests >= 2:
                    messages.error(
                        self.request,
                        'You have pending signup requests. Please wait for them to complete.'
                    )
                    return self.form_invalid(form)

                # Create signup request with idempotency key
                password = form.cleaned_data['password']

                # Check for duplicate requests (same subdomain + email in last 24h)
                existing_request = TenantSignupRequest.objects.filter(
                    subdomain=subdomain,
                    admin_email=form.cleaned_data['admin_email'],
                    status__in=['PENDING', 'PROCESSING', 'COMPLETED'],
                    created_at__gte=timezone.now() - timedelta(hours=24)
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
                args=[str(signup_request.request_id)],
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



# Constants
LOGIN_TOKEN_EXPIRY = 300  # 5 minutes
MAX_LOGIN_ATTEMPTS = 5
LOGIN_ATTEMPT_WINDOW = 900  # 15 minutes
BRIDGE_TOKEN_EXPIRY = 60  # 1 minute


def rate_limit_check(identifier, max_attempts, window):
    """
    Check if rate limit is exceeded
    Returns (is_allowed, attempts_left)
    """
    cache_key = f"rate_limit:{identifier}"
    attempts = cache.get(cache_key, 0)

    if attempts >= max_attempts:
        return False, 0

    return True, max_attempts - attempts


def rate_limit_increment(identifier, window):
    """Increment rate limit counter"""
    cache_key = f"rate_limit:{identifier}"
    attempts = cache.get(cache_key, 0)
    cache.set(cache_key, attempts + 1, window)


def rate_limit(max_attempts=5, window=900, block_duration=900):
    """
    Rate limiting decorator
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Use IP + user agent for better fingerprinting
            identifier = f"{get_client_ip(request)}:{request.META.get('HTTP_USER_AGENT', '')[:50]}"

            is_allowed, attempts_left = rate_limit_check(identifier, max_attempts, window)

            if not is_allowed:
                logger.warning(
                    f"Rate limit exceeded for {get_client_ip(request)} on {request.path}"
                )
                if request.content_type == 'application/json':
                    return JsonResponse(
                        {'error': 'Too many attempts. Please try again later.'},
                        status=429
                    )
                messages.error(
                    request,
                    'Too many login attempts. Please try again in 15 minutes.'
                )
                return render(request, 'public_router/rate_limited.html', status=429)

            response = view_func(request, *args, **kwargs)

            # Increment on failed attempts (check for error messages)
            if hasattr(response, 'context_data') or (
                    request.method == 'POST' and
                    hasattr(messages, '_loaded_data')
            ):
                storage = messages.get_messages(request)
                for message in storage:
                    if message.level == messages.ERROR:
                        rate_limit_increment(identifier, window)
                        break
                storage.used = False  # Don't consume messages

            return response

        return wrapper

    return decorator


def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def create_login_token(email, tenant_schema, user_id):
    """
    Create a secure, time-limited login token
    """
    token = secrets.token_urlsafe(32)
    cache_key = f"login_token:{token}"

    token_data = {
        'email': email,
        'tenant_schema': tenant_schema,
        'user_id': user_id,
        'created_at': timezone.now().isoformat(),
        'used': False
    }

    cache.set(cache_key, token_data, LOGIN_TOKEN_EXPIRY)
    logger.info(f"Created login token for user {user_id} in tenant {tenant_schema}")

    return token


def validate_and_consume_token(token):
    """
    Validate token and mark as used (single-use)
    Returns token_data or None if invalid
    """
    if not token or len(token) < 32:
        return None

    cache_key = f"login_token:{token}"
    token_data = cache.get(cache_key)

    if not token_data:
        logger.warning(f"Invalid or expired login token attempted")
        return None

    if token_data.get('used'):
        logger.warning(f"Attempted reuse of login token for {token_data.get('email')}")
        cache.delete(cache_key)
        return None

    # Mark as used
    token_data['used'] = True
    cache.set(cache_key, token_data, 60)  # Keep for 1 minute for logging

    return token_data


def find_user_tenant_by_email(email):
    """
    Find user's tenant by email
    Returns (tenant_schema, tenant_object) or (None, None)
    """
    from company.models import Company
    from django.contrib.auth import get_user_model
    from django_tenants.utils import schema_context

    User = get_user_model()

    try:
        # Search across all active tenants.
        # WARNING: This performs one DB query per tenant — can be slow at scale.
        # Consider caching email→schema mappings or a cross-tenant user index.
        tenants = Company.objects.filter(is_active=True).exclude(schema_name='public')

        for tenant in tenants:
            try:
                with schema_context(tenant.schema_name):
                    if User.objects.filter(email__iexact=email).exists():
                        return tenant.schema_name, tenant
            except Exception as e:
                logger.error(f"Error searching tenant {tenant.schema_name}: {e}")
                continue

        return None, None

    except Exception as e:
        logger.error(f"Error in find_user_tenant_by_email: {e}")
        return None, None


def verify_user_credentials(email, password, tenant_schema):
    """
    Verify user credentials in specific tenant
    Returns User object or None
    """
    from django.contrib.auth import get_user_model, authenticate
    from django_tenants.utils import schema_context

    User = get_user_model()

    try:
        with schema_context(tenant_schema):
            # Check if user exists and is active
            try:
                user = User.objects.get(email__iexact=email)
                if not user.is_active:
                    logger.warning(f"Login attempt for inactive user: {email}")
                    return None
            except User.DoesNotExist:
                return None

            # Authenticate
            authenticated_user = authenticate(
                username=email,
                password=password
            )

            if authenticated_user:
                return authenticated_user

            return None

    except Exception as e:
        logger.error(f"Error verifying credentials in tenant {tenant_schema}: {e}")
        return None


def get_tenant_login_url(tenant_schema, token=None):
    """
    Generate tenant login URL
    """
    from company.models import Company

    try:
        tenant = Company.objects.get(schema_name=tenant_schema)

        # Get domain
        domain = tenant.get_primary_domain()
        if not domain:
            logger.error(f"No domain found for tenant {tenant_schema}")
            return None

        protocol = 'https' if not settings.DEBUG else 'http'
        if settings.DEBUG:
            base_url = f"{protocol}://{domain.domain}:8000"
        else:
            base_url = f"{protocol}://{domain.domain}"

        if token:
            return f"{base_url}/accounts/login/complete/?token={token}"

        return base_url

    except Company.DoesNotExist:
        logger.error(f"Tenant not found: {tenant_schema}")
        return None
    except Exception as e:
        logger.error(f"Error generating tenant URL: {e}")
        return None


@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
@rate_limit(max_attempts=MAX_LOGIN_ATTEMPTS, window=LOGIN_ATTEMPT_WINDOW)
def public_login_router(request):
    """
    Public login router - handles authentication and redirects to tenant
    """
    # Redirect if already authenticated
    if request.user.is_authenticated:
        if hasattr(request, 'tenant') and request.tenant.schema_name != 'public':
            from accounts.views import get_dashboard_url
            return redirect(get_dashboard_url(request.user))

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')

        # Input validation
        if not email or not password:
            messages.error(request, 'Please provide both email and password')
            return render(request, 'public_router/login.html', get_login_context())

        # Basic email format validation
        if '@' not in email or len(email) < 5:
            messages.error(request, 'Invalid email format')
            return render(request, 'public_router/login.html', get_login_context())

        # Password length check (prevent very long passwords DoS)
        if len(password) > 128:
            messages.error(request, 'Invalid credentials')
            return render(request, 'public_router/login.html', get_login_context())

        try:
            # Find user's tenant
            tenant_schema, tenant = find_user_tenant_by_email(email)

            if not tenant_schema:
                # Generic error message to prevent email enumeration
                messages.error(request, 'Invalid credentials')
                logger.warning(
                    f"Login attempt with non-existent email: {email} from IP: {get_client_ip(request)}"
                )
                return render(request, 'public_router/login.html', get_login_context())

            # Verify credentials in tenant schema
            user = verify_user_credentials(email, password, tenant_schema)

            if not user:
                # Generic error message
                messages.error(request, 'Invalid credentials')
                logger.warning(
                    f"Failed login attempt for {email} in tenant {tenant_schema} from IP: {get_client_ip(request)}"
                )
                return render(request, 'public_router/login.html', get_login_context())

            # Create secure login token
            token = create_login_token(email, tenant_schema, user.id)

            # Store minimal data in session
            request.session['login_token'] = token
            request.session['tenant_schema'] = tenant_schema
            request.session['tenant_name'] = tenant.display_name
            request.session['login_initiated_at'] = timezone.now().isoformat()

            # Clear rate limiting on successful login
            identifier = f"{get_client_ip(request)}:{request.META.get('HTTP_USER_AGENT', '')[:50]}"
            cache.delete(f"rate_limit:{identifier}")

            logger.info(
                f"Successful login for {email} in tenant {tenant_schema} from IP: {get_client_ip(request)}"
            )

            # Redirect to bridge page
            return redirect('public_router:login_bridge')

        except Exception as e:
            logger.error(f"Error during login process: {e}", exc_info=True)
            messages.error(request, 'An error occurred. Please try again.')
            return render(request, 'public_router/login.html', get_login_context())

    # GET request
    return render(request, 'public_router/login.html', get_login_context())


def get_login_context():
    """Get context for login page"""
    return {
        'page_title': 'Login to Your Account',
        'show_signup_link': getattr(settings, 'ALLOW_PUBLIC_SIGNUP', True),
    }


@never_cache
@require_http_methods(["GET"])
def login_bridge(request):
    """
    Bridge page that redirects to tenant subdomain
    Runs on public schema - validates session and generates redirect
    """
    token = request.session.get('login_token')
    tenant_schema = request.session.get('tenant_schema')
    tenant_name = request.session.get('tenant_name')
    login_initiated_at = request.session.get('login_initiated_at')

    # Validate session data exists
    if not token or not tenant_schema:
        messages.error(request, 'Invalid login session. Please try again.')
        logger.warning(f"Invalid bridge access from IP: {get_client_ip(request)}")
        return redirect('public_router:login')

    # Check if login session is too old (prevent stale sessions)
    if login_initiated_at:
        try:
            initiated_time = timezone.datetime.fromisoformat(login_initiated_at)
            if timezone.now() - initiated_time > timedelta(seconds=BRIDGE_TOKEN_EXPIRY):
                request.session.flush()
                messages.error(request, 'Login session expired. Please try again.')
                logger.warning(f"Expired bridge session from IP: {get_client_ip(request)}")
                return redirect('public_router:login')
        except (ValueError, TypeError):
            pass

    # Validate token still exists in cache
    cache_key = f"login_token:{token}"
    token_data = cache.get(cache_key)

    if not token_data:
        request.session.flush()
        messages.error(request, 'Login session expired. Please try again.')
        logger.warning(f"Bridge accessed with invalid token from IP: {get_client_ip(request)}")
        return redirect('public_router:login')

    # Generate tenant URL with token
    tenant_url = get_tenant_login_url(tenant_schema, token)

    if not tenant_url:
        request.session.flush()
        messages.error(request, 'Error redirecting to your account. Please try again.')
        logger.error(f"Failed to generate tenant URL for {tenant_schema}")
        return redirect('public_router:login')

    context = {
        'tenant_url': tenant_url,
        'tenant_name': tenant_name,
        'tenant_schema': tenant_schema,
        'auto_redirect': True,
        'redirect_delay': 1000,  # 1 second
    }

    logger.info(f"Bridge redirect to {tenant_schema} from IP: {get_client_ip(request)}")

    return render(request, 'public_router/login_bridge.html', context)


@csrf_exempt  # API endpoint - use other security measures
@require_http_methods(["POST"])
@rate_limit(max_attempts=10, window=300)  # 10 requests per 5 minutes
def api_find_tenant(request):
    """
    API endpoint to find tenant by email
    Used for progressive login flows
    """
    try:
        # Parse JSON body
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse(
                {'error': 'Invalid JSON payload'},
                status=400
            )

        email = data.get('email', '').strip().lower()

        # Validate email
        if not email:
            return JsonResponse(
                {'error': 'Email is required'},
                status=400
            )

        if '@' not in email or len(email) < 5 or len(email) > 254:
            return JsonResponse(
                {'error': 'Invalid email format'},
                status=400
            )

        # Find tenant
        tenant_schema, tenant = find_user_tenant_by_email(email)

        if tenant:
            tenant_url = get_tenant_login_url(tenant_schema)

            if not tenant_url:
                logger.error(f"Could not generate URL for tenant {tenant_schema}")
                return JsonResponse(
                    {'error': 'Unable to generate tenant URL'},
                    status=500
                )

            logger.info(f"API tenant lookup successful for {email}")

            return JsonResponse({
                'exists': True,
                'tenant_url': tenant_url,
                'tenant_name': tenant.display_name,
                'tenant_schema': tenant_schema
            })

        # Don't reveal whether email exists - return generic response
        logger.info(f"API tenant lookup - email not found: {email}")

        return JsonResponse({
            'exists': False,
            'message': 'Please enter your password to continue'
        })

    except Exception as e:
        logger.error(f"Error in api_find_tenant: {e}", exc_info=True)
        return JsonResponse(
            {'error': 'An error occurred processing your request'},
            status=500
        )


# Additional utility view for completing login on tenant side
@never_cache
@csrf_protect
@require_http_methods(["GET"])
def complete_tenant_login(request):
    """
    Complete login on tenant subdomain
    This view runs on the TENANT schema
    """
    from django.contrib.auth import login

    token = request.GET.get('token')

    if not token:
        messages.error(request, 'Invalid login link')
        return redirect('login')

    # Validate and consume token
    token_data = validate_and_consume_token(token)

    if not token_data:
        messages.error(request, 'Invalid or expired login link. Please log in again.')
        logger.warning(f"Invalid token used from IP: {get_client_ip(request)}")
        return redirect('login')

    # Verify we're on the correct tenant
    if hasattr(request, 'tenant'):
        if request.tenant.schema_name != token_data.get('tenant_schema'):
            logger.error(
                f"Token tenant mismatch: expected {token_data.get('tenant_schema')}, "
                f"got {request.tenant.schema_name}"
            )
            messages.error(request, 'Invalid login session')
            return redirect('login')

    # Get user and log them in
    from django.contrib.auth import get_user_model
    User = get_user_model()

    try:
        user = User.objects.get(
            id=token_data.get('user_id'),
            email__iexact=token_data.get('email'),
            is_active=True
        )

        # Log the user in
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')

        logger.info(
            f"User {user.email} successfully logged in to tenant "
            f"{request.tenant.schema_name} from IP: {get_client_ip(request)}"
        )

        # Redirect to dashboard
        from accounts.views import get_dashboard_url
        return redirect(get_dashboard_url(user))

    except User.DoesNotExist:
        logger.error(
            f"User not found for token: user_id={token_data.get('user_id')}, "
            f"email={token_data.get('email')}"
        )
        messages.error(request, 'User account not found or has been disabled')
        return redirect('login')

    except Exception as e:
        logger.error(f"Error completing tenant login: {e}", exc_info=True)
        messages.error(request, 'An error occurred. Please try again.')
        return redirect('login')