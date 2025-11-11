from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db.models import Sum, Q, Count, Avg
from django.utils import timezone
from datetime import timedelta
from datetime import datetime
from decimal import Decimal
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from .models import Expense, ExpenseCategory, ExpenseAttachment, ExpenseComment
from .forms import (
    ExpenseForm, ExpenseApprovalForm, ExpensePaymentForm,
    ExpenseFilterForm, ExpenseCommentForm, BulkExpenseActionForm
)
from .utils import (
    get_expense_statistics, get_budget_analysis,
    validate_expense_approval, export_expenses_to_excel
)
from accounts.utils import log_action


@login_required
def expense_list(request):
    """List expenses with filtering and pagination"""
    expenses = Expense.objects.select_related(
        'category', 'created_by', 'store', 'approved_by'
    ).filter(created_by=request.user)

    # Apply filters
    filter_form = ExpenseFilterForm(request.GET)
    if filter_form.is_valid():
        if filter_form.cleaned_data.get('status'):
            expenses = expenses.filter(status=filter_form.cleaned_data['status'])
        if filter_form.cleaned_data.get('category'):
            expenses = expenses.filter(category=filter_form.cleaned_data['category'])
        if filter_form.cleaned_data.get('date_from'):
            expenses = expenses.filter(expense_date__gte=filter_form.cleaned_data['date_from'])
        if filter_form.cleaned_data.get('date_to'):
            expenses = expenses.filter(expense_date__lte=filter_form.cleaned_data['date_to'])
        if filter_form.cleaned_data.get('search'):
            search = filter_form.cleaned_data['search']
            expenses = expenses.filter(
                Q(expense_number__icontains=search) |
                Q(title__icontains=search) |
                Q(description__icontains=search) |
                Q(vendor_name__icontains=search)
            )

    # Pagination
    paginator = Paginator(expenses.order_by('-expense_date'), 20)
    page = request.GET.get('page')

    try:
        expenses_page = paginator.page(page)
    except PageNotAnInteger:
        expenses_page = paginator.page(1)
    except EmptyPage:
        expenses_page = paginator.page(paginator.num_pages)

    # Stats
    stats = {
        'total': expenses.count(),
        'draft': expenses.filter(status='DRAFT').count(),
        'submitted': expenses.filter(status='SUBMITTED').count(),
        'approved': expenses.filter(status='APPROVED').count(),
        'rejected': expenses.filter(status='REJECTED').count(),
        'paid': expenses.filter(status='PAID').count(),
        'total_amount': expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
    }

    context = {
        'expenses': expenses_page,
        'categories': ExpenseCategory.objects.filter(is_active=True),
        'stats': stats,
        'filter_form': filter_form,
        'filters': request.GET.dict()
    }

    return render(request, 'expenses/expense_list.html', context)


@login_required
@transaction.atomic
def expense_create(request):
    """Create new expense with proper error handling"""
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.created_by = request.user

            # Set store if user has one
            if hasattr(request.user, 'store') and request.user.store:
                expense.store = request.user.store

            # Determine status based on action
            action = request.POST.get('action', 'draft')
            if action == 'submit':
                expense.status = 'SUBMITTED'
                expense.submitted_at = timezone.now()

                # Check if auto-approval applies
                if expense.category.approval_threshold and \
                        expense.amount < expense.category.approval_threshold:
                    expense.status = 'APPROVED'
                    expense.approved_by = request.user
                    expense.approved_at = timezone.now()
            else:
                expense.status = 'DRAFT'

            expense.save()

            # Handle multiple file attachments
            files = request.FILES.getlist('attachments')
            for file in files:
                ExpenseAttachment.objects.create(
                    expense=expense,
                    file=file,
                    uploaded_by=request.user
                )

            # Log action
            log_action(
                request,
                'expense_created',
                f'Created expense: {expense.expense_number}',
                content_object=expense
            )

            if action == 'submit':
                messages.success(
                    request,
                    f'Expense {expense.expense_number} created and submitted successfully!'
                )
            else:
                messages.success(
                    request,
                    f'Expense {expense.expense_number} saved as draft!'
                )

            return redirect('expenses:expense_detail', pk=expense.pk)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        # Pre-fill expense date with today
        initial = {'expense_date': timezone.now().date()}
        form = ExpenseForm(initial=initial, user=request.user)

    context = {
        'form': form,
        'categories': ExpenseCategory.objects.filter(is_active=True).order_by('sort_order', 'name')
    }

    return render(request, 'expenses/expense_form.html', context)


