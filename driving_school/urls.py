from django.urls import path
from . import views

app_name = 'driving_school'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Students
    path('students/', views.students_list, name='students'),
    path('students/new/', views.student_create, name='student_create'),
    path('students/<int:pk>/', views.student_detail, name='student_detail'),
    path('students/<int:pk>/edit/', views.student_edit, name='student_edit'),

    # Courses
    path('courses/', views.courses_list, name='courses'),
    path('courses/new/', views.course_create, name='course_create'),
    path('courses/<int:pk>/edit/', views.course_edit, name='course_edit'),
    path('courses/<int:pk>/price/', views.course_price_api, name='course_price_api'),

    # Enrollments
    path('enrollments/', views.enrollments_list, name='enrollments'),
    path('enrollments/new/', views.enrollment_create, name='enrollment_create'),
    path('enrollments/<int:pk>/', views.enrollment_detail, name='enrollment_detail'),
    path('enrollments/<int:pk>/status/', views.enrollment_update_status, name='enrollment_update_status'),

    # Payments
    path('enrollments/<int:enrollment_pk>/pay/', views.payment_add, name='payment_add'),
    path('payments/<int:pk>/void/', views.payment_void, name='payment_void'),
    path('payments/<int:pk>/receipt/', views.payment_receipt, name='payment_receipt'),

    # Schedule / Sessions
    path('schedule/', views.schedule, name='schedule'),
    path('sessions/new/', views.session_create, name='session_create'),
    path('sessions/<int:pk>/edit/', views.session_edit, name='session_edit'),
    path('sessions/<int:pk>/delete/', views.session_delete, name='session_delete'),
    path('sessions/<int:pk>/status/', views.session_update_status, name='session_update_status'),

    # Instructors
    path('instructors/', views.instructors_list, name='instructors'),
    path('instructors/new/', views.instructor_create, name='instructor_create'),
    path('instructors/<int:pk>/edit/', views.instructor_edit, name='instructor_edit'),

    # Fleet
    path('fleet/', views.fleet_list, name='fleet'),
    path('fleet/new/', views.vehicle_create, name='vehicle_create'),
    path('fleet/<int:pk>/edit/', views.vehicle_edit, name='vehicle_edit'),

    # Tests
    path('tests/', views.tests_list, name='tests'),
    path('tests/new/', views.test_create, name='test_create'),
    path('tests/<int:pk>/edit/', views.test_edit, name='test_edit'),

    # Reports
    path('reports/', views.reports, name='reports'),

    # ── JSON APIs (all return application/json) ──────────────────────────────
    path('api/sessions/', views.api_sessions_for_date, name='api_sessions_for_date'),
    path('api/conflicts/', views.api_check_conflicts, name='api_check_conflicts'),
    path('api/dashboard/', views.api_dashboard_data, name='api_dashboard_data'),
    path('api/reports/', views.api_reports_data, name='api_reports_data'),
    path('api/schedule-heatmap/', views.api_schedule_heatmap, name='api_schedule_heatmap'),
    path('api/student/<int:pk>/progress/', views.api_student_progress, name='api_student_progress'),
    path('api/search/', views.api_global_search, name='api_global_search'),
]
