from stores.models import Store

def current_branch(request):
    """
    Provides the current branch to templates.
    Assumes branch is inferred from logged-in user, URL, or subdomain.
    """
    branch = None

    # Example: branch linked to user
    if request.user.is_authenticated:
        # Adjust this depending on your user-branch relationship
        branch = getattr(request.user, 'branch', None)

    # Fallback: main branch of the current company (tenant)
    if not branch and hasattr(request, 'tenant') and request.tenant:
        branch = Store.objects.filter(
            company=request.tenant,
            is_main_branch=True
        ).first()

    context = {
        'branch': branch,
        'branch_name': branch.name if branch else None,
        'branch_location': branch.location if branch else None,
        'branch_allows_sales': branch.allows_sales if branch else True,
        'branch_allows_inventory': branch.allows_inventory if branch else True,
        'branch_manager': branch.manager_name if branch else None,
        'branch_phone': branch.phone if branch else None,
        'branch_email': branch.email if branch else None,
        'branch_timezone': branch.timezone if branch else getattr(request.tenant, 'time_zone', 'UTC'),
        'branch_open_now': branch.is_open_now() if branch else True,
    }
    return context
