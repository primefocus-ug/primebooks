"""
reports/urls.py
"""
from django.urls import path
from . import views

app_name = 'suggestions'

urlpatterns = [
    path('submit/',                       views.submit_report,   name='report_submit'),
    path('mine/',                         views.my_reports,      name='report_my_reports'),
    path('<str:ticket_number>/',          views.report_detail,   name='report_detail'),
    path('<str:ticket_number>/feedback/', views.submit_feedback, name='report_feedback'),
]