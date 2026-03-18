# Driving School App — Plug-in Guide

## 1. Copy the app
Place the `driving_school/` folder in your Django project root
(same level as your other apps like `sales`, `restaurant`, etc.)

---

## 2. settings.py — Add to TENANT_APPS

```python
TENANT_APPS = [
    # ... existing apps ...
    'driving_school',
]
```

---

## 3. URLs — Add to your tenant urlconf

In your tenant `urls.py` (the file referenced by `TENANT_URLCONF`):

```python
from django.urls import path, include

urlpatterns = [
    # ... existing urls ...
    path('driving-school/', include('driving_school.urls', namespace='driving_school')),
]
```

---

## 4. navigation.py — Add navigation items

Open your main `navigation.py` and add to `NAVIGATION_ITEMS` list:

```python
# ── Driving School (pluggable) ────────────────────────────────
NavigationItem(
    name="Driving School",
    icon="bi bi-car-front",
    requires_module="driving_school",
    children=[
        NavigationItem(name="Dashboard",    url_name="driving_school:dashboard",    icon="bi bi-speedometer2",   requires_module="driving_school"),
        NavigationItem(name="Students",     url_name="driving_school:students",     icon="bi bi-people",         permission="driving_school.view_student",       requires_module="driving_school"),
        NavigationItem(name="Enrollments",  url_name="driving_school:enrollments",  icon="bi bi-journal-check",  permission="driving_school.view_enrollment",    requires_module="driving_school"),
        NavigationItem(name="Schedule",     url_name="driving_school:schedule",     icon="bi bi-calendar3",      permission="driving_school.view_lessonsession", requires_module="driving_school"),
        NavigationItem(name="Instructors",  url_name="driving_school:instructors",  icon="bi bi-person-badge",   permission="driving_school.view_instructor",    requires_module="driving_school"),
        NavigationItem(name="Fleet",        url_name="driving_school:fleet",        icon="bi bi-truck",          permission="driving_school.view_vehicle",       requires_module="driving_school"),
        NavigationItem(name="Courses",      url_name="driving_school:courses",      icon="bi bi-book",           permission="driving_school.view_drivingcourse", requires_module="driving_school"),
        NavigationItem(name="Tests",        url_name="driving_school:tests",        icon="bi bi-patch-check",    permission="driving_school.view_testrecord",    requires_module="driving_school"),
        NavigationItem(name="Reports",      url_name="driving_school:reports",      icon="bi bi-bar-chart-line", permission="driving_school.view_enrollment",    requires_module="driving_school"),
    ]
),
```

---

## 5. App Store / Module activation

In your App Store / module registry, register the module key:

```python
MODULE_KEY = 'driving_school'
```

When a tenant activates "Driving School" from the App Store,
`driving_school` gets added to `request.active_modules` and
all nav items automatically appear for that tenant.

---

## 6. Run migrations

```bash
python manage.py makemigrations driving_school
python manage.py migrate
```

For tenant-aware migrations (django-tenants):
```bash
python manage.py migrate_schemas --shared   # if models are in shared schema
python manage.py migrate_schemas            # for all tenant schemas
```

---

## 7. Media files (optional)

Student and instructor photos upload to:
- `driving_school/students/`
- `driving_school/instructors/`

Make sure your `MEDIA_ROOT` is configured. The app uses Django's
`TenantFileSystemStorage` automatically via your `DEFAULT_FILE_STORAGE` setting.

---

## 8. Template

The entire app lives in one template:
```
driving_school/templates/driving_school/app.html
```

It extends `base.html` and uses `[data-theme='dark']` for dark mode —
your existing base.html theme switcher handles it automatically.

No extra CSS files. No extra JS files. Self-contained.

---

## App Structure Summary

```
driving_school/
├── models/
│   ├── course.py        — DrivingCourse (packages & pricing)
│   ├── student.py       — Student (profiles)
│   ├── enrollment.py    — Enrollment + Payment
│   ├── instructor.py    — Instructor
│   ├── vehicle.py       — Vehicle / Fleet
│   ├── session.py       — LessonSession (schedule)
│   └── test_record.py   — TestRecord (theory & practical)
├── views/main.py        — All views
├── urls.py              — All routes (namespace: driving_school)
├── admin.py             — Admin registration
├── templates/driving_school/app.html  — Single HTML template
├── navigation_snippet.py — Copy-paste nav items
└── INSTALL.md           — This file
```

## Zero External Dependencies

This app depends ONLY on:
- Django
- django-tenants (for multi-tenant context)
- Your project's `settings.AUTH_USER_MODEL` (for created_by / received_by fields)
- Bootstrap Icons (already in your base.html)

No links to `inventory`, `sales`, `customers`, or any other PrimeBooks app.