@login_required
def expense_detail(request, pk):
    """View expense details with permission checks"""
    expense = get_object_or_404(
        Expense.objects.select_related(
            'category', 'created_by', 'approved_by', 'paid_by', 'store'
        ).prefetch_related('attachments', 'comments'),
        pk=pk
    )

    # Check permissions
    can_view = (
            expense.created_by == request.user or
            request.user.has_perm('expenses.view_all_expenses') or
            request.user.has_perm('expenses.approve_expense')
    )

    if not can_view:
        messages.error(request, "You don't have permission to view this expense.")
        return redirect('expenses:expense_list')

    attachments = expense.attachments.all()
    comments = expense.comments.select_related('user').order_by('created_at')

    # Filter internal comments for non-approvers
    if not request.user.has_perm('expenses.approve_expense'):
        comments = comments.filter(is_internal=False)

    context = {
        'expense': expense,
        'attachments': attachments,
        'comments': comments,
        'can_approve': request.user.has_perm('expenses.approve_expense') and expense.created_by != request.user,
        'can_pay': request.user.has_perm('expenses.pay_expense'),
        'can_edit': expense.status == 'DRAFT' and expense.created_by == request.user
    }

    return render(request, 'expenses/expense_detail.html', context)


@login_required
@require_http_methods(["POST"])
def expense_edit(request, pk):
    """Edit existing expense (only drafts)"""
    expense = get_object_or_404(Expense, pk=pk, created_by=request.user)

    if expense.status != 'DRAFT':
        messages.error(request, "Only draft expenses can be edited.")
        return redirect('expenses:expense_detail', pk=pk)

    form = ExpenseForm(request.POST, request.FILES, instance=expense, user=request.user)
    if form.is_valid():
        expense = form.save()

        # Handle new attachments
        files = request.FILES.getlist('attachments')
        for file in files:
            ExpenseAttachment.objects.create(
                expense=expense,
                file=file,
                uploaded_by=request.user
            )

        log_action(request, 'expense_updated', f'Updated expense: {expense.expense_number}', content_object=expense)
        messages.success(request, 'Expense updated successfully!')
        return redirect('expenses:expense_detail', pk=pk)

    return render(request, 'expenses/expense_form.html', {'form': form, 'expense': expense})


