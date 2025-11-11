from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from .models import Expense, ExpenseCategory, ExpenseComment


@login_required
@require_http_methods(["GET"])
def expense_stats_api(request):
    """Get expense statistics as JSON"""
    user_expenses = Expense.objects.filter(created_by=request.user)

    stats = {
        'total': user_expenses.count(),
        'by_status': {
            'draft': user_expenses.filter(status='DRAFT').count(),
            'submitted': user_expenses.filter(status='SUBMITTED').count(),
            'approved': user_expenses.filter(status='APPROVED').count(),
            'rejected': user_expenses.filter(status='REJECTED').count(),
            'paid': user_expenses.filter(status='PAID').count(),
        },
        'amounts': {
            'total': float(user_expenses.aggregate(Sum('amount'))['amount__sum'] or 0),
            'pending': float(user_expenses.filter(status='SUBMITTED').aggregate(Sum('amount'))['amount__sum'] or 0),
            'paid': float(user_expenses.filter(status='PAID').aggregate(Sum('amount'))['amount__sum'] or 0),
        },
        'this_month': float(user_expenses.filter(
            expense_date__month=timezone.now().month,
            expense_date__year=timezone.now().year
        ).aggregate(Sum('amount'))['amount__sum'] or 0)
    }

    return JsonResponse(stats)


@login_required
@require_http_methods(["GET"])
def expense_category_stats_api(request):
    """Get category-wise expense statistics"""
    user_expenses = Expense.objects.filter(created_by=request.user)

    # Get time range
    days = int(request.GET.get('days', 30))
    start_date = timezone.now().date() - timedelta(days=days)

    expenses = user_expenses.filter(expense_date__gte=start_date)

    category_stats = expenses.values(
        'category__name',
        'category__color_code'
    ).annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')

    data = [
        {
            'category': item['category__name'],
            'color': item['category__color_code'],
            'total': float(item['total']),
            'count': item['count']
        }
        for item in category_stats
    ]

    return JsonResponse({'categories': data})


@login_required
@require_http_methods(["GET"])
def expense_chart_data_api(request):
    """Get expense data for charts"""
    user_expenses = Expense.objects.filter(created_by=request.user)

    # Monthly trend (last 6 months)
    months_data = []
    for i in range(6, -1, -1):
        date = timezone.now().date().replace(day=1) - timedelta(days=30 * i)
        month_expenses = user_expenses.filter(
            expense_date__year=date.year,
            expense_date__month=date.month
        )

        months_data.append({
            'month': date.strftime('%b %Y'),
            'total': float(month_expenses.aggregate(Sum('amount'))['amount__sum'] or 0),
            'count': month_expenses.count()
        })

    return JsonResponse({'monthly_trend': months_data})


@login_required
@require_http_methods(["GET"])
def check_expense_number_api(request):
    """Check if expense number exists"""
    expense_number = request.GET.get('expense_number', '')

    exists = Expense.objects.filter(expense_number=expense_number).exists()

    return JsonResponse({
        'exists': exists,
        'available': not exists
    })


@login_required
@require_http_methods(["POST"])
def quick_approve_api(request, pk):
    """Quick approve endpoint for AJAX requests"""
    from .models import Expense
    from .utils import validate_expense_approval

    if not request.user.has_perm('expenses.approve_expense'):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    try:
        expense = Expense.objects.get(pk=pk)

        # Validate
        validation = validate_expense_approval(expense, request.user)
        if validation['errors']:
            return JsonResponse({
                'success': False,
                'errors': validation['errors']
            }, status=400)

        expense.approve(request.user)

        return JsonResponse({
            'success': True,
            'message': f'Expense {expense.expense_number} approved',
            'status': expense.status
        })
    except Expense.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Expense not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
@require_http_methods(["GET"])
def expense_search_api(request):
    """Search expenses via AJAX"""
    query = request.GET.get('q', '')
    limit = int(request.GET.get('limit', 10))

    expenses = Expense.objects.filter(
        created_by=request.user
    ).filter(
        Q(expense_number__icontains=query) |
        Q(title__icontains=query) |
        Q(vendor_name__icontains=query) |
        Q(description__icontains=query)
    ).select_related('category')[:limit]

    results = [
        {
            'id': exp.id,
            'expense_number': exp.expense_number,
            'title': exp.title,
            'amount': float(exp.amount),
            'currency': exp.currency,
            'category': exp.category.name,
            'status': exp.status,
            'date': exp.expense_date.strftime('%Y-%m-%d'),
            'url': f'/expenses/{exp.id}/'
        }
        for exp in expenses
    ]

    return JsonResponse({'results': results})


@login_required
@require_http_methods(["GET"])
def budget_utilization_api(request):
    """Get budget utilization for categories"""
    categories = ExpenseCategory.objects.filter(
        is_active=True,
        monthly_budget__isnull=False
    )

    data = []
    for category in categories:
        utilization = category.get_budget_utilization()
        spent = category.get_monthly_spent()

        data.append({
            'category': category.name,
            'budget': float(category.monthly_budget),
            'spent': float(spent),
            'remaining': float(category.monthly_budget - spent),
            'utilization': float(utilization) if utilization else 0,
            'color': category.color_code,
            'status': 'exceeded' if utilization and utilization >= 100
            else 'warning' if utilization and utilization >= 80
            else 'safe'
        })

    return JsonResponse({'budgets': data})


@login_required
@require_http_methods(["POST"])
def bulk_action_api(request):
    """Handle bulk actions on expenses"""
    import json

    data = json.loads(request.body)
    action = data.get('action')
    expense_ids = data.get('expense_ids', [])

    if not action or not expense_ids:
        return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)

    expenses = Expense.objects.filter(
        id__in=expense_ids,
        created_by=request.user
    )

    results = {
        'success': True,
        'processed': 0,
        'failed': 0,
        'errors': []
    }

    try:
        if action == 'delete':
            # Only allow deleting drafts
            draft_expenses = expenses.filter(status='DRAFT')
            count = draft_expenses.count()
            draft_expenses.delete()
            results['processed'] = count

        elif action == 'submit':
            for expense in expenses.filter(status='DRAFT'):
                try:
                    expense.submit_for_approval()
                    results['processed'] += 1
                except Exception as e:
                    results['failed'] += 1
                    results['errors'].append(f'{expense.expense_number}: {str(e)}')

        elif action == 'export':
            from .tasks import export_expenses_to_csv
            export_expenses_to_csv.delay(request.user.id, {'ids': expense_ids})
            results['message'] = 'Export queued successfully'

        else:
            return JsonResponse({'success': False, 'error': 'Unknown action'}, status=400)

        return JsonResponse(results)

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)