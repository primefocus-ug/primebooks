from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.db.models import Sum, Count, Avg, Q
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from decimal import Decimal
import json
from datetime import datetime, timedelta

from .models import Expense, Budget
from .forms import ExpenseForm, BudgetForm, ExpenseFilterForm


@login_required
def dashboard(request):
    """Main dashboard with analytics"""
    user = request.user
    today = timezone.now().date()

    # Get date ranges
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    # Quick stats
    total_expenses = Expense.objects.filter(user=user).count()

    # Today's expenses
    today_expenses = Expense.objects.filter(user=user, date=today)
    today_total = today_expenses.aggregate(total=Sum('amount'))['total'] or 0

    # This week
    week_expenses = Expense.objects.filter(user=user, date__gte=week_start, date__lte=today)
    week_total = week_expenses.aggregate(total=Sum('amount'))['total'] or 0

    # This month
    month_expenses = Expense.objects.filter(user=user, date__gte=month_start, date__lte=today)
    month_total = month_expenses.aggregate(total=Sum('amount'))['total'] or 0

    # This year
    year_expenses = Expense.objects.filter(user=user, date__gte=year_start, date__lte=today)
    year_total = year_expenses.aggregate(total=Sum('amount'))['total'] or 0

    # Recent expenses
    recent_expenses = Expense.objects.filter(user=user).select_related()[:10]

    # Top tags
    all_expenses = Expense.objects.filter(user=user)
    tag_stats = {}
    for expense in all_expenses:
        for tag in expense.tags.all():
            if tag.name not in tag_stats:
                tag_stats[tag.name] = {'count': 0, 'total': Decimal('0')}
            tag_stats[tag.name]['count'] += 1
            tag_stats[tag.name]['total'] += expense.amount

    top_tags = sorted(tag_stats.items(), key=lambda x: x[1]['total'], reverse=True)[:10]

    # Budget alerts
    budgets = Budget.objects.filter(user=user, is_active=True)
    budget_alerts = []
    for budget in budgets:
        percentage = budget.get_percentage_used()
        if budget.is_over_threshold():
            budget_alerts.append({
                'budget': budget,
                'percentage': round(percentage, 1),
                'spent': budget.get_current_spending(),
                'remaining': budget.get_remaining(),
                'status': budget.get_status_color()
            })

    # Monthly trend (last 12 months)
    monthly_data = []
    for i in range(11, -1, -1):
        date = today - timedelta(days=30 * i)
        month_start = date.replace(day=1)
        if date.month == 12:
            month_end = date.replace(day=31)
        else:
            month_end = (date.replace(month=date.month + 1, day=1) - timedelta(days=1))

        month_expenses = Expense.objects.filter(
            user=user,
            date__gte=month_start,
            date__lte=month_end
        )
        total = month_expenses.aggregate(total=Sum('amount'))['total'] or 0
        count = month_expenses.count()

        monthly_data.append({
            'month': month_start.strftime('%b %Y'),
            'total': float(total),
            'count': count
        })

    # Payment method breakdown
    payment_stats = {}
    for expense in all_expenses:
        method = expense.payment_method or 'Not Specified'
        if method not in payment_stats:
            payment_stats[method] = {'count': 0, 'total': Decimal('0')}
        payment_stats[method]['count'] += 1
        payment_stats[method]['total'] += expense.amount

    context = {
        'total_expenses': total_expenses,
        'today_total': today_total,
        'today_count': today_expenses.count(),
        'week_total': week_total,
        'week_count': week_expenses.count(),
        'month_total': month_total,
        'month_count': month_expenses.count(),
        'year_total': year_total,
        'year_count': year_expenses.count(),
        'recent_expenses': recent_expenses,
        'top_tags': top_tags,
        'budget_alerts': budget_alerts,
        'monthly_data': json.dumps(monthly_data),
        'tag_stats': json.dumps([{'name': k, 'total': float(v['total']), 'count': v['count']} for k, v in top_tags]),
        'payment_stats': json.dumps(
            [{'method': k, 'total': float(v['total']), 'count': v['count']} for k, v in payment_stats.items()]),
    }

    return render(request, 'expenses/dashboard.html', context)