@login_required
@require_http_methods(["POST"])
def expense_submit(request, pk):
    """Submit expense for approval with validation"""
    expense = get_object_or_404(Expense, pk=pk, created_by=request.user)

    if expense.status != 'DRAFT':
        messages.error(request, "Only draft expenses can be submitted.")
        return redirect('expenses:expense_detail', pk=pk)

    # Validate required fields
    if not expense.attachments.exists() and expense.category.requires_approval:
        messages.warning(request, "Please attach receipts before submitting for approval.")
        return redirect('expenses:expense_detail', pk=pk)

    try:
        expense.submit_for_approval()

        log_action(
            request,
            'expense_submitted',
            f'Submitted expense {expense.expense_number} for approval',
            content_object=expense
        )

        messages.success(request, f'Expense {expense.expense_number} submitted for approval!')
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@permission_required('expenses.approve_expense', raise_exception=True)
@require_http_methods(["POST"])
def expense_approve(request, pk):
    """Approve expense with validation"""
    expense = get_object_or_404(Expense, pk=pk)

    # Validate approval
    validation = validate_expense_approval(expense, request.user)

    if validation['errors']:
        for error in validation['errors']:
            messages.error(request, error)
        return redirect('expenses:expense_detail', pk=pk)

    try:
        expense.approve(request.user)

        log_action(
            request,
            'expense_approved',
            f'Approved expense {expense.expense_number}',
            content_object=expense
        )

        messages.success(request, f'Expense {expense.expense_number} approved successfully!')

        # Send notification via WebSocket
        send_expense_update_notification(expense, 'approved')

    except ValueError as e:
        messages.error(request, str(e))

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@permission_required('expenses.reject_expense', raise_exception=True)
@require_http_methods(["POST"])
def expense_reject(request, pk):
    """Reject expense with reason"""
    expense = get_object_or_404(Expense, pk=pk)

    reason = request.POST.get('reason', '').strip()

    if not reason:
        messages.error(request, 'Rejection reason is required.')
        return redirect('expenses:expense_detail', pk=pk)

    if len(reason) < 10:
        messages.error(request, 'Please provide a detailed rejection reason (at least 10 characters).')
        return redirect('expenses:expense_detail', pk=pk)

    try:
        expense.reject(request.user, reason)

        log_action(
            request,
            'expense_rejected',
            f'Rejected expense {expense.expense_number}: {reason}',
            content_object=expense
        )

        messages.success(request, f'Expense {expense.expense_number} rejected.')

        # Send notification
        send_expense_update_notification(expense, 'rejected')

    except ValueError as e:
        messages.error(request, str(e))

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@permission_required('expenses.pay_expense', raise_exception=True)
@require_http_methods(["POST"])
def expense_mark_paid(request, pk):
    """Mark expense as paid"""
    expense = get_object_or_404(Expense, pk=pk)

    payment_method = request.POST.get('payment_method')
    payment_reference = request.POST.get('payment_reference', '')

    if not payment_method:
        messages.error(request, 'Payment method is required.')
        return redirect('expenses:expense_detail', pk=pk)

    try:
        expense.mark_as_paid(request.user, payment_method, payment_reference)

        log_action(
            request,
            'expense_paid',
            f'Marked expense {expense.expense_number} as paid',
            content_object=expense,
            metadata={
                'payment_method': payment_method,
                'payment_reference': payment_reference
            }
        )

        messages.success(request, f'Expense {expense.expense_number} marked as paid!')

        # Send notification
        send_expense_update_notification(expense, 'paid')

    except ValueError as e:
        messages.error(request, str(e))

    return redirect('expenses:expense_detail', pk=pk)


@login_required
def expense_dashboard(request):
    """Enhanced expense dashboard with more insights"""
    # Date range (current month by default)
    today = timezone.now().date()
    start_of_month = today.replace(day=1)

    # User's expenses
    user_expenses = Expense.objects.filter(created_by=request.user)

    # Stats for current month
    month_expenses = user_expenses.filter(
        expense_date__gte=start_of_month,
        expense_date__lte=today
    )

    stats = {
        'total_this_month': month_expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'pending_approval': user_expenses.filter(status='SUBMITTED').count(),
        'approved_unpaid': user_expenses.filter(status='APPROVED').count(),
        'total_paid': user_expenses.filter(status='PAID').count(),
        'rejected': user_expenses.filter(status='REJECTED').count(),
        'average_expense': month_expenses.aggregate(Avg('amount'))['amount__avg'] or Decimal('0')
    }

    # Category breakdown for current month
    category_breakdown = month_expenses.values(
        'category__name', 'category__color_code'
    ).annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')[:5]

    # Recent expenses
    recent_expenses = user_expenses.select_related(
        'category', 'store'
    ).order_by('-created_at')[:10]

    # Pending approvals (if user can approve)
    pending_approvals = []
    if request.user.has_perm('expenses.approve_expense'):
        pending_approvals = Expense.objects.filter(
            status='SUBMITTED'
        ).exclude(
            created_by=request.user
        ).select_related('created_by', 'category').order_by('-submitted_at')[:10]

    # Budget analysis
    budget_analysis = []
    if request.user.has_perm('expenses.view_all_expenses'):
        budget_analysis = get_budget_analysis()[:5]

    context = {
        'stats': stats,
        'category_breakdown': category_breakdown,
        'recent_expenses': recent_expenses,
        'pending_approvals': pending_approvals,
        'budget_analysis': budget_analysis
    }

    return render(request, 'expenses/dashboard.html', context)


