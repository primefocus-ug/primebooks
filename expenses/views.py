from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.db.models import Q, Sum
from django.views.decorators.http import require_http_methods
from .models import Expense, Budget
from .forms import ExpenseForm, BudgetForm, ExpenseFilterForm
from .utils import (
    get_date_range, get_expense_summary,
    generate_chart_data, export_to_pdf, export_to_excel
)
import json


@login_required
def expense_list(request):
    """Main expense list view with filtering"""
    expenses = Expense.objects.filter(user=request.user)
    filter_form = ExpenseFilterForm(request.GET)

    # Apply filters
    if filter_form.is_valid():
        period = filter_form.cleaned_data.get('period')
        start_date = filter_form.cleaned_data.get('start_date')
        end_date = filter_form.cleaned_data.get('end_date')
        tags = filter_form.cleaned_data.get('tags')
        min_amount = filter_form.cleaned_data.get('min_amount')
        max_amount = filter_form.cleaned_data.get('max_amount')

        # Date filtering
        if period and period != 'custom':
            start, end = get_date_range(period)
            if start and end:
                expenses = expenses.filter(date__gte=start, date__lte=end)
        elif period == 'custom' and start_date and end_date:
            expenses = expenses.filter(date__gte=start_date, date__lte=end_date)

        # Tag filtering
        if tags:
            tag_list = [tag.strip() for tag in tags.split(',')]
            expenses = expenses.filter(tags__name__in=tag_list).distinct()

        # Amount filtering
        if min_amount:
            expenses = expenses.filter(amount__gte=min_amount)
        if max_amount:
            expenses = expenses.filter(amount__lte=max_amount)

    # Get summary
    summary = get_expense_summary(expenses)

    # Get active budgets with alerts
    budgets = Budget.objects.filter(user=request.user, is_active=True)
    budget_alerts = []
    for budget in budgets:
        if budget.is_over_threshold():
            percentage = budget.get_percentage_used()
            budget_alerts.append({
                'budget': budget,
                'percentage': round(percentage, 1),
                'spent': budget.get_current_spending()
            })

    context = {
        'expenses': expenses[:50],  # Paginate if needed
        'filter_form': filter_form,
        'summary': summary,
        'budget_alerts': budget_alerts,
        'total_expenses': expenses.count()
    }

    return render(request, 'expenses/expense_list.html', context)


@login_required
def expense_create(request):
    """Quick expense entry form"""
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.user = request.user
            expense.save()
            form.save_m2m()  # Save tags

            messages.success(request, 'Expense added successfully!')

            # Return JSON for AJAX requests
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'expense_id': expense.id,
                    'message': 'Expense added successfully!'
                })

            return redirect('expenses:expense_list')
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'errors': form.errors
                }, status=400)
    else:
        form = ExpenseForm()

    return render(request, 'expenses/expense_form.html', {'form': form})


@login_required
def expense_edit(request, pk):
    """Edit existing expense"""
    expense = get_object_or_404(Expense, pk=pk, user=request.user)

    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES, instance=expense)
        if form.is_valid():
            form.save()
            messages.success(request, 'Expense updated successfully!')
            return redirect('expenses:expense_list')
    else:
        form = ExpenseForm(instance=expense)

    return render(request, 'expenses/expense_form.html', {
        'form': form,
        'expense': expense
    })


@login_required
@require_http_methods(["DELETE", "POST"])
def expense_delete(request, pk):
    """Delete expense"""
    expense = get_object_or_404(Expense, pk=pk, user=request.user)
    expense.delete()
    messages.success(request, 'Expense deleted successfully!')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    return redirect('expenses:expense_list')


@login_required
def reports_view(request):
    """Advanced reporting with charts"""
    expenses = Expense.objects.filter(user=request.user)
    filter_form = ExpenseFilterForm(request.GET)

    # Apply same filters as list view
    if filter_form.is_valid():
        period = filter_form.cleaned_data.get('period')
        start_date = filter_form.cleaned_data.get('start_date')
        end_date = filter_form.cleaned_data.get('end_date')
        tags = filter_form.cleaned_data.get('tags')
        min_amount = filter_form.cleaned_data.get('min_amount')
        max_amount = filter_form.cleaned_data.get('max_amount')

        # Date filtering
        if period and period != 'custom':
            start, end = get_date_range(period)
            if start and end:
                expenses = expenses.filter(date__gte=start, date__lte=end)
        elif period == 'custom' and start_date and end_date:
            expenses = expenses.filter(date__gte=start_date, date__lte=end_date)

        # Tag filtering
        if tags:
            tag_list = [tag.strip() for tag in tags.split(',')]
            expenses = expenses.filter(tags__name__in=tag_list).distinct()

        # Amount filtering
        if min_amount:
            expenses = expenses.filter(amount__gte=min_amount)
        if max_amount:
            expenses = expenses.filter(amount__lte=max_amount)

    summary = get_expense_summary(expenses)

    # Generate chart data
    daily_data = generate_chart_data(expenses, group_by='date')
    monthly_data = generate_chart_data(expenses, group_by='month')

    context = {
        'summary': summary,
        'daily_data': json.dumps(daily_data, default=str),
        'monthly_data': json.dumps(monthly_data, default=str),
        'filter_form': filter_form,
    }

    return render(request, 'expenses/reports.html', context)


