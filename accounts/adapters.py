from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.shortcuts import redirect
from django.urls import reverse
from public_router.tenant_lookup import find_user_tenant_by_email, create_login_token


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):

    def pre_social_login(self, request, sociallogin):
        """
        Handle tenant routing before social login completes
        """
        # Get email from social account
        email = sociallogin.account.extra_data.get('email')

        if email and not sociallogin.is_existing:
            # For new users, you might want different logic
            # For now, we'll check if they exist in any tenant
            tenant_schema, tenant = find_user_tenant_by_email(email)

            if tenant_schema:
                # Store tenant info in session
                request.session['pending_tenant_schema'] = tenant_schema
                request.session['pending_tenant_name'] = tenant.display_name

    def get_login_redirect_url(self, request):
        """
        Redirect to appropriate tenant after successful social login
        """
        # Check if we have a pending tenant from pre_social_login
        tenant_schema = request.session.pop('pending_tenant_schema', None)

        if tenant_schema and request.user.is_authenticated:
            # Create login token
            token = create_login_token(
                request.user.email,
                tenant_schema,
                expires_in=300
            )

            # Get tenant URL
            from public_router.tenant_lookup import get_tenant_login_url
            tenant_url = get_tenant_login_url(tenant_schema, token)

            if tenant_url:
                return tenant_url

        # Fallback to default
        from accounts.views import get_dashboard_url
        return get_dashboard_url(request.user)