@login_required
@require_http_methods(["POST"])
def expense_add_comment(request, pk):
    """Add comment to expense"""
    expense = get_object_or_404(Expense, pk=pk)

    # Check if user can view this expense
    can_view = (
            expense.created_by == request.user or
            request.user.has_perm('expenses.view_all_expenses') or
            request.user.has_perm('expenses.approve_expense')
    )

    if not can_view:
        messages.error(request, "You don't have permission to comment on this expense.")
        return redirect('expenses:expense_list')

    comment_text = request.POST.get('comment', '').strip()
    is_internal = request.POST.get('is_internal') == 'on'

    if comment_text:
        # Only approvers can make internal comments
        if is_internal and not request.user.has_perm('expenses.approve_expense'):
            is_internal = False

        comment = ExpenseComment.objects.create(
            expense=expense,
            user=request.user,
            comment=comment_text,
            is_internal=is_internal
        )

        messages.success(request, 'Comment added successfully!')

        # Send real-time notification
        send_comment_notification(expense, comment)
    else:
        messages.error(request, 'Comment cannot be empty.')

    return redirect('expenses:expense_detail', pk=pk)


@login_required
@require_http_methods(["POST"])
def expense_delete_attachment(request, pk, attachment_id):
    """Delete an attachment"""
    expense = get_object_or_404(Expense, pk=pk, created_by=request.user)
    attachment = get_object_or_404(ExpenseAttachment, pk=attachment_id, expense=expense)

    if expense.status != 'DRAFT':
        messages.error(request, "Cannot delete attachments from submitted expenses.")
        return redirect('expenses:expense_detail', pk=pk)

    attachment.file.delete()
    attachment.delete()

    messages.success(request, 'Attachment deleted successfully.')
    return redirect('expenses:expense_detail', pk=pk)


@login_required
@permission_required('expenses.view_all_expenses', raise_exception=True)
def expense_reports(request):
    """View expense reports and analytics"""
    from .utils import get_expense_statistics, get_expense_insights

    # Get date range from request
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    # Get statistics
    stats = get_expense_statistics(
        user=None if request.user.has_perm('expenses.view_all_expenses') else request.user,
        date_from=date_from,
        date_to=date_to
    )

    # Get insights
    insights = get_expense_insights(
        user=None if request.user.has_perm('expenses.view_all_expenses') else request.user
    )

    # Budget analysis
    budget_analysis = get_budget_analysis()

    context = {
        'stats': stats,
        'insights': insights,
        'budget_analysis': budget_analysis,
        'date_from': date_from,
        'date_to': date_to
    }

    return render(request, 'expenses/reports.html', context)


@login_required
def expense_export(request):
    """Export expenses to Excel"""
    from .tasks import export_expenses_to_csv

    filters = request.GET.dict()

    # Queue export task
    export_expenses_to_csv.delay(request.user.id, filters)

    messages.success(request, 'Export has been queued. You will receive a notification when it\'s ready.')
    return redirect('expenses:expense_list')