@login_required
def export_pdf(request):
    """Export expenses to PDF"""
    expenses = Expense.objects.filter(user=request.user)
    filter_form = ExpenseFilterForm(request.GET)

    # Apply filters if form is valid
    if filter_form.is_valid():
        period = filter_form.cleaned_data.get('period')
        start_date = filter_form.cleaned_data.get('start_date')
        end_date = filter_form.cleaned_data.get('end_date')
        tags = filter_form.cleaned_data.get('tags')
        min_amount = filter_form.cleaned_data.get('min_amount')
        max_amount = filter_form.cleaned_data.get('max_amount')

        # Date filtering
        if period and period != 'custom':
            start, end = get_date_range(period)
            if start and end:
                expenses = expenses.filter(date__gte=start, date__lte=end)
        elif period == 'custom' and start_date and end_date:
            expenses = expenses.filter(date__gte=start_date, date__lte=end_date)

        # Tag filtering
        if tags:
            tag_list = [tag.strip() for tag in tags.split(',')]
            expenses = expenses.filter(tags__name__in=tag_list).distinct()

        # Amount filtering
        if min_amount:
            expenses = expenses.filter(amount__gte=min_amount)
        if max_amount:
            expenses = expenses.filter(amount__lte=max_amount)

    summary = get_expense_summary(expenses)
    pdf_buffer = export_to_pdf(expenses, summary, request.GET)

    response = HttpResponse(pdf_buffer, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="expenses_report.pdf"'
    return response


@login_required
def export_excel(request):
    """Export expenses to Excel"""
    expenses = Expense.objects.filter(user=request.user)
    filter_form = ExpenseFilterForm(request.GET)

    # Apply filters if form is valid
    if filter_form.is_valid():
        period = filter_form.cleaned_data.get('period')
        start_date = filter_form.cleaned_data.get('start_date')
        end_date = filter_form.cleaned_data.get('end_date')
        tags = filter_form.cleaned_data.get('tags')
        min_amount = filter_form.cleaned_data.get('min_amount')
        max_amount = filter_form.cleaned_data.get('max_amount')

        # Date filtering
        if period and period != 'custom':
            start, end = get_date_range(period)
            if start and end:
                expenses = expenses.filter(date__gte=start, date__lte=end)
        elif period == 'custom' and start_date and end_date:
            expenses = expenses.filter(date__gte=start_date, date__lte=end_date)

        # Tag filtering
        if tags:
            tag_list = [tag.strip() for tag in tags.split(',')]
            expenses = expenses.filter(tags__name__in=tag_list).distinct()

        # Amount filtering
        if min_amount:
            expenses = expenses.filter(amount__gte=min_amount)
        if max_amount:
            expenses = expenses.filter(amount__lte=max_amount)

    summary = get_expense_summary(expenses)
    excel_buffer = export_to_excel(expenses, summary, request.GET)

    response = HttpResponse(excel_buffer,
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="expenses_report.xlsx"'
    return response


@login_required
def budget_list(request):
    """List and manage budgets"""
    budgets = Budget.objects.filter(user=request.user)

    # Calculate current spending for each budget
    budget_data = []
    for budget in budgets:
        spending = budget.get_current_spending()
        percentage = budget.get_percentage_used()
        budget_data.append({
            'budget': budget,
            'spending': spending,
            'percentage': round(percentage, 1),
            'remaining': budget.amount - spending,
            'is_over': budget.is_over_threshold()
        })

    return render(request, 'expenses/budget_list.html', {
        'budget_data': budget_data
    })


@login_required
def budget_create(request):
    """Create new budget"""
    if request.method == 'POST':
        form = BudgetForm(request.POST)
        if form.is_valid():
            budget = form.save(commit=False)
            budget.user = request.user
            budget.save()
            form.save_m2m()
            messages.success(request, 'Budget created successfully!')
            return redirect('expenses:budget_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = BudgetForm()

    return render(request, 'expenses/budget_form.html', {'form': form})


@login_required
def budget_edit(request, pk):
    """Edit existing budget"""
    budget = get_object_or_404(Budget, pk=pk, user=request.user)

    if request.method == 'POST':
        form = BudgetForm(request.POST, instance=budget)
        if form.is_valid():
            form.save()
            messages.success(request, 'Budget updated successfully!')
            return redirect('expenses:budget_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = BudgetForm(instance=budget)

    return render(request, 'expenses/budget_form.html', {
        'form': form,
        'budget': budget
    })


@login_required
def budget_delete(request, pk):
    """Delete budget"""
    budget = get_object_or_404(Budget, pk=pk, user=request.user)

    if request.method == 'POST':
        budget.delete()
        messages.success(request, 'Budget deleted successfully!')

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})

        return redirect('expenses:budget_list')

    # If not POST, show confirmation page
    return render(request, 'expenses/budget_confirm_delete.html', {
        'budget': budget
    })


@login_required
def get_tag_suggestions(request):
    """API endpoint for tag autocomplete"""
    query = request.GET.get('q', '')
    user_expenses = Expense.objects.filter(user=request.user)

    if query:
        # Filter tags by query
        tags = set()
        for expense in user_expenses:
            for tag in expense.tags.filter(name__icontains=query):
                tags.add(tag.name)
        return JsonResponse({'tags': list(tags)[:10]})

    # Return most used tags
    from collections import Counter
    all_tags = []
    for expense in user_expenses:
        all_tags.extend([tag.name for tag in expense.tags.all()])

    most_common = Counter(all_tags).most_common(20)
    return JsonResponse({'tags': [tag for tag, count in most_common]})