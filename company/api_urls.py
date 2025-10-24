from django.urls import path
from . import views
from branches.views import BranchCreateView,BranchDeleteView,BranchDetailView,BranchListView,BranchUpdateView, GetBranchesAjaxView

app_name = 'company'

urlpatterns = [
    path('auto-save/', views.CompanyAutoSaveView.as_view(), name='company_auto_save'),
    path('get-branches/', GetBranchesAjaxView.as_view(), name='get_branches_ajax'),
    path('company-stats/', views.CompanyStatsAPIView.as_view(), name='company_stats_api'),
    path('status/', views.api_company_status, name='status'),
]