# Helper functions for WebSocket notifications
def send_expense_update_notification(expense, update_type):
    """Send real-time update via WebSocket"""
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    channel_layer = get_channel_layer()

    # Notify expense creator
    async_to_sync(channel_layer.group_send)(
        f'expense_user_{expense.created_by.id}',
        {
            'type': 'expense_update',
            'expense_id': expense.id,
            'expense_number': expense.expense_number,
            'status': expense.status,
            'message': f'Your expense has been {update_type}',
            'timestamp': timezone.now().isoformat()
        }
    )

    # Notify approvers if submitted
    if update_type == 'submitted':
        async_to_sync(channel_layer.group_send)(
            'expense_approvers',
            {
                'type': 'expense_update',
                'expense_id': expense.id,
                'expense_number': expense.expense_number,
                'status': expense.status,
                'message': f'New expense submitted by {expense.created_by.get_full_name()}',
                'timestamp': timezone.now().isoformat()
            }
        )


def send_comment_notification(expense, comment):
    """Send notification about new comment"""
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        f'expense_user_{expense.created_by.id}',
        {
            'type': 'expense_comment',
            'expense_id': expense.id,
            'comment': comment.comment[:100],
            'user': comment.user.get_full_name(),
            'timestamp': timezone.now().isoformat()
        }
    )

# Add these to existing views.py

@login_required
def expense_edit(request, pk):
    """Edit existing expense"""
    expense = get_object_or_404(Expense, pk=pk, created_by=request.user)
    
    if expense.status != 'DRAFT':
        messages.error(request, "Only draft expenses can be edited.")
        return redirect('expenses:expense_detail', pk=pk)
    
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES, instance=expense, user=request.user)
        if form.is_valid():
            expense = form.save()
            
            # Handle new attachments
            files = request.FILES.getlist('attachments')
            for file in files:
                ExpenseAttachment.objects.create(
                    expense=expense,
                    file=file,
                    uploaded_by=request.user
                )
            
            log_action(request, 'expense_updated', f'Updated expense: {expense.expense_number}', content_object=expense)
            messages.success(request, 'Expense updated successfully!')
            return redirect('expenses:expense_detail', pk=pk)
    else:
        form = ExpenseForm(instance=expense, user=request.user)
    
    context = {
        'form': form,
        'expense': expense,
        'categories': ExpenseCategory.objects.filter(is_active=True).order_by('sort_order', 'name')
    }
    return render(request, 'expenses/expense_form.html', context)

@login_required
@require_http_methods(["POST"])
def expense_delete(request, pk):
    """Delete expense (only drafts)"""
    expense = get_object_or_404(Expense, pk=pk, created_by=request.user)
    
    if expense.status != 'DRAFT':
        messages.error(request, "Only draft expenses can be deleted.")
        return redirect('expenses:expense_detail', pk=pk)
    
    expense_number = expense.expense_number
    expense.delete()
    
    log_action(request, 'expense_deleted', f'Deleted expense: {expense_number}')
    messages.success(request, f'Expense {expense_number} deleted successfully!')
    
    return redirect('expenses:expense_list')

@login_required
def expense_bulk_action(request):
    """Handle bulk actions for expenses"""
    if request.method == 'POST':
        form = BulkExpenseActionForm(request.POST, user=request.user)
        if form.is_valid():
            expense_ids = form.cleaned_data['expense_ids']
            action = form.cleaned_data['action']
            
            expenses = Expense.objects.filter(
                id__in=expense_ids,
                created_by=request.user
            )
            
            success_count = 0
            errors = []
            
            with transaction.atomic():
                for expense in expenses:
                    try:
                        if action == 'submit':
                            if expense.status == 'DRAFT':
                                expense.submit_for_approval()
                                success_count += 1
                            else:
                                errors.append(f"{expense.expense_number}: Already submitted")
                        elif action == 'delete':
                            if expense.status == 'DRAFT':
                                expense.delete()
                                success_count += 1
                            else:
                                errors.append(f"{expense.expense_number}: Cannot delete submitted expense")
                    except Exception as e:
                        errors.append(f"{expense.expense_number}: {str(e)}")
            
            if success_count > 0:
                messages.success(request, f'Successfully processed {success_count} expenses')
            if errors:
                messages.warning(request, f'Some actions failed: {", ".join(errors[:5])}')
            
            return redirect('expenses:expense_list')
    
    return redirect('expenses:expense_list')

