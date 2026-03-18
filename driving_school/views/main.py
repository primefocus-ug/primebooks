from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Sum, Count, Q, Avg
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET
from django.urls import reverse
import json, datetime, calendar

from ..models import (
    DrivingCourse, Student, Enrollment, Payment,
    Instructor, Vehicle, LessonSession, TestRecord,
    EnrollmentStatus, PaymentMethod, SessionStatus, TestResult
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _is_ajax(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'

def _month_range(today, months_back):
    """Yield (month_start, month_end, label) for the last N months."""
    for i in range(months_back - 1, -1, -1):
        m = today.month - i
        y = today.year
        while m < 1: m += 12; y -= 1
        ms = datetime.date(y, m, 1)
        me = datetime.date(y, m + 1, 1) if m < 12 else datetime.date(y + 1, 1, 1)
        yield ms, me, ms.strftime('%b')

def _check_conflicts(date, start_time, duration_minutes,
                     instructor_pk=None, vehicle_pk=None, exclude_session_pk=None):
    conflicts = []
    if not date or not start_time:
        return conflicts
    try:
        if isinstance(date, str):
            date = datetime.date.fromisoformat(date)
        if isinstance(start_time, str):
            parts = start_time.split(':')
            start_time = datetime.time(int(parts[0]), int(parts[1]))
        duration_minutes = int(duration_minutes or 60)
    except (ValueError, TypeError):
        return conflicts

    start_dt = datetime.datetime.combine(date, start_time)
    end_dt   = start_dt + datetime.timedelta(minutes=duration_minutes)

    qs = LessonSession.objects.filter(date=date, status__in=['scheduled', 'rescheduled'])
    if exclude_session_pk:
        qs = qs.exclude(pk=exclude_session_pk)

    for s in qs.select_related('enrollment__student', 'instructor', 'vehicle'):
        s_start = datetime.datetime.combine(date, s.start_time)
        s_end   = s_start + datetime.timedelta(minutes=s.duration_minutes)
        if start_dt < s_end and end_dt > s_start:
            if instructor_pk and s.instructor_id and str(s.instructor_id) == str(instructor_pk):
                conflicts.append(
                    f"Instructor '{s.instructor.full_name}' already booked at "
                    f"{s.start_time.strftime('%H:%M')} with {s.enrollment.student.full_name}.")
            if vehicle_pk and s.vehicle_id and str(s.vehicle_id) == str(vehicle_pk):
                conflicts.append(
                    f"Vehicle '{s.vehicle.plate_number}' already assigned at "
                    f"{s.start_time.strftime('%H:%M')} for {s.enrollment.student.full_name}.")
    return conflicts


# ─────────────────────────────────────────────────────────────────────────────
# JSON API ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def api_sessions_for_date(request):
    date_str = request.GET.get('date', '')
    try:
        date = datetime.date.fromisoformat(date_str)
    except ValueError:
        return JsonResponse({'sessions': []})
    sessions = LessonSession.objects.filter(date=date).select_related(
        'enrollment__student', 'enrollment__course', 'instructor', 'vehicle'
    ).order_by('start_time')
    return JsonResponse({'sessions': [
        {'id': s.pk,
         'student': s.enrollment.student.full_name,
         'course': s.enrollment.course.name,
         'time': s.start_time.strftime('%H:%M'),
         'end_time': (datetime.datetime.combine(date, s.start_time) +
                      datetime.timedelta(minutes=s.duration_minutes)).strftime('%H:%M'),
         'duration': s.duration_minutes,
         'status': s.status,
         'status_display': s.get_status_display(),
         'instructor': s.instructor.full_name if s.instructor else '—',
         'vehicle': s.vehicle.plate_number if s.vehicle else '—',
         'lesson_number': s.lesson_number,
         'edit_url': reverse('driving_school:session_edit', args=[s.pk]),
         'delete_url': reverse('driving_school:session_delete', args=[s.pk]),
         'status_url': reverse('driving_school:session_update_status', args=[s.pk])}
        for s in sessions
    ], 'date': date_str})


@login_required
def api_check_conflicts(request):
    conflicts = _check_conflicts(
        request.GET.get('date'), request.GET.get('start_time'),
        request.GET.get('duration', 60),
        request.GET.get('instructor') or None,
        request.GET.get('vehicle') or None,
        request.GET.get('exclude') or None,
    )
    return JsonResponse({'conflicts': conflicts})


@login_required
def api_dashboard_data(request):
    """Rich JSON for dashboard charts."""
    today = timezone.now().date()

    # Revenue & enrollments — last 12 months
    revenue_series, enroll_series, labels = [], [], []
    for ms, me, label in _month_range(today, 12):
        labels.append(label)
        rev = Payment.objects.filter(is_voided=False, date_paid__gte=ms, date_paid__lt=me
                                     ).aggregate(t=Sum('amount'))['t'] or 0
        revenue_series.append(float(rev))
        cnt = Enrollment.objects.filter(date_enrolled__gte=ms, date_enrolled__lt=me).count()
        enroll_series.append(cnt)

    # Enrollment by status (doughnut)
    status_data = {s: Enrollment.objects.filter(status=s).count()
                   for s, _ in EnrollmentStatus.choices}

    # Session status breakdown (doughnut)
    session_status = {}
    for val, label in SessionStatus.choices:
        session_status[label] = LessonSession.objects.filter(status=val).count()

    # Pass rates
    theory_total    = TestRecord.objects.filter(test_type='theory').count()
    theory_pass     = TestRecord.objects.filter(test_type='theory',    result='pass').count()
    practical_total = TestRecord.objects.filter(test_type='practical').count()
    practical_pass  = TestRecord.objects.filter(test_type='practical', result='pass').count()

    # Instructor workload — last 30 days
    cutoff = today - datetime.timedelta(days=30)
    instructor_workload = list(
        Instructor.objects.filter(is_active=True).annotate(
            recent_sessions=Count('sessions', filter=Q(sessions__date__gte=cutoff)),
            total_sessions=Count('sessions')
        ).values('first_name', 'last_name', 'recent_sessions', 'total_sessions')
        .order_by('-recent_sessions')[:8]
    )
    for i in instructor_workload:
        i['name'] = f"{i['first_name']} {i['last_name']}"

    # Revenue by course (top 6)
    course_revenue = list(
        DrivingCourse.objects.annotate(
            revenue=Sum('enrollments__payments__amount',
                        filter=Q(enrollments__payments__is_voided=False))
        ).filter(revenue__gt=0).values('name', 'revenue').order_by('-revenue')[:6]
    )
    for c in course_revenue:
        c['revenue'] = float(c['revenue'] or 0)

    # Daily session counts — last 90 days for heatmap
    day_counts = {}
    sessions_90 = LessonSession.objects.filter(
        date__gte=today - datetime.timedelta(days=89)
    ).values('date').annotate(count=Count('id'))
    for row in sessions_90:
        day_counts[row['date'].isoformat()] = row['count']

    return JsonResponse({
        'labels': labels,
        'revenue_series': revenue_series,
        'enroll_series': enroll_series,
        'status_data': status_data,
        'session_status': session_status,
        'theory_pass_rate': round(theory_pass / theory_total * 100) if theory_total else 0,
        'practical_pass_rate': round(practical_pass / practical_total * 100) if practical_total else 0,
        'theory_total': theory_total, 'theory_pass': theory_pass,
        'practical_total': practical_total, 'practical_pass': practical_pass,
        'instructor_workload': instructor_workload,
        'course_revenue': course_revenue,
        'day_counts': day_counts,
    })


@login_required
def api_reports_data(request):
    today = timezone.now().date()

    # Monthly revenue + breakdown by course — last 12 months
    revenue_by_month = []
    course_names = list(DrivingCourse.objects.filter(is_active=True).values_list('name', flat=True)[:5])
    for ms, me, label in _month_range(today, 12):
        row = {'month': label, 'total': 0}
        for cn in course_names:
            r = Payment.objects.filter(
                is_voided=False, date_paid__gte=ms, date_paid__lt=me,
                enrollment__course__name=cn
            ).aggregate(t=Sum('amount'))['t'] or 0
            row[cn] = float(r)
            row['total'] += float(r)
        revenue_by_month.append(row)

    # Outstanding per enrollment
    top_outstanding = []
    for e in (Enrollment.objects.filter(status=EnrollmentStatus.ACTIVE)
              .select_related('student', 'course').order_by('-agreed_fee')[:10]):
        bal = float(e.balance)
        if bal > 0:
            top_outstanding.append({
                'student': e.student.full_name,
                'course': e.course.name,
                'balance': bal,
                'total_fee': float(e.total_fee),
            })

    # Lesson completion rate by instructor
    instructor_completion = list(
        Instructor.objects.filter(is_active=True).annotate(
            total=Count('sessions'),
            completed=Count('sessions', filter=Q(sessions__status='completed')),
            missed=Count('sessions', filter=Q(sessions__status='missed')),
        ).values('first_name', 'last_name', 'total', 'completed', 'missed')
        .filter(total__gt=0).order_by('-total')[:8]
    )
    for i in instructor_completion:
        i['name'] = f"{i['first_name']} {i['last_name']}"
        i['rate'] = round(i['completed'] / i['total'] * 100) if i['total'] else 0

    # Test scores scatter data
    test_scatter = list(
        TestRecord.objects.filter(score__isnull=False, max_score__isnull=False, max_score__gt=0)
        .select_related('enrollment__course')
        .values('score', 'max_score', 'result', 'test_type')[:100]
    )
    for t in test_scatter:
        t['pct'] = round(float(t['score']) / float(t['max_score']) * 100, 1)

    return JsonResponse({
        'revenue_by_month': revenue_by_month,
        'course_names': course_names,
        'top_outstanding': top_outstanding,
        'instructor_completion': instructor_completion,
        'test_scatter': test_scatter,
    })


@login_required
def api_schedule_heatmap(request):
    """Session count by day-of-week × hour for last 90 days."""
    cutoff = timezone.now().date() - datetime.timedelta(days=89)
    sessions = LessonSession.objects.filter(date__gte=cutoff).values('date', 'start_time')
    grid = [[0]*24 for _ in range(7)]  # [weekday][hour]
    for s in sessions:
        dow = s['date'].weekday()  # 0=Mon
        hr  = s['start_time'].hour
        grid[dow][hr] += 1
    return JsonResponse({'grid': grid,
                         'days': ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']})


@login_required
def api_student_progress(request, pk):
    student = get_object_or_404(Student, pk=pk)
    data = []
    for e in student.enrollments.select_related('course').order_by('-created_at'):
        sessions = list(e.sessions.values('lesson_number', 'date', 'status', 'start_time')
                        .order_by('lesson_number'))
        data.append({
            'enrollment_number': e.enrollment_number,
            'course': e.course.name,
            'total_lessons': e.course.duration_lessons,
            'sessions': [
                {'n': s['lesson_number'], 'date': s['date'].isoformat() if s['date'] else None,
                 'status': s['status']} for s in sessions
            ]
        })
    return JsonResponse({'enrollments': data})


@login_required
def api_global_search(request):
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    results = []
    for s in Student.objects.filter(
        Q(first_name__icontains=q)|Q(last_name__icontains=q)|Q(phone__icontains=q)|Q(student_number__icontains=q)
    ).filter(is_active=True)[:5]:
        results.append({'type': 'Student', 'label': s.full_name,
                        'sub': s.student_number, 'url': reverse('driving_school:student_detail', args=[s.pk])})
    for e in Enrollment.objects.filter(enrollment_number__icontains=q).select_related('student')[:3]:
        results.append({'type': 'Enrollment', 'label': e.enrollment_number,
                        'sub': e.student.full_name, 'url': reverse('driving_school:enrollment_detail', args=[e.pk])})
    return JsonResponse({'results': results})


# ─────────────────────────────────────────────────────────────────────────────
# PAGE VIEWS  (return HTML; AJAX requests get partial context flag)
# ─────────────────────────────────────────────────────────────────────────────

def _render(request, ctx):
    """Adds is_ajax flag so template can omit chrome if needed."""
    ctx['is_ajax_nav'] = _is_ajax(request)
    return render(request, 'driving_school/app.html', ctx)


@login_required
def dashboard(request):
    today = timezone.now().date()
    this_month = today.replace(day=1)

    total_students      = Student.objects.filter(is_active=True).count()
    active_enrollments  = Enrollment.objects.filter(status=EnrollmentStatus.ACTIVE).count()
    today_sessions      = LessonSession.objects.filter(date=today).count()
    monthly_revenue     = Payment.objects.filter(date_paid__gte=this_month, is_voided=False).aggregate(t=Sum('amount'))['t'] or 0
    week_start          = today - datetime.timedelta(days=today.weekday())
    weekly_revenue      = Payment.objects.filter(date_paid__gte=week_start, is_voided=False).aggregate(t=Sum('amount'))['t'] or 0

    total_practical = TestRecord.objects.filter(test_type='practical').count()
    passed_practical = TestRecord.objects.filter(test_type='practical', result='pass').count()
    pass_rate = round((passed_practical / total_practical * 100) if total_practical else 0)

    recent_enrollments = Enrollment.objects.select_related('student', 'course').order_by('-created_at')[:5]
    todays_sessions = LessonSession.objects.filter(date=today).select_related(
        'enrollment__student', 'instructor', 'vehicle').order_by('start_time')
    upcoming_tests = TestRecord.objects.filter(
        test_date__gte=today, result='pending').select_related('enrollment__student').order_by('test_date')[:5]

    return _render(request, {
        'section': 'dashboard',
        'total_students': total_students, 'active_enrollments': active_enrollments,
        'today_sessions': today_sessions, 'monthly_revenue': monthly_revenue,
        'weekly_revenue': weekly_revenue, 'pass_rate': pass_rate,
        'recent_enrollments': recent_enrollments, 'todays_sessions': todays_sessions,
        'upcoming_tests': upcoming_tests,
        'api_dashboard_url': reverse('driving_school:api_dashboard_data'),
        'api_heatmap_url': reverse('driving_school:api_schedule_heatmap'),
    })


@login_required
def students_list(request):
    q = request.GET.get('q', '')
    students = Student.objects.filter(is_active=True)
    if q:
        students = students.filter(
            Q(first_name__icontains=q)|Q(last_name__icontains=q)|
            Q(phone__icontains=q)|Q(student_number__icontains=q)|Q(national_id__icontains=q)
        )
    return _render(request, {'section': 'students', 'students': students.order_by('-created_at'), 'q': q})


@login_required
def student_detail(request, pk):
    student = get_object_or_404(Student, pk=pk)
    enrollments = student.enrollments.select_related('course').order_by('-created_at')
    return _render(request, {
        'section': 'student_detail', 'student': student, 'enrollments': enrollments,
        'api_progress_url': reverse('driving_school:api_student_progress', args=[pk]),
    })


@login_required
def student_create(request):
    if request.method == 'POST':
        data = request.POST
        student = Student(
            first_name=data.get('first_name','').strip(), last_name=data.get('last_name','').strip(),
            gender=data.get('gender',''), phone=data.get('phone','').strip(),
            email=data.get('email','').strip(), address=data.get('address','').strip(),
            national_id=data.get('national_id','').strip(),
            emergency_contact_name=data.get('emergency_contact_name','').strip(),
            emergency_contact_phone=data.get('emergency_contact_phone','').strip(),
            emergency_contact_relation=data.get('emergency_contact_relation','').strip(),
            notes=data.get('notes','').strip(),
        )
        dob = data.get('date_of_birth','')
        if dob:
            try: student.date_of_birth = datetime.date.fromisoformat(dob)
            except ValueError: pass
        if request.FILES.get('photo'): student.photo = request.FILES['photo']
        student.save()
        if _is_ajax(request):
            return JsonResponse({'ok': True, 'redirect': reverse('driving_school:student_detail', args=[student.pk]),
                                 'message': f"Student {student.full_name} ({student.student_number}) created."})
        messages.success(request, f"Student {student.full_name} ({student.student_number}) created.")
        return redirect('driving_school:student_detail', pk=student.pk)
    return _render(request, {'section': 'student_create'})


@login_required
def student_edit(request, pk):
    student = get_object_or_404(Student, pk=pk)
    if request.method == 'POST':
        data = request.POST
        student.first_name = data.get('first_name', student.first_name).strip()
        student.last_name  = data.get('last_name',  student.last_name).strip()
        student.gender     = data.get('gender',     student.gender)
        student.phone      = data.get('phone',      student.phone).strip()
        student.email      = data.get('email',      student.email).strip()
        student.address    = data.get('address',    student.address).strip()
        student.national_id = data.get('national_id', student.national_id).strip()
        student.emergency_contact_name     = data.get('emergency_contact_name',     student.emergency_contact_name).strip()
        student.emergency_contact_phone    = data.get('emergency_contact_phone',    student.emergency_contact_phone).strip()
        student.emergency_contact_relation = data.get('emergency_contact_relation', student.emergency_contact_relation).strip()
        student.notes = data.get('notes', student.notes).strip()
        dob = data.get('date_of_birth','')
        if dob:
            try: student.date_of_birth = datetime.date.fromisoformat(dob)
            except ValueError: pass
        if request.FILES.get('photo'): student.photo = request.FILES['photo']
        student.save()
        if _is_ajax(request):
            return JsonResponse({'ok': True, 'redirect': reverse('driving_school:student_detail', args=[student.pk]),
                                 'message': f"Student {student.full_name} updated."})
        messages.success(request, f"Student {student.full_name} updated.")
        return redirect('driving_school:student_detail', pk=student.pk)
    return _render(request, {'section': 'student_edit', 'student': student})


@login_required
def courses_list(request):
    return _render(request, {'section': 'courses',
                              'courses': DrivingCourse.objects.filter(is_active=True).order_by('code')})


@login_required
def course_create(request):
    if request.method == 'POST':
        data = request.POST
        c = DrivingCourse(name=data.get('name','').strip(), code=data.get('code','').strip().upper(),
                          category=data.get('category','OTHER'), description=data.get('description','').strip(),
                          price=data.get('price',0), duration_lessons=data.get('duration_lessons',10),
                          duration_days=data.get('duration_days',30))
        c.save()
        if _is_ajax(request):
            return JsonResponse({'ok': True, 'redirect': reverse('driving_school:courses'), 'message': 'Course created.'})
        messages.success(request, 'Course created.')
        return redirect('driving_school:courses')
    from ..models.course import CourseCategory
    return _render(request, {'section': 'course_create', 'categories': CourseCategory.choices})


@login_required
def course_edit(request, pk):
    course = get_object_or_404(DrivingCourse, pk=pk)
    if request.method == 'POST':
        data = request.POST
        course.name = data.get('name', course.name).strip()
        course.code = data.get('code', course.code).strip().upper()
        course.category = data.get('category', course.category)
        course.description = data.get('description', course.description).strip()
        course.price = data.get('price', course.price)
        course.duration_lessons = data.get('duration_lessons', course.duration_lessons)
        course.duration_days = data.get('duration_days', course.duration_days)
        course.is_active = data.get('is_active') == 'on'
        course.save()
        if _is_ajax(request):
            return JsonResponse({'ok': True, 'redirect': reverse('driving_school:courses'), 'message': f'{course.name} updated.'})
        messages.success(request, f"Course {course.name} updated.")
        return redirect('driving_school:courses')
    from ..models.course import CourseCategory
    return _render(request, {'section': 'course_edit', 'course': course, 'categories': CourseCategory.choices})


@login_required
def enrollments_list(request):
    status_filter = request.GET.get('status','')
    enrollments = Enrollment.objects.select_related('student','course')
    if status_filter: enrollments = enrollments.filter(status=status_filter)
    return _render(request, {'section': 'enrollments', 'enrollments': enrollments.order_by('-created_at'),
                              'status_filter': status_filter, 'status_choices': EnrollmentStatus.choices})


@login_required
def enrollment_detail(request, pk):
    enrollment = get_object_or_404(Enrollment.objects.select_related('student','course'), pk=pk)
    payments = enrollment.payments.filter(is_voided=False).order_by('-date_paid')
    sessions = enrollment.sessions.select_related('instructor','vehicle').order_by('date','start_time')
    tests = enrollment.test_records.order_by('-test_date')
    total_lessons = enrollment.course.duration_lessons
    session_list  = list(sessions)
    lesson_slots  = [{'number': i, 'session': next((s for s in session_list if s.lesson_number == i), None)}
                     for i in range(1, total_lessons + 1)]
    return _render(request, {
        'section': 'enrollment_detail', 'enrollment': enrollment,
        'payments': payments, 'sessions': sessions, 'tests': tests, 'lesson_slots': lesson_slots,
        'payment_methods': PaymentMethod.choices, 'session_statuses': SessionStatus.choices,
        'instructors': Instructor.objects.filter(is_active=True),
        'vehicles': Vehicle.objects.filter(is_active=True),
        'status_choices': EnrollmentStatus.choices,
    })


@login_required
def enrollment_create(request):
    if request.method == 'POST':
        data = request.POST
        student  = get_object_or_404(Student,     pk=data.get('student'))
        course   = get_object_or_404(DrivingCourse, pk=data.get('course'))
        enrollment = Enrollment(student=student, course=course,
                                agreed_fee=data.get('agreed_fee', course.price),
                                discount=data.get('discount',0),
                                notes=data.get('notes','').strip(),
                                status=EnrollmentStatus.ACTIVE, created_by=request.user)
        exp = data.get('expected_completion','')
        if exp:
            try: enrollment.expected_completion = datetime.date.fromisoformat(exp)
            except ValueError: pass
        enrollment.save()
        if _is_ajax(request):
            return JsonResponse({'ok': True,
                                 'redirect': reverse('driving_school:enrollment_detail', args=[enrollment.pk]),
                                 'message': f"Enrollment {enrollment.enrollment_number} created."})
        messages.success(request, f"Enrollment {enrollment.enrollment_number} created.")
        return redirect('driving_school:enrollment_detail', pk=enrollment.pk)
    return _render(request, {
        'section': 'enrollment_create',
        'students': Student.objects.filter(is_active=True).order_by('first_name'),
        'courses':  DrivingCourse.objects.filter(is_active=True).order_by('code'),
    })


@login_required
@require_POST
def enrollment_update_status(request, pk):
    enrollment = get_object_or_404(Enrollment, pk=pk)
    new_status = request.POST.get('status')
    if new_status in dict(EnrollmentStatus.choices):
        enrollment.status = new_status
        enrollment.save()
        if _is_ajax(request):
            return JsonResponse({'ok': True, 'status': new_status,
                                 'status_display': enrollment.get_status_display(),
                                 'message': f"Status updated to {enrollment.get_status_display()}."})
        messages.success(request, f"Status updated to {enrollment.get_status_display()}.")
    return redirect('driving_school:enrollment_detail', pk=pk)


@login_required
@require_POST
def payment_add(request, enrollment_pk):
    enrollment = get_object_or_404(Enrollment, pk=enrollment_pk)
    data = request.POST
    payment = Payment(enrollment=enrollment, amount=data.get('amount',0),
                      method=data.get('method', PaymentMethod.CASH),
                      reference=data.get('reference','').strip(),
                      notes=data.get('notes','').strip(), received_by=request.user)
    payment.save()
    msg = f"Payment of UGX {float(payment.amount):,.0f} recorded."
    if _is_ajax(request):
        return JsonResponse({'ok': True, 'message': msg,
                             'amount_paid': float(enrollment.amount_paid),
                             'balance': float(enrollment.balance),
                             'receipt_url': reverse('driving_school:payment_receipt', args=[payment.pk]),
                             'payment': {'id': payment.pk, 'amount': float(payment.amount),
                                         'method_display': payment.get_method_display(),
                                         'date': payment.date_paid.strftime('%d %b %Y'),
                                         'reference': payment.reference or '—',
                                         'receipt_url': reverse('driving_school:payment_receipt', args=[payment.pk])}})
    messages.success(request, msg)
    return redirect('driving_school:enrollment_detail', pk=enrollment_pk)


@login_required
@require_POST
def payment_void(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    payment.is_voided = True
    payment.save()
    if _is_ajax(request):
        return JsonResponse({'ok': True, 'message': 'Payment voided.',
                             'amount_paid': float(payment.enrollment.amount_paid),
                             'balance': float(payment.enrollment.balance)})
    messages.warning(request, "Payment voided.")
    return redirect('driving_school:enrollment_detail', pk=payment.enrollment.pk)


@login_required
def payment_receipt(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related('enrollment__student','enrollment__course','received_by'), pk=pk)
    return _render(request, {'section': 'payment_receipt', 'payment': payment})


@login_required
def schedule(request):
    today = timezone.now().date()
    year  = int(request.GET.get('year',  today.year))
    month = int(request.GET.get('month', today.month))
    if month < 1:  month = 12; year -= 1
    if month > 12: month = 1;  year += 1

    cal   = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)

    month_start = datetime.date(year, month, 1)
    month_end   = datetime.date(year, month+1, 1) if month < 12 else datetime.date(year+1, 1, 1)

    month_sessions = LessonSession.objects.filter(
        date__gte=month_start, date__lt=month_end
    ).select_related('enrollment__student','enrollment__course','instructor','vehicle')

    sessions_by_date = {}
    for s in month_sessions:
        sessions_by_date.setdefault(s.date.isoformat(), []).append(s)

    date_str = request.GET.get('date', today.isoformat())
    try:    selected_date = datetime.date.fromisoformat(date_str)
    except: selected_date = today

    day_sessions = LessonSession.objects.filter(date=selected_date).select_related(
        'enrollment__student','enrollment__course','instructor','vehicle').order_by('start_time')

    week_start = selected_date - datetime.timedelta(days=selected_date.weekday())
    week_days  = [week_start + datetime.timedelta(days=i) for i in range(7)]
    week_sessions = LessonSession.objects.filter(
        date__gte=week_days[0], date__lte=week_days[-1]
    ).select_related('enrollment__student','instructor','vehicle').order_by('date','start_time')
    week_by_day = {}
    for s in week_sessions: week_by_day.setdefault(s.date.isoformat(), []).append(s)

    prev_month = month-1 if month>1 else 12; prev_year = year if month>1 else year-1
    next_month = month+1 if month<12 else 1;  next_year = year if month<12 else year+1

    sessions_json = {
        k: [{'id': s.pk, 'student': s.enrollment.student.full_name,
              'time': s.start_time.strftime('%H:%M'), 'status': s.status,
              'course': s.enrollment.course.name,
              'instructor': s.instructor.full_name if s.instructor else '',
              'vehicle': s.vehicle.plate_number if s.vehicle else ''}
             for s in v]
        for k, v in sessions_by_date.items()
    }

    return _render(request, {
        'section': 'schedule', 'today': today, 'year': year, 'month': month,
        'month_name': datetime.date(year, month, 1).strftime('%B %Y'),
        'weeks': weeks, 'sessions_by_date': sessions_by_date,
        'sessions_json': json.dumps(sessions_json, default=str),
        'selected_date': selected_date, 'day_sessions': day_sessions,
        'week_days': week_days, 'week_by_day': week_by_day,
        'prev_year': prev_year, 'prev_month': prev_month,
        'next_year': next_year, 'next_month': next_month,
        'weekday_names': ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'],
        'enrollments': Enrollment.objects.filter(status=EnrollmentStatus.ACTIVE).select_related('student','course'),
        'instructors': Instructor.objects.filter(is_active=True),
        'vehicles':    Vehicle.objects.filter(is_active=True),
        'status_choices': SessionStatus.choices,
        'api_sessions_url': reverse('driving_school:api_sessions_for_date'),
        'api_conflicts_url': reverse('driving_school:api_check_conflicts'),
        'api_heatmap_url': reverse('driving_school:api_schedule_heatmap'),
    })


@login_required
@require_POST
def session_create(request):
    data = request.POST
    enrollment   = get_object_or_404(Enrollment, pk=data.get('enrollment'))
    instructor_pk = data.get('instructor') or None
    vehicle_pk    = data.get('vehicle') or None
    date, start_time, duration = data.get('date'), data.get('start_time'), data.get('duration_minutes', 60)

    conflicts = _check_conflicts(date, start_time, duration, instructor_pk, vehicle_pk)
    if conflicts:
        if _is_ajax(request):
            return JsonResponse({'ok': False, 'conflicts': conflicts}, status=409)
        for c in conflicts: messages.error(request, f"⚠ Conflict: {c}")
        return redirect(f"{reverse('driving_school:schedule')}?date={date}")

    session = LessonSession(enrollment=enrollment, date=date, start_time=start_time,
                            duration_minutes=duration, status=SessionStatus.SCHEDULED,
                            route_notes=data.get('route_notes','').strip())
    if instructor_pk: session.instructor = get_object_or_404(Instructor, pk=instructor_pk)
    if vehicle_pk:    session.vehicle    = get_object_or_404(Vehicle, pk=vehicle_pk)
    session.lesson_number = enrollment.sessions.filter(status='completed').count() + 1
    session.save()

    if _is_ajax(request):
        return JsonResponse({'ok': True, 'message': 'Session scheduled.',
                             'session': {'id': session.pk, 'date': str(session.date),
                                         'time': session.start_time.strftime('%H:%M'),
                                         'status': session.status,
                                         'student': enrollment.student.full_name,
                                         'edit_url': reverse('driving_school:session_edit', args=[session.pk])}})
    messages.success(request, "Session scheduled.")
    return redirect(f"{reverse('driving_school:schedule')}?date={date}")


@login_required
def session_edit(request, pk):
    session = get_object_or_404(
        LessonSession.objects.select_related('enrollment__student','enrollment__course','instructor','vehicle'), pk=pk)
    if request.method == 'POST':
        data = request.POST
        instructor_pk = data.get('instructor') or None
        vehicle_pk    = data.get('vehicle') or None
        date       = data.get('date', str(session.date))
        start_time = data.get('start_time', str(session.start_time))
        duration   = data.get('duration_minutes', session.duration_minutes)

        conflicts = _check_conflicts(date, start_time, duration, instructor_pk, vehicle_pk, exclude_session_pk=pk)
        if conflicts:
            if _is_ajax(request):
                return JsonResponse({'ok': False, 'conflicts': conflicts}, status=409)
            for c in conflicts: messages.error(request, f"⚠ {c}")
            return redirect('driving_school:session_edit', pk=pk)

        session.date = date; session.start_time = start_time; session.duration_minutes = duration
        session.status = data.get('status', session.status)
        session.route_notes = data.get('route_notes', session.route_notes or '').strip()
        session.instructor_notes = data.get('instructor_notes', session.instructor_notes or '').strip()
        session.student_performance = data.get('student_performance', session.student_performance or '').strip()
        session.instructor = get_object_or_404(Instructor, pk=instructor_pk) if instructor_pk else None
        session.vehicle    = get_object_or_404(Vehicle, pk=vehicle_pk) if vehicle_pk else None
        session.save()
        if _is_ajax(request):
            return JsonResponse({'ok': True, 'message': 'Session updated.',
                                 'redirect': f"{reverse('driving_school:schedule')}?date={session.date}"})
        messages.success(request, "Session updated.")
        return redirect(f"{reverse('driving_school:schedule')}?date={session.date}")

    return _render(request, {'section': 'session_edit', 'session': session,
                              'instructors': Instructor.objects.filter(is_active=True),
                              'vehicles':    Vehicle.objects.filter(is_active=True),
                              'status_choices': SessionStatus.choices,
                              'api_conflicts_url': reverse('driving_school:api_check_conflicts')})


@login_required
@require_POST
def session_delete(request, pk):
    session = get_object_or_404(LessonSession, pk=pk)
    date = session.date
    session.delete()
    if _is_ajax(request):
        return JsonResponse({'ok': True, 'message': 'Session deleted.',
                             'redirect': f"{reverse('driving_school:schedule')}?date={date}"})
    messages.success(request, "Session deleted.")
    return redirect(f"{reverse('driving_school:schedule')}?date={date}")


@login_required
@require_POST
def session_update_status(request, pk):
    session = get_object_or_404(LessonSession, pk=pk)
    new_status = request.POST.get('status')
    if new_status in dict(SessionStatus.choices):
        session.status = new_status
        session.instructor_notes    = request.POST.get('instructor_notes',    session.instructor_notes)
        session.student_performance = request.POST.get('student_performance', session.student_performance)
        session.save()
        if _is_ajax(request):
            return JsonResponse({'ok': True, 'status': new_status,
                                 'status_display': session.get_status_display(),
                                 'message': f"Marked as {session.get_status_display()}."})
        messages.success(request, f"Session marked as {session.get_status_display()}.")
    return redirect(f"{reverse('driving_school:schedule')}?date={session.date}")


@login_required
def instructors_list(request):
    return _render(request, {'section': 'instructors', 'today': timezone.now().date(),
                              'instructors': Instructor.objects.filter(is_active=True).order_by('first_name')})


@login_required
def instructor_create(request):
    if request.method == 'POST':
        data = request.POST
        i = Instructor(first_name=data.get('first_name','').strip(), last_name=data.get('last_name','').strip(),
                       phone=data.get('phone','').strip(), email=data.get('email','').strip(),
                       license_number=data.get('license_number','').strip(),
                       specializations=data.get('specializations','').strip(),
                       notes=data.get('notes','').strip())
        exp = data.get('license_expiry','')
        if exp:
            try: i.license_expiry = datetime.date.fromisoformat(exp)
            except ValueError: pass
        if request.FILES.get('photo'): i.photo = request.FILES['photo']
        i.save()
        if _is_ajax(request):
            return JsonResponse({'ok': True, 'redirect': reverse('driving_school:instructors'),
                                 'message': f"Instructor {i.full_name} created."})
        messages.success(request, f"Instructor {i.full_name} created.")
        return redirect('driving_school:instructors')
    return _render(request, {'section': 'instructor_create'})


@login_required
def instructor_edit(request, pk):
    instructor = get_object_or_404(Instructor, pk=pk)
    if request.method == 'POST':
        data = request.POST
        instructor.first_name     = data.get('first_name',     instructor.first_name).strip()
        instructor.last_name      = data.get('last_name',      instructor.last_name).strip()
        instructor.phone          = data.get('phone',          instructor.phone).strip()
        instructor.email          = data.get('email',          instructor.email).strip()
        instructor.license_number = data.get('license_number', instructor.license_number).strip()
        instructor.specializations = data.get('specializations', instructor.specializations).strip()
        instructor.notes          = data.get('notes',          instructor.notes).strip()
        exp = data.get('license_expiry','')
        if exp:
            try: instructor.license_expiry = datetime.date.fromisoformat(exp)
            except ValueError: pass
        if request.FILES.get('photo'): instructor.photo = request.FILES['photo']
        instructor.save()
        if _is_ajax(request):
            return JsonResponse({'ok': True, 'redirect': reverse('driving_school:instructors'),
                                 'message': f"Instructor {instructor.full_name} updated."})
        messages.success(request, f"Instructor {instructor.full_name} updated.")
        return redirect('driving_school:instructors')
    return _render(request, {'section': 'instructor_edit', 'instructor': instructor})


@login_required
def fleet_list(request):
    return _render(request, {'section': 'fleet', 'today': timezone.now().date(),
                              'vehicles': Vehicle.objects.filter(is_active=True).order_by('plate_number'),
                              'transmission_choices': [('manual','Manual'),('automatic','Automatic')],
                              'status_choices': [('available','Available'),('in_use','In Use'),('maintenance','Under Maintenance'),('retired','Retired')]})


@login_required
def vehicle_create(request):
    if request.method == 'POST':
        data = request.POST
        v = Vehicle(plate_number=data.get('plate_number','').strip().upper(),
                    make=data.get('make','').strip(), model=data.get('model','').strip(),
                    color=data.get('color','').strip(), transmission=data.get('transmission','manual'),
                    notes=data.get('notes','').strip())
        yr = data.get('year','')
        if yr:
            try: v.year = int(yr)
            except ValueError: pass
        for f in ['insurance_expiry','service_due_date']:
            val = data.get(f,'')
            if val:
                try: setattr(v, f, datetime.date.fromisoformat(val))
                except ValueError: pass
        v.save()
        if _is_ajax(request):
            return JsonResponse({'ok': True, 'redirect': reverse('driving_school:fleet'),
                                 'message': f"Vehicle {v.plate_number} added."})
        messages.success(request, f"Vehicle {v.plate_number} added.")
        return redirect('driving_school:fleet')
    return _render(request, {'section': 'vehicle_create',
                              'transmission_choices': [('manual','Manual'),('automatic','Automatic')]})


@login_required
def vehicle_edit(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    if request.method == 'POST':
        data = request.POST
        vehicle.plate_number  = data.get('plate_number',  vehicle.plate_number).strip().upper()
        vehicle.make          = data.get('make',          vehicle.make).strip()
        vehicle.model         = data.get('model',         vehicle.model).strip()
        vehicle.color         = data.get('color',         vehicle.color).strip()
        vehicle.transmission  = data.get('transmission',  vehicle.transmission)
        vehicle.status        = data.get('status',        vehicle.status)
        vehicle.notes         = data.get('notes',         vehicle.notes).strip()
        yr = data.get('year','')
        if yr:
            try: vehicle.year = int(yr)
            except ValueError: pass
        for f in ['insurance_expiry','service_due_date']:
            val = data.get(f,'')
            if val:
                try: setattr(vehicle, f, datetime.date.fromisoformat(val))
                except ValueError: pass
        vehicle.save()
        if _is_ajax(request):
            return JsonResponse({'ok': True, 'redirect': reverse('driving_school:fleet'),
                                 'message': f"Vehicle {vehicle.plate_number} updated."})
        messages.success(request, f"Vehicle {vehicle.plate_number} updated.")
        return redirect('driving_school:fleet')
    return _render(request, {'section': 'vehicle_edit', 'vehicle': vehicle,
                              'transmission_choices': [('manual','Manual'),('automatic','Automatic')],
                              'status_choices': [('available','Available'),('in_use','In Use'),('maintenance','Under Maintenance'),('retired','Retired')]})


@login_required
def tests_list(request):
    return _render(request, {'section': 'tests',
                              'tests': TestRecord.objects.select_related('enrollment__student','enrollment__course').order_by('-test_date'),
                              'enrollments': Enrollment.objects.filter(status=EnrollmentStatus.ACTIVE).select_related('student')})


@login_required
@require_POST
def test_create(request):
    data = request.POST
    enrollment = get_object_or_404(Enrollment, pk=data.get('enrollment'))
    test = TestRecord(enrollment=enrollment, test_type=data.get('test_type','theory'),
                      test_date=data.get('test_date'), result=data.get('result', TestResult.PENDING),
                      test_center=data.get('test_center','').strip(),
                      examiner_name=data.get('examiner_name','').strip(),
                      certificate_number=data.get('certificate_number','').strip(),
                      notes=data.get('notes','').strip())
    for attr in ['score','max_score']:
        val = data.get(attr,'')
        if val:
            try: setattr(test, attr, float(val))
            except ValueError: pass
    test.save()
    if _is_ajax(request):
        return JsonResponse({'ok': True, 'message': 'Test record saved.',
                             'redirect': reverse('driving_school:tests')})
    messages.success(request, "Test record saved.")
    return redirect('driving_school:tests')


@login_required
def test_edit(request, pk):
    test = get_object_or_404(TestRecord.objects.select_related('enrollment__student','enrollment__course'), pk=pk)
    if request.method == 'POST':
        data = request.POST
        test.test_type = data.get('test_type', test.test_type)
        test.result    = data.get('result',    test.result)
        test.test_center          = data.get('test_center',         test.test_center).strip()
        test.examiner_name        = data.get('examiner_name',       test.examiner_name).strip()
        test.certificate_number   = data.get('certificate_number',  test.certificate_number).strip()
        test.notes = data.get('notes', test.notes).strip()
        date_val = data.get('test_date','')
        if date_val:
            try: test.test_date = datetime.date.fromisoformat(date_val)
            except ValueError: pass
        for attr in ['score','max_score']:
            val = data.get(attr,'')
            setattr(test, attr, float(val) if val else None)
        test.save()
        if _is_ajax(request):
            return JsonResponse({'ok': True, 'message': 'Test updated.',
                                 'redirect': reverse('driving_school:tests')})
        messages.success(request, "Test record updated.")
        return redirect('driving_school:tests')
    return _render(request, {'section': 'test_edit', 'test': test})


@login_required
def reports(request):
    today = timezone.now().date()
    this_month = today.replace(day=1)
    total_revenue     = Payment.objects.filter(is_voided=False).aggregate(t=Sum('amount'))['t'] or 0
    monthly_revenue   = Payment.objects.filter(is_voided=False, date_paid__gte=this_month).aggregate(t=Sum('amount'))['t'] or 0
    active_enrollments = Enrollment.objects.filter(status=EnrollmentStatus.ACTIVE).select_related('student','course')
    total_outstanding  = sum(e.balance for e in active_enrollments if e.balance > 0)
    enrollment_by_status = {s: Enrollment.objects.filter(status=s).count() for s,_ in EnrollmentStatus.choices}
    course_stats = DrivingCourse.objects.filter(is_active=True).annotate(total_enrollments=Count('enrollments')).order_by('-total_enrollments')[:10]
    theory_total    = TestRecord.objects.filter(test_type='theory').count()
    theory_pass     = TestRecord.objects.filter(test_type='theory',    result='pass').count()
    practical_total = TestRecord.objects.filter(test_type='practical').count()
    practical_pass  = TestRecord.objects.filter(test_type='practical', result='pass').count()
    instructor_stats = Instructor.objects.filter(is_active=True).annotate(
        total_sessions=Count('sessions'),
        completed_sessions=Count('sessions', filter=Q(sessions__status='completed'))
    ).order_by('-total_sessions')
    return _render(request, {
        'section': 'reports',
        'total_revenue': total_revenue, 'monthly_revenue': monthly_revenue,
        'total_outstanding': total_outstanding, 'enrollment_by_status': enrollment_by_status,
        'course_stats': course_stats,
        'theory_total': theory_total, 'theory_pass': theory_pass,
        'theory_pass_rate': round(theory_pass/theory_total*100) if theory_total else 0,
        'practical_total': practical_total, 'practical_pass': practical_pass,
        'practical_pass_rate': round(practical_pass/practical_total*100) if practical_total else 0,
        'instructor_stats': instructor_stats,
        'api_reports_url': reverse('driving_school:api_reports_data'),
        'api_dashboard_url': reverse('driving_school:api_dashboard_data'),
    })


@login_required
def course_price_api(request, pk):
    course = get_object_or_404(DrivingCourse, pk=pk)
    return JsonResponse({'price': str(course.price), 'duration_lessons': course.duration_lessons})
