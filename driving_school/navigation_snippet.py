"""
driving_school/navigation_snippet.py
=====================================
Add these NavigationItems to your main navigation.py NAVIGATION_ITEMS list.
Place them in the pluggable apps section (after the divider, before Profile/Settings).

Make sure to add requires_module='driving_school' so they only appear
when the module is activated for the tenant via the App Store.
"""

# ── Add this block to NAVIGATION_ITEMS in navigation.py ──────────────────

from navigation import NavigationItem  # adjust import if needed

DRIVING_SCHOOL_NAV = [
    NavigationItem(
        name="Driving School",
        icon="bi bi-car-front",
        requires_module="driving_school",
        children=[
            NavigationItem(
                name="Dashboard",
                url_name="driving_school:dashboard",
                icon="bi bi-speedometer2",
                requires_module="driving_school",
            ),
            NavigationItem(
                name="Students",
                url_name="driving_school:students",
                icon="bi bi-people",
                permission="driving_school.view_student",
                requires_module="driving_school",
            ),
            NavigationItem(
                name="Enrollments",
                url_name="driving_school:enrollments",
                icon="bi bi-journal-check",
                permission="driving_school.view_enrollment",
                requires_module="driving_school",
            ),
            NavigationItem(
                name="Schedule",
                url_name="driving_school:schedule",
                icon="bi bi-calendar3",
                permission="driving_school.view_lessonsession",
                requires_module="driving_school",
            ),
            NavigationItem(
                name="Instructors",
                url_name="driving_school:instructors",
                icon="bi bi-person-badge",
                permission="driving_school.view_instructor",
                requires_module="driving_school",
            ),
            NavigationItem(
                name="Fleet",
                url_name="driving_school:fleet",
                icon="bi bi-truck",
                permission="driving_school.view_vehicle",
                requires_module="driving_school",
            ),
            NavigationItem(
                name="Courses",
                url_name="driving_school:courses",
                icon="bi bi-book",
                permission="driving_school.view_drivingcourse",
                requires_module="driving_school",
            ),
            NavigationItem(
                name="Tests",
                url_name="driving_school:tests",
                icon="bi bi-patch-check",
                permission="driving_school.view_testrecord",
                requires_module="driving_school",
            ),
            NavigationItem(
                name="Reports",
                url_name="driving_school:reports",
                icon="bi bi-bar-chart-line",
                permission="driving_school.view_enrollment",
                requires_module="driving_school",
            ),
        ]
    ),
]