# API Views for AJAX calls
@login_required
def expense_quick_stats(request):
    """Get quick stats for dashboard widgets"""
    today = timezone.now().date()
    start_of_month = today.replace(day=1)
    
    user_expenses = Expense.objects.filter(created_by=request.user)
    month_expenses = user_expenses.filter(
        expense_date__gte=start_of_month,
        expense_date__lte=today
    )
    
    stats = {
        'total_this_month': float(month_expenses.aggregate(Sum('amount'))['amount__sum'] or 0),
        'pending_approval': user_expenses.filter(status='SUBMITTED').count(),
        'approved_unpaid': user_expenses.filter(status='APPROVED').count(),
        'recent_submissions': user_expenses.filter(
            submitted_at__gte=timezone.now() - timedelta(days=7)
        ).count()
    }
    
    return JsonResponse(stats)

@login_required
def expense_category_summary(request):
    """Get category-wise summary for charts"""
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    expenses = Expense.objects.filter(created_by=request.user)
    
    if date_from:
        expenses = expenses.filter(expense_date__gte=date_from)
    if date_to:
        expenses = expenses.filter(expense_date__lte=date_to)
    
    summary = expenses.values(
        'category__name', 'category__color_code'
    ).annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')
    
    data = {
        'labels': [item['category__name'] for item in summary],
        'datasets': [{
            'data': [float(item['total']) for item in summary],
            'backgroundColor': [item['category__color_code'] for item in summary],
        }]
    }
    
    return JsonResponse(data)



# Category Management Views
class ExpenseCategoryListView(PermissionRequiredMixin, ListView):
    model = ExpenseCategory
    template_name = 'expenses/category_list.html'
    context_object_name = 'categories'
    permission_required = 'expenses.view_expensecategory'
    
    def get_queryset(self):
        return ExpenseCategory.objects.all().order_by('sort_order', 'name')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_categories'] = self.get_queryset().filter(is_active=True)
        context['inactive_categories'] = self.get_queryset().filter(is_active=False)
        return context

class ExpenseCategoryCreateView(PermissionRequiredMixin, CreateView):
    model = ExpenseCategory
    template_name = 'expenses/category_form.html'
    fields = [
        'name', 'code', 'description', 'gl_account', 'monthly_budget',
        'requires_approval', 'approval_threshold', 'color_code', 'icon',
        'is_active', 'sort_order'
    ]
    permission_required = 'expenses.add_expensecategory'
    success_url = reverse_lazy('expenses:category_list')
    
    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(
            self.request,
            'category_created',
            f'Created expense category: {self.object.name}',
            content_object=self.object
        )
        messages.success(self.request, f'Category "{self.object.name}" created successfully!')
        return response
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create Category'
        return context

class ExpenseCategoryUpdateView(PermissionRequiredMixin, UpdateView):
    model = ExpenseCategory
    template_name = 'expenses/category_form.html'
    fields = [
        'name', 'code', 'description', 'gl_account', 'monthly_budget',
        'requires_approval', 'approval_threshold', 'color_code', 'icon',
        'is_active', 'sort_order'
    ]
    permission_required = 'expenses.change_expensecategory'
    success_url = reverse_lazy('expenses:category_list')
    
    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(
            self.request,
            'category_updated',
            f'Updated expense category: {self.object.name}',
            content_object=self.object
        )
        messages.success(self.request, f'Category "{self.object.name}" updated successfully!')
        return response
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Edit Category'
        return context

