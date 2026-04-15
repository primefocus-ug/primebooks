from django.urls import path
from . import views
from branches.views import BranchCreateView,BranchDeleteView,BranchDetailView,BranchListView,BranchUpdateView, GetBranchesAjaxView
from company.views.pause_views import EFRISModeToggleView


app_name = 'company'

urlpatterns = [
    path('auto-save/', views.CompanyAutoSaveView.as_view(), name='company_auto_save'),
    path('get-branches/', GetBranchesAjaxView.as_view(), name='get_branches_ajax'),
    path('company-stats/', views.CompanyStatsAPIView.as_view(), name='company_stats_api'),
    path('status/', views.api_company_status, name='status'),
    path(
        'settings/efris/mode/',
        EFRISModeToggleView.as_view(),
        name='efris_mode_toggle',
    ),
]
