from django.urls import path
from .views import PublicStaffLoginView, PublicStaffLogoutView

app_name = 'public_admin'

urlpatterns = [
    path('login/', PublicStaffLoginView.as_view(), name='login'),
    path('logout/', PublicStaffLogoutView.as_view(), name='logout'),
]