class ExpenseCategoryDeleteView(PermissionRequiredMixin, DeleteView):
    model = ExpenseCategory
    template_name = 'expenses/category_confirm_delete.html'
    permission_required = 'expenses.delete_expensecategory'
    success_url = reverse_lazy('expenses:category_list')
    
    def delete(self, request, *args, **kwargs):
        category = self.get_object()
        
        # Check if category has expenses
        if category.expenses.exists():
            messages.error(
                request, 
                f'Cannot delete category "{category.name}" because it has associated expenses. '
                f'You can deactivate it instead.'
            )
            return redirect('expenses:category_list')
        
        response = super().delete(request, *args, **kwargs)
        log_action(
            request,
            'category_deleted',
            f'Deleted expense category: {category.name}'
        )
        messages.success(request, f'Category "{category.name}" deleted successfully!')
        return response

@login_required
@permission_required('expenses.change_expensecategory')
def category_toggle_active(request, pk):
    """Toggle category active status"""
    category = get_object_or_404(ExpenseCategory, pk=pk)
    
    category.is_active = not category.is_active
    category.save()
    
    action = 'activated' if category.is_active else 'deactivated'
    log_action(
        request,
        'category_updated',
        f'{action.capitalize()} expense category: {category.name}',
        content_object=category
    )
    
    messages.success(request, f'Category "{category.name}" {action} successfully!')
    return redirect('expenses:category_list')

@login_required
def category_expenses(request, pk):
    """View expenses for a specific category"""
    category = get_object_or_404(ExpenseCategory, pk=pk)
    
    # Check permissions - users can only see their own expenses unless they have view_all permission
    if request.user.has_perm('expenses.view_all_expenses'):
        expenses = Expense.objects.filter(category=category)
    else:
        expenses = Expense.objects.filter(category=category, created_by=request.user)
    
    # Apply filters
    status_filter = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    if status_filter:
        expenses = expenses.filter(status=status_filter)
    if date_from:
        expenses = expenses.filter(expense_date__gte=date_from)
    if date_to:
        expenses = expenses.filter(expense_date__lte=date_to)
    
    # Pagination
    paginator = Paginator(expenses.order_by('-expense_date'), 20)
    page = request.GET.get('page')
    
    try:
        expenses_page = paginator.page(page)
    except PageNotAnInteger:
        expenses_page = paginator.page(1)
    except EmptyPage:
        expenses_page = paginator.page(paginator.num_pages)
    
    # Statistics
    stats = {
        'total_expenses': expenses.count(),
        'total_amount': expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'approved_amount': expenses.filter(status='APPROVED').aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'paid_amount': expenses.filter(status='PAID').aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
    }
    
    # Budget utilization
    budget_utilization = None
    if category.monthly_budget:
        current_month_spent = category.get_monthly_spent()
        budget_utilization = {
            'spent': current_month_spent,
            'budget': category.monthly_budget,
            'percentage': (current_month_spent / category.monthly_budget * 100) if category.monthly_budget > 0 else 0,
            'remaining': category.monthly_budget - current_month_spent
        }
    
    context = {
        'category': category,
        'expenses': expenses_page,
        'stats': stats,
        'budget_utilization': budget_utilization,
        'status_choices': Expense.STATUS_CHOICES,
    }
    
    return render(request, 'expenses/category_expenses.html', context)

