from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import PermissionDenied

from .models import Store, StoreAccess
from .forms import StoreForm, StoreStaffAssignmentForm
from accounts.models import AuditLog


@login_required
def store_create(request):
    """Create a new store with proper access control"""


    # Get user's company
    company = request.user.company

    if request.method == 'POST':
        form = StoreForm(request.POST, request.FILES, user=request.user, tenant=company)

        if form.is_valid():
            try:
                with transaction.atomic():
                    # Create store
                    store = form.save(commit=False)
                    store.company = company

                    # Auto-generate code if not provided
                    if not store.code:
                        import uuid
                        store.code = f"ST-{uuid.uuid4().hex[:6].upper()}"

                    store.save()

                    # Automatically add creator as store admin
                    StoreAccess.objects.create(
                        user=request.user,
                        store=store,
                        access_level='admin',
                        can_view_sales=True,
                        can_create_sales=True,
                        can_view_inventory=True,
                        can_manage_inventory=True,
                        can_view_reports=True,
                        can_fiscalize=True,
                        can_manage_staff=True,
                        granted_by=request.user
                    )

                    # If accessible_by_all is checked, create view-only access for all company users
                    if store.accessible_by_all:
                        from accounts.models import CustomUser
                        company_users = CustomUser.objects.filter(
                            company=company,
                            is_active=True
                        ).exclude(id=request.user.id)

                        for user in company_users:
                            StoreAccess.objects.get_or_create(
                                user=user,
                                store=store,
                                defaults={
                                    'access_level': 'view',
                                    'can_view_sales': True,
                                    'can_create_sales': False,
                                    'can_view_inventory': True,
                                    'can_manage_inventory': False,
                                    'can_view_reports': False,
                                    'can_fiscalize': False,
                                    'can_manage_staff': False,
                                    'granted_by': request.user
                                }
                            )

                    # Log the action
                    AuditLog.log(
                        action='store_created',
                        user=request.user,
                        description=f"Created store: {store.name}",
                        store=store,
                        metadata={
                            'store_id': store.id,
                            'store_code': store.code,
                            'accessible_by_all': store.accessible_by_all
                        }
                    )

                    messages.success(
                        request,
                        _('Store "{}" has been created successfully.').format(store.name)
                    )
                    return redirect('stores:store_detail', pk=store.pk)

            except Exception as e:
                messages.error(request, _('Error creating store: {}').format(str(e)))
        else:
            messages.error(request, _('Please correct the errors below.'))
    else:
        form = StoreForm(user=request.user, tenant=company)

    context = {
        'form': form,
        'title': _('Create New Store'),
        'action': 'create',
        'submit_text': _('Create Store'),
        'cancel_url': 'stores:store_list',
    }

    return render(request, 'stores/store_create.html', context)


@login_required
def store_update(request, pk):
    """Update an existing store"""

    store = get_object_or_404(Store, pk=pk)

    # Check if user can edit this store
    if not request.user.can_edit_store(store):
        messages.error(request, _('You do not have permission to edit this store.'))
        raise PermissionDenied

    if request.method == 'POST':
        form = StoreForm(
            request.POST,
            request.FILES,
            instance=store,
            user=request.user,
            tenant=request.user.company
        )

        if form.is_valid():
            try:
                with transaction.atomic():
                    # Track changes
                    old_accessible_by_all = store.accessible_by_all

                    store = form.save()

                    # Handle accessible_by_all changes
                    if store.accessible_by_all and not old_accessible_by_all:
                        # Grant view access to all company users
                        from accounts.models import CustomUser
                        company_users = CustomUser.objects.filter(
                            company=store.company,
                            is_active=True
                        )

                        for user in company_users:
                            StoreAccess.objects.get_or_create(
                                user=user,
                                store=store,
                                defaults={
                                    'access_level': 'view',
                                    'can_view_sales': True,
                                    'can_create_sales': False,
                                    'can_view_inventory': True,
                                    'can_manage_inventory': False,
                                    'can_view_reports': False,
                                    'can_fiscalize': False,
                                    'can_manage_staff': False,
                                    'granted_by': request.user
                                }
                            )
                    elif not store.accessible_by_all and old_accessible_by_all:
                        # Remove view-only access granted by accessible_by_all
                        StoreAccess.objects.filter(
                            store=store,
                            access_level='view',
                            granted_by=request.user
                        ).delete()

                    # Log the action
                    AuditLog.log(
                        action='store_updated',
                        user=request.user,
                        description=f"Updated store: {store.name}",
                        store=store,
                        metadata={
                            'store_id': store.id,
                            'changes': form.changed_data
                        }
                    )

                    messages.success(
                        request,
                        _('Store "{}" has been updated successfully.').format(store.name)
                    )
                    return redirect('stores:store_detail', pk=store.pk)

            except Exception as e:
                messages.error(request, _('Error updating store: {}').format(str(e)))
        else:
            messages.error(request, _('Please correct the errors below.'))
    else:
        form = StoreForm(
            instance=store,
            user=request.user,
            tenant=request.user.company
        )

    context = {
        'form': form,
        'store': store,
        'title': _('Edit Store: {}').format(store.name),
        'action': 'update',
        'submit_text': _('Update Store'),
        'cancel_url': 'stores:store_detail',
        'cancel_url_kwargs': {'pk': store.pk},
    }

    return render(request, 'stores/store_create.html', context)


