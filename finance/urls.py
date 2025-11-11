from django.urls import path
from . import views
from . import views_reports

app_name = 'finance'

urlpatterns = [
    # Dashboard
    path('', views.finance_dashboard, name='dashboard'),

    # Currency Management
    path('currency/', views.currency_list, name='currency_list'),
    path('exchange-rates/', views.exchange_rate_list, name='exchange_rate_list'),
    path('exchange-rates/fetch/', views.fetch_exchange_rates, name='fetch_exchange_rates'),

    # Dimensions
    path('dimensions/', views.dimension_list, name='dimension_list'),
    path('dimensions/<int:pk>/', views.dimension_detail, name='dimension_detail'),

    # Chart of Accounts
    path('chart-of-accounts/', views.chart_of_accounts_list, name='chart_of_accounts_list'),
    path('chart-of-accounts/create/', views.chart_of_accounts_create, name='chart_of_accounts_create'),
    path('chart-of-accounts/<int:pk>/', views.chart_of_accounts_detail, name='chart_of_accounts_detail'),
    path('chart-of-accounts/<int:pk>/update/', views.chart_of_accounts_update, name='chart_of_accounts_update'),

    # Fiscal Year & Periods
    path('fiscal-years/', views.fiscal_year_list, name='fiscal_year_list'),
    path('fiscal-years/<int:pk>/', views.fiscal_year_detail, name='fiscal_year_detail'),
    path('fiscal-years/<int:pk>/generate-periods/', views.fiscal_year_generate_periods,
         name='fiscal_year_generate_periods'),
    path('fiscal-periods/<int:pk>/close/', views.fiscal_period_close, name='fiscal_period_close'),

    # Journal Entries
    path('journal-entries/', views.journal_entry_list, name='journal_entry_list'),
    path('journal-entries/create/', views.journal_entry_create, name='journal_entry_create'),
    path('journal-entries/<uuid:pk>/', views.journal_entry_detail, name='journal_entry_detail'),
    path('journal-entries/<uuid:pk>/update/', views.journal_entry_update, name='journal_entry_update'),
    path('journal-entries/<uuid:pk>/post/', views.journal_entry_post, name='journal_entry_post'),
    path('journal-entries/<uuid:pk>/approve/', views.journal_entry_approve, name='journal_entry_approve'),
    path('journal-entries/<uuid:pk>/reverse/', views.journal_entry_reverse, name='journal_entry_reverse'),

    # Recurring Journal Entries
    path('recurring-entries/', views.recurring_entry_list, name='recurring_entry_list'),
    path('recurring-entries/<int:pk>/generate/', views.recurring_entry_generate, name='recurring_entry_generate'),

    # Bank Accounts
    path('bank-accounts/', views.bank_account_list, name='bank_account_list'),
    path('bank-accounts/<int:pk>/', views.bank_account_detail, name='bank_account_detail'),

    # Transactions
    path('transactions/create/', views.transaction_create, name='transaction_create'),

    # Bank Reconciliation
    path('reconciliation/', views.bank_reconciliation_list, name='bank_reconciliation_list'),
    path('reconciliation/create/', views.bank_reconciliation_create, name='bank_reconciliation_create'),
    path('reconciliation/<int:pk>/', views.bank_reconciliation_detail, name='bank_reconciliation_detail'),
    path('reconciliation/<int:pk>/match/', views.bank_reconciliation_match, name='bank_reconciliation_match'),
    path('reconciliation/<int:pk>/complete/', views.bank_reconciliation_complete, name='bank_reconciliation_complete'),

    # Budgets
    path('budgets/', views.budget_list, name='budget_list'),
    path('budgets/<int:pk>/', views.budget_detail, name='budget_detail'),
    path('budgets/<int:pk>/approve/', views.budget_approve, name='budget_approve'),
    path('budgets/<int:pk>/activate/', views.budget_activate, name='budget_activate'),

    # Fixed Assets
    path('fixed-assets/', views.fixed_asset_list, name='fixed_asset_list'),
    path('fixed-assets/<int:pk>/', views.fixed_asset_detail, name='fixed_asset_detail'),
    path('fixed-assets/<int:pk>/depreciate/', views.fixed_asset_depreciate, name='fixed_asset_depreciate'),

    # Reports
    path('reports/', views_reports.financial_reports_dashboard, name='financial_reports_dashboard'),
    path('reports/balance-sheet/', views_reports.generate_balance_sheet, name='generate_balance_sheet'),
    path('reports/income-statement/', views_reports.generate_income_statement, name='generate_income_statement'),
    path('reports/trial-balance/', views_reports.generate_trial_balance, name='generate_trial_balance'),
    path('reports/general-ledger/', views_reports.general_ledger, name='general_ledger'),
    path('reports/cash-flow/', views.generate_cash_flow, name='generate_cash_flow'),
    path('exports/general-ledger/', views_reports.export_general_ledger_csv, name='export_general_ledger_csv'),
    path('expenses/', views.expense_dashboard, name='expense_dashboard'),
    path('expenses/list/', views.expense_list, name='expense_list'),
    path('expenses/create/', views.expense_create, name='expense_create'),
    path('expenses/quick/', views.quick_expense_create, name='quick_expense_create'),
    path('expenses/<int:pk>/', views.expense_detail, name='expense_detail'),
    path('expenses/<int:pk>/approve/', views.expense_approve, name='expense_approve'),
    path('expenses/<int:pk>/reject/', views.expense_reject, name='expense_reject'),

    # Expense Categories
    path('expenses/categories/', views.expense_category_list, name='expense_category_list'),
    path('expenses/', views.expense_dashboard, name='expense_dashboard'),
    path('expenses/list/', views.expense_list, name='expense_list'),
    path('expenses/create/', views.expense_create, name='expense_create'),
    path('expenses/quick/', views.quick_expense_create, name='quick_expense_create'),
    path('expenses/<int:pk>/', views.expense_detail, name='expense_detail'),
    path('expenses/<int:pk>/approve/', views.expense_approve, name='expense_approve'),
    path('expenses/<int:pk>/reject/', views.expense_reject, name='expense_reject'),
    path('expenses/report/', views.expense_report, name='expense_report'),
    path('expenses/export/', views.export_expense_report, name='export_expense_report'),

    # Expense Categories
    path('expenses/categories/', views.expense_category_list, name='expense_category_list'),
    path('expenses/categories/create/', views.expense_category_create, name='expense_category_create'),
    path('expenses/categories/<int:pk>/update/', views.expense_category_update, name='expense_category_update'),
    path('expenses/categories/<int:pk>/delete/', views.expense_category_delete, name='expense_category_delete'),

    # Petty Cash
    path('expenses/petty-cash/', views.petty_cash_list, name='petty_cash_list'),
    path('expenses/petty-cash/create/', views.petty_cash_create, name='petty_cash_create'),
    path('expenses/petty-cash/<int:pk>/replenish/', views.petty_cash_replenish, name='petty_cash_replenish'),
    # Tax
    path('tax/codes/', views_reports.tax_code_list, name='tax_code_list'),
    path('tax/report/', views_reports.tax_report, name='tax_report'),

    # Exports
    path('exports/trial-balance/', views_reports.export_trial_balance_csv, name='export_trial_balance_csv'),
    path('exports/general-ledger/', views.export_general_ledger, name='export_general_ledger'),
    path('currency/create/', views.currency_create, name='currency_create'),
    path('currency/<int:pk>/update/', views.currency_update, name='currency_update'),
    path('exchange-rates/create/', views.exchange_rate_create, name='exchange_rate_create'),

    # Dimensions
    path('dimensions/create/', views.dimension_create, name='dimension_create'),
    path('dimensions/<int:pk>/update/', views.dimension_update, name='dimension_update'),
    path('dimensions/<int:dimension_pk>/values/create/', views.dimension_value_create, name='dimension_value_create'),

    # Fiscal Year
    path('fiscal-years/create/', views.fiscal_year_create, name='fiscal_year_create'),
    path('fiscal-years/<int:pk>/close/', views.fiscal_year_close, name='fiscal_year_close'),

    # Journals
    path('journals/', views.journal_list, name='journal_list'),
    path('journals/create/', views.journal_create, name='journal_create'),

    # Recurring Entries
    path('recurring-entries/create/', views.recurring_entry_create, name='recurring_entry_create'),
    path('recurring-entries/<int:pk>/update/', views.recurring_entry_update, name='recurring_entry_update'),

    # Bank Accounts
    path('bank-accounts/create/', views.bank_account_create, name='bank_account_create'),
    path('bank-accounts/<int:pk>/update/', views.bank_account_update, name='bank_account_update'),

    # Transactions
    path('transactions/', views.transaction_list, name='transaction_list'),
    path('transactions/<int:pk>/', views.transaction_detail, name='transaction_detail'),
    path('transactions/<int:pk>/update/', views.transaction_update, name='transaction_update'),
    path('transactions/<int:pk>/clear/', views.transaction_clear, name='transaction_clear'),

    # Budgets
    path('budgets/create/', views.budget_create, name='budget_create'),
    path('budgets/<int:pk>/update/', views.budget_update, name='budget_update'),

    # Fixed Assets
    path('fixed-assets/create/', views.fixed_asset_create, name='fixed_asset_create'),
    path('fixed-assets/<int:pk>/update/', views.fixed_asset_update, name='fixed_asset_update'),

    # Tax Codes
    path('tax/codes/create/', views.tax_code_create, name='tax_code_create'),
    path('tax/codes/<int:pk>/update/', views.tax_code_update, name='tax_code_update'),

    # Bulk Operations
    path('journal-entries/bulk-create/', views.journal_entry_bulk_create, name='journal_entry_bulk_create'),

    # AJAX Endpoints
    path('ajax/account/<int:account_id>/balance/', views.ajax_get_account_balance, name='ajax_account_balance'),
    path('ajax/exchange-rate/', views.ajax_get_exchange_rate, name='ajax_exchange_rate'),
    path('ajax/fiscal-year/<int:fiscal_year_id>/periods/', views.ajax_get_fiscal_periods, name='ajax_fiscal_periods'),
]