@login_required
@permission_required('expenses.view_expensecategory')
def category_budget_report(request):
    """Budget utilization report across all categories"""
    categories = ExpenseCategory.objects.filter(
        monthly_budget__isnull=False,
        monthly_budget__gt=0
    ).order_by('sort_order', 'name')
    
    # Calculate utilization for each category
    budget_data = []
    for category in categories:
        spent = category.get_monthly_spent()
        budget = category.monthly_budget
        percentage = (spent / budget * 100) if budget > 0 else 0
        
        budget_data.append({
            'category': category,
            'spent': spent,
            'budget': budget,
            'percentage': percentage,
            'remaining': budget - spent,
            'is_over_budget': spent > budget
        })
    
    # Overall statistics
    total_budget = sum(item['budget'] for item in budget_data)
    total_spent = sum(item['spent'] for item in budget_data)
    overall_percentage = (total_spent / total_budget * 100) if total_budget > 0 else 0
    
    context = {
        'budget_data': budget_data,
        'total_budget': total_budget,
        'total_spent': total_spent,
        'overall_percentage': overall_percentage,
        'over_budget_categories': [item for item in budget_data if item['is_over_budget']],
    }
    
    return render(request, 'expenses/category_budget_report.html', context)



@login_required
@require_http_methods(["GET"])
def category_list_api(request):
    """Get list of categories for dropdowns"""
    categories = ExpenseCategory.objects.filter(is_active=True).order_by('sort_order', 'name')
    
    data = [
        {
            'id': category.id,
            'name': category.name,
            'code': category.code,
            'color_code': category.color_code,
            'icon': category.icon,
            'monthly_budget': float(category.monthly_budget) if category.monthly_budget else None,
            'requires_approval': category.requires_approval,
            'approval_threshold': float(category.approval_threshold) if category.approval_threshold else None,
        }
        for category in categories
    ]
    
    return JsonResponse({'categories': data})

@login_required
@require_http_methods(["GET"])
def category_budget_utilization_api(request, pk):
    """Get budget utilization data for a specific category"""
    category = get_object_or_404(ExpenseCategory, pk=pk)
    
    # Get date range from request (default to current month)
    year = request.GET.get('year', timezone.now().year)
    month = request.GET.get('month', timezone.now().month)
    
    try:
        year = int(year)
        month = int(month)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid year or month'}, status=400)
    
    # Calculate spent amount for the specified month
    spent = category.expenses.filter(
        expense_date__year=year,
        expense_date__month=month,
        status='PAID'  # Only count paid expenses
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    budget = category.monthly_budget or 0
    utilization_percentage = (float(spent) / float(budget) * 100) if budget > 0 else 0
    
    data = {
        'category': {
            'id': category.id,
            'name': category.name,
            'budget': float(budget),
        },
        'period': {
            'year': year,
            'month': month,
            'month_name': datetime(year, month, 1).strftime('%B')
        },
        'utilization': {
            'spent': float(spent),
            'remaining': float(budget - spent),
            'percentage': utilization_percentage,
            'is_over_budget': spent > budget
        }
    }
    
    return JsonResponse(data)

@login_required
@permission_required('expenses.view_expensecategory')
def category_usage_stats_api(request):
    """Get category usage statistics"""
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    # Build base queryset
    expenses = Expense.objects.all()
    
    if not request.user.has_perm('expenses.view_all_expenses'):
        expenses = expenses.filter(created_by=request.user)
    
    if date_from:
        expenses = expenses.filter(expense_date__gte=date_from)
    if date_to:
        expenses = expenses.filter(expense_date__lte=date_to)
    
    # Get category statistics
    category_stats = expenses.values(
        'category__id', 'category__name', 'category__color_code'
    ).annotate(
        total_amount=Sum('amount'),
        expense_count=Count('id'),
        avg_amount=Avg('amount')
    ).order_by('-total_amount')
    
    data = {
        'categories': [
            {
                'id': stat['category__id'],
                'name': stat['category__name'],
                'color_code': stat['category__color_code'],
                'total_amount': float(stat['total_amount'] or 0),
                'expense_count': stat['expense_count'],
                'avg_amount': float(stat['avg_amount'] or 0),
            }
            for stat in category_stats
        ],
        'summary': {
            'total_categories': len(category_stats),
            'total_amount': float(sum(stat['total_amount'] or 0 for stat in category_stats)),
            'total_expenses': sum(stat['expense_count'] for stat in category_stats)
        }
    }
    
    return JsonResponse(data)