@login_required
def expense_list(request):
    """Advanced expense list with real-time filtering"""
    expenses = Expense.objects.filter(user=request.user).prefetch_related('tags')

    # Get filter parameters
    search = request.GET.get('search', '')
    tags = request.GET.get('tags', '')
    payment_method = request.GET.get('payment_method', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    min_amount = request.GET.get('min_amount', '')
    max_amount = request.GET.get('max_amount', '')
    period = request.GET.get('period', '')

    # Apply filters
    if search:
        expenses = expenses.filter(
            Q(description__icontains=search) |
            Q(notes__icontains=search)
        )

    if tags:
        tag_list = [t.strip() for t in tags.split(',') if t.strip()]
        if tag_list:
            expenses = expenses.filter(tags__name__in=tag_list).distinct()

    if payment_method:
        expenses = expenses.filter(payment_method=payment_method)

    # Period filtering
    if period:
        today = timezone.now().date()
        if period == 'today':
            expenses = expenses.filter(date=today)
        elif period == 'week':
            week_start = today - timedelta(days=today.weekday())
            expenses = expenses.filter(date__gte=week_start, date__lte=today)
        elif period == 'month':
            month_start = today.replace(day=1)
            expenses = expenses.filter(date__gte=month_start, date__lte=today)
        elif period == 'quarter':
            quarter_month = ((today.month - 1) // 3) * 3 + 1
            quarter_start = today.replace(month=quarter_month, day=1)
            expenses = expenses.filter(date__gte=quarter_start, date__lte=today)
        elif period == 'year':
            year_start = today.replace(month=1, day=1)
            expenses = expenses.filter(date__gte=year_start, date__lte=today)

    # Date range filtering
    if date_from:
        expenses = expenses.filter(date__gte=date_from)
    if date_to:
        expenses = expenses.filter(date__lte=date_to)

    # Amount filtering
    if min_amount:
        try:
            expenses = expenses.filter(amount__gte=Decimal(min_amount))
        except:
            pass
    if max_amount:
        try:
            expenses = expenses.filter(amount__lte=Decimal(max_amount))
        except:
            pass

    # Calculate summary
    total = expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    count = expenses.count()
    average = total / count if count > 0 else Decimal('0')

    # Get all unique tags
    all_tags = set()
    for expense in Expense.objects.filter(user=request.user):
        all_tags.update(expense.tags.names())

    context = {
        'expenses': expenses[:100],  # Limit for performance
        'total': total,
        'count': count,
        'average': average,
        'all_tags': sorted(all_tags),
        'payment_methods': Expense.PAYMENT_METHODS,
        'filters': {
            'search': search,
            'tags': tags,
            'payment_method': payment_method,
            'date_from': date_from,
            'date_to': date_to,
            'min_amount': min_amount,
            'max_amount': max_amount,
            'period': period,
        }
    }

    return render(request, 'expenses/expense_list.html', context)


@login_required
def expense_create(request):
    """Quick expense entry"""
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.user = request.user
            expense.save()
            form.save_m2m()

            messages.success(request, '✅ Expense added successfully!')

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'expense': {
                        'id': str(expense.id),
                        'description': expense.description,
                        'amount': float(expense.amount),
                        'date': expense.date.isoformat(),
                        'tags': list(expense.tags.names())
                    }
                })

            if request.POST.get('save_and_new'):
                return redirect('expenses:expense_create')

            return redirect('expenses:dashboard')
    else:
        form = ExpenseForm()

    # Get common tags for suggestions
    recent_tags = set()
    for expense in Expense.objects.filter(user=request.user)[:50]:
        recent_tags.update(expense.tags.names())

    context = {
        'form': form,
        'recent_tags': sorted(recent_tags)[:20]
    }

    return render(request, 'expenses/expense_form.html', context)


@login_required
def expense_edit(request, pk):
    """Edit expense"""
    expense = get_object_or_404(Expense, pk=pk, user=request.user)

    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES, instance=expense)
        if form.is_valid():
            form.save()
            messages.success(request, '✅ Expense updated successfully!')

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True})

            return redirect('expenses:expense_list')
    else:
        form = ExpenseForm(instance=expense)

    context = {
        'form': form,
        'expense': expense
    }

    return render(request, 'expenses/expense_form.html', context)


@login_required
@require_http_methods(["DELETE", "POST"])
def expense_delete(request, pk):
    """Delete expense"""
    expense = get_object_or_404(Expense, pk=pk, user=request.user)
    expense.delete()

    messages.success(request, '🗑️ Expense deleted successfully!')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    return redirect('expenses:expense_list')


