from django.contrib import admin
from .models import (
    DrivingCourse, Student, Enrollment, Payment,
    Instructor, Vehicle, LessonSession, TestRecord
)


@admin.register(DrivingCourse)
class DrivingCourseAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'category', 'price', 'duration_lessons', 'is_active']
    list_filter = ['category', 'is_active']
    search_fields = ['name', 'code']


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ['student_number', 'full_name', 'phone', 'email', 'is_active', 'created_at']
    list_filter = ['is_active', 'gender']
    search_fields = ['first_name', 'last_name', 'phone', 'student_number', 'national_id']


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ['enrollment_number', 'student', 'course', 'status', 'agreed_fee', 'date_enrolled']
    list_filter = ['status']
    search_fields = ['enrollment_number', 'student__first_name', 'student__last_name']


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['enrollment', 'amount', 'method', 'date_paid', 'is_voided']
    list_filter = ['method', 'is_voided']


@admin.register(Instructor)
class InstructorAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'phone', 'license_number', 'license_expiry', 'is_active']
    list_filter = ['is_active']
    search_fields = ['first_name', 'last_name', 'phone']


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ['plate_number', 'make', 'model', 'transmission', 'status', 'is_active']
    list_filter = ['transmission', 'status', 'is_active']


@admin.register(LessonSession)
class LessonSessionAdmin(admin.ModelAdmin):
    list_display = ['enrollment', 'date', 'start_time', 'instructor', 'vehicle', 'status']
    list_filter = ['status', 'date']


@admin.register(TestRecord)
class TestRecordAdmin(admin.ModelAdmin):
    list_display = ['enrollment', 'test_type', 'test_date', 'result', 'score']
    list_filter = ['test_type', 'result']