@login_required
def store_staff_assignment(request, pk):
    """Manage staff assignments for a store"""

    store = get_object_or_404(Store, pk=pk)

    # Check if user can manage staff for this store
    if not request.user.can_manage_store_staff(store):
        messages.error(request, _('You do not have permission to manage staff for this store.'))
        raise PermissionDenied

    if request.method == 'POST':
        form = StoreStaffAssignmentForm(
            request.POST,
            store_instance=store,
            user=request.user
        )

        if form.is_valid():
            try:
                with transaction.atomic():
                    # Get cleaned data
                    add_staff = form.cleaned_data.get('add_staff')
                    remove_staff = form.cleaned_data.get('remove_staff')
                    access_level = form.cleaned_data.get('access_level')

                    # Add new staff
                    added_count = 0
                    for user in add_staff:
                        # Create StoreAccess with specified permissions
                        StoreAccess.objects.create(
                            user=user,
                            store=store,
                            access_level=access_level,
                            can_view_sales=form.cleaned_data.get('can_view_sales', True),
                            can_create_sales=form.cleaned_data.get('can_create_sales', True),
                            can_view_inventory=form.cleaned_data.get('can_view_inventory', True),
                            can_manage_inventory=form.cleaned_data.get('can_manage_inventory', False),
                            can_view_reports=form.cleaned_data.get('can_view_reports', False),
                            can_fiscalize=form.cleaned_data.get('can_fiscalize', False),
                            can_manage_staff=form.cleaned_data.get('can_manage_staff', False),
                            granted_by=request.user
                        )

                        # Log the action
                        AuditLog.log(
                            action='staff_added_to_store',
                            user=request.user,
                            description=f"Added {user.get_full_name()} to {store.name}",
                            store=store,
                            metadata={
                                'added_user_id': user.id,
                                'access_level': access_level
                            }
                        )
                        added_count += 1

                    # Remove staff
                    removed_count = 0
                    for user in remove_staff:
                        # Revoke access
                        access = StoreAccess.objects.filter(
                            user=user,
                            store=store
                        ).first()

                        if access:
                            access.revoke(revoked_by=request.user)
                            removed_count += 1

                    # Success message
                    if added_count > 0 or removed_count > 0:
                        msg_parts = []
                        if added_count > 0:
                            msg_parts.append(_('Added {} staff member(s)').format(added_count))
                        if removed_count > 0:
                            msg_parts.append(_('Removed {} staff member(s)').format(removed_count))

                        messages.success(request, ' and '.join(msg_parts))
                    else:
                        messages.info(request, _('No changes were made.'))

                    return redirect('stores:store_detail', pk=store.pk)

            except Exception as e:
                messages.error(request, _('Error updating staff assignments: {}').format(str(e)))
        else:
            messages.error(request, _('Please correct the errors below.'))
    else:
        form = StoreStaffAssignmentForm(
            store_instance=store,
            user=request.user
        )

    # Get current staff with their access levels
    current_staff = StoreAccess.objects.filter(
        store=store,
        is_active=True
    ).select_related('user')

    context = {
        'form': form,
        'store': store,
        'current_staff': current_staff,
        'title': _('Manage Staff: {}').format(store.name),
    }

    return render(request, 'stores/store_staff_assignment.html', context)


@login_required
def geocode_address_ajax(request):
    """AJAX endpoint for geocoding addresses"""

    if request.method == 'POST':
        address = request.POST.get('address', '')

        if not address:
            return JsonResponse({
                'success': False,
                'error': _('Address is required')
            })

        try:
            from .models import geocode_address
            result = geocode_address(address)

            if result:
                return JsonResponse({
                    'success': True,
                    'latitude': result['latitude'],
                    'longitude': result['longitude'],
                    'display_name': result['display_name']
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': _('Could not find coordinates for this address')
                })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })

    return JsonResponse({
        'success': False,
        'error': _('Invalid request method')
    })