@login_required
def analytics(request):
    """Advanced analytics dashboard"""
    user = request.user

    # Get date range
    period = request.GET.get('period', '30')
    try:
        days = int(period)
    except:
        days = 30

    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days)

    expenses = Expense.objects.filter(
        user=user,
        date__gte=start_date,
        date__lte=end_date
    )

    # Daily trend
    daily_data = expenses.values('date').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('date')

    # Tag analysis
    tag_analysis = {}
    for expense in expenses:
        for tag in expense.tags.all():
            if tag.name not in tag_analysis:
                tag_analysis[tag.name] = {
                    'total': Decimal('0'),
                    'count': 0,
                    'avg': Decimal('0')
                }
            tag_analysis[tag.name]['total'] += expense.amount
            tag_analysis[tag.name]['count'] += 1

    for tag_name, data in tag_analysis.items():
        if data['count'] > 0:
            data['avg'] = data['total'] / data['count']

    top_tags = sorted(tag_analysis.items(), key=lambda x: x[1]['total'], reverse=True)[:15]

    # Payment method analysis
    payment_analysis = expenses.values('payment_method').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')

    # Day of week analysis
    day_analysis = {}
    for expense in expenses:
        day_name = expense.date.strftime('%A')
        if day_name not in day_analysis:
            day_analysis[day_name] = {'total': Decimal('0'), 'count': 0}
        day_analysis[day_name]['total'] += expense.amount
        day_analysis[day_name]['count'] += 1

    # Hour analysis (from created_at)
    hour_analysis = {}
    for expense in expenses:
        hour = expense.created_at.hour
        if hour not in hour_analysis:
            hour_analysis[hour] = {'total': Decimal('0'), 'count': 0}
        hour_analysis[hour]['total'] += expense.amount
        hour_analysis[hour]['count'] += 1

    # Summary
    total = expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    count = expenses.count()
    average = total / count if count > 0 else Decimal('0')

    # Trend comparison
    prev_start = start_date - timedelta(days=days)
    prev_end = start_date - timedelta(days=1)
    prev_expenses = Expense.objects.filter(
        user=user,
        date__gte=prev_start,
        date__lte=prev_end
    )
    prev_total = prev_expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    if prev_total > 0:
        trend_percentage = ((total - prev_total) / prev_total * 100)
    else:
        trend_percentage = 100 if total > 0 else 0

    context = {
        'period_days': days,
        'start_date': start_date,
        'end_date': end_date,
        'total': total,
        'count': count,
        'average': average,
        'trend_percentage': round(trend_percentage, 1),
        'trend_direction': 'up' if trend_percentage > 0 else 'down',
        'daily_data': json.dumps([{
            'date': item['date'].isoformat(),
            'total': float(item['total']),
            'count': item['count']
        } for item in daily_data]),
        'tag_data': json.dumps([{
            'name': name,
            'total': float(data['total']),
            'count': data['count'],
            'avg': float(data['avg'])
        } for name, data in top_tags]),
        'payment_data': json.dumps([{
            'method': item['payment_method'] or 'Not Specified',
            'total': float(item['total']),
            'count': item['count']
        } for item in payment_analysis]),
        'day_data': json.dumps([{
            'day': day,
            'total': float(data['total']),
            'count': data['count']
        } for day, data in day_analysis.items()]),
    }

    return render(request, 'expenses/analytics.html', context)


@login_required
def budget_list(request):
    """Budget management"""
    budgets = Budget.objects.filter(user=request.user)

    budget_data = []
    for budget in budgets:
        spending = budget.get_current_spending()
        percentage = budget.get_percentage_used()
        remaining = budget.get_remaining()

        budget_data.append({
            'budget': budget,
            'spending': spending,
            'percentage': round(percentage, 1),
            'remaining': remaining,
            'status': budget.get_status_color(),
            'is_over': budget.is_over_threshold()
        })

    context = {
        'budget_data': budget_data
    }

    return render(request, 'expenses/budget_list.html', context)


@login_required
def budget_create(request):
    """Create budget"""
    if request.method == 'POST':
        form = BudgetForm(request.POST)
        if form.is_valid():
            budget = form.save(commit=False)
            budget.user = request.user
            budget.save()
            form.save_m2m()

            messages.success(request, '✅ Budget created successfully!')
            return redirect('expenses:budget_list')
    else:
        form = BudgetForm()

    context = {'form': form}
    return render(request, 'expenses/budget_form.html', context)


@login_required
def budget_edit(request, pk):
    """Edit budget"""
    budget = get_object_or_404(Budget, pk=pk, user=request.user)

    if request.method == 'POST':
        form = BudgetForm(request.POST, instance=budget)
        if form.is_valid():
            form.save()
            messages.success(request, '✅ Budget updated successfully!')
            return redirect('expenses:budget_list')
    else:
        form = BudgetForm(instance=budget)

    context = {
        'form': form,
        'budget': budget
    }

    return render(request, 'expenses/budget_form.html', context)


@login_required
def budget_delete(request, pk):
    """Delete budget"""
    budget = get_object_or_404(Budget, pk=pk, user=request.user)
    budget.delete()

    messages.success(request, '🗑️ Budget deleted successfully!')
    return redirect('expenses:budget_list')


# API Endpoints for real-time features

@login_required
def api_tag_suggestions(request):
    """Get tag suggestions"""
    query = request.GET.get('q', '').lower()

    all_tags = set()
    for expense in Expense.objects.filter(user=request.user):
        all_tags.update(expense.tags.names())

    if query:
        suggestions = [tag for tag in all_tags if query in tag.lower()]
    else:
        # Return most used tags
        tag_counts = {}
        for expense in Expense.objects.filter(user=request.user):
            for tag in expense.tags.all():
                tag_counts[tag.name] = tag_counts.get(tag.name, 0) + 1

        suggestions = sorted(tag_counts.keys(), key=lambda x: tag_counts[x], reverse=True)[:20]

    return JsonResponse({'tags': suggestions[:10]})


@login_required
def api_quick_stats(request):
    """Get quick stats for dashboard"""
    today = timezone.now().date()

    today_total = Expense.objects.filter(
        user=request.user,
        date=today
    ).aggregate(total=Sum('amount'))['total'] or 0

    month_start = today.replace(day=1)
    month_total = Expense.objects.filter(
        user=request.user,
        date__gte=month_start,
        date__lte=today
    ).aggregate(total=Sum('amount'))['total'] or 0

    return JsonResponse({
        'today': float(today_total),
        'month': float(month_total)
    })


@login_required
def api_budget_status(request):
    """Get budget status"""
    budgets = Budget.objects.filter(user=request.user, is_active=True)

    budget_status = []
    for budget in budgets:
        percentage = budget.get_percentage_used()
        budget_status.append({
            'id': budget.id,
            'name': budget.name,
            'amount': float(budget.amount),
            'spent': float(budget.get_current_spending()),
            'remaining': float(budget.get_remaining()),
            'percentage': round(percentage, 1),
            'status': budget.get_status_color(),
            'over_threshold': budget.is_over_threshold()
        })

    return JsonResponse({'budgets': budget_status})


@login_required
def expense_detail(request, pk):
    """Detailed view of a single expense"""
    expense = get_object_or_404(Expense, pk=pk, user=request.user)

    # Get related expenses (same tags)
    related_expenses = []
    if expense.tags.exists():
        tag_names = list(expense.tags.names())
        related_expenses = Expense.objects.filter(
            user=request.user,
            tags__name__in=tag_names
        ).exclude(id=expense.id).distinct()[:5]

    context = {
        'expense': expense,
        'related_expenses': related_expenses,
    }

    return render(request, 'expenses/expense_detail.html', context)


@login_required
def reports_dashboard(request):
    """Comprehensive reports dashboard"""
    user = request.user

    # Date range from filters
    period = request.GET.get('period', '30')
    try:
        days = int(period)
    except:
        days = 30

    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days)

    expenses = Expense.objects.filter(
        user=user,
        date__gte=start_date,
        date__lte=end_date
    )

    # Summary Statistics
    total = expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    count = expenses.count()
    average = total / count if count > 0 else Decimal('0')

    # Tag Analysis
    tag_analysis = {}
    for expense in expenses:
        for tag in expense.tags.all():
            if tag.name not in tag_analysis:
                tag_analysis[tag.name] = {'total': Decimal('0'), 'count': 0}
            tag_analysis[tag.name]['total'] += expense.amount
            tag_analysis[tag.name]['count'] += 1

    top_tags = sorted(tag_analysis.items(), key=lambda x: x[1]['total'], reverse=True)[:10]

    # Payment Method Analysis
    payment_analysis = expenses.values('payment_method').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')

    # Monthly Comparison
    current_month_start = end_date.replace(day=1)
    current_month = expenses.filter(date__gte=current_month_start)
    current_month_total = current_month.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    # Previous month
    if current_month_start.month == 1:
        prev_month_start = current_month_start.replace(year=current_month_start.year - 1, month=12)
    else:
        prev_month_start = current_month_start.replace(month=current_month_start.month - 1)

    prev_month_end = current_month_start - timedelta(days=1)
    prev_month = Expense.objects.filter(
        user=user,
        date__gte=prev_month_start,
        date__lte=prev_month_end
    )
    prev_month_total = prev_month.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    if prev_month_total > 0:
        month_change = ((current_month_total - prev_month_total) / prev_month_total * 100)
    else:
        month_change = 100 if current_month_total > 0 else 0

    # Budget Status
    budgets = Budget.objects.filter(user=user, is_active=True)
    budget_status = []
    for budget in budgets:
        percentage = budget.get_percentage_used()
        budget_status.append({
            'budget': budget,
            'percentage': round(percentage, 1),
            'spent': budget.get_current_spending(),
            'remaining': budget.get_remaining(),
            'status': budget.get_status_color()
        })

    context = {
        'period_days': days,
        'start_date': start_date,
        'end_date': end_date,
        'total': total,
        'count': count,
        'average': average,
        'top_tags': top_tags,
        'payment_analysis': payment_analysis,
        'current_month_total': current_month_total,
        'prev_month_total': prev_month_total,
        'month_change': round(month_change, 1),
        'month_change_direction': 'up' if month_change > 0 else 'down',
        'budget_status': budget_status,
    }

    return render(request, 'expenses/reports_dashboard.html', context)