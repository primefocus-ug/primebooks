"""
sync/login_view.py
==================
POST /api/desktop/auth/login/

Called by the desktop login screen. Returns access + refresh tokens
plus a user dict that the desktop persists to local SQLite.

This view runs in the TENANT schema (subdomain routing gives us that).
It uses simplejwt to generate tokens so the desktop can call all other
tenant-scoped endpoints with Bearer auth.

Response shape (matches what login_screen._normalise_response() expects):
  {
    "token":   "<access JWT>",     ← also available as "access" for simplejwt compat
    "refresh": "<refresh JWT>",
    "user": {
      "id":           1,
      "sync_id":      "<uuid>",    ← always present, auto-generated if NULL
      "email":        "...",
      "username":     "...",
      "first_name":   "...",
      "last_name":    "...",
      "company_id":   "PF-N212467",
      "company_name": "...",
      "schema_name":  "rem",
      "role_name":    "...",
      "is_active":    true,
      "permissions":  ["can_create_sales", ...]
    }
  }
"""

import uuid
import logging
from django.contrib.auth import authenticate
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

logger = logging.getLogger(__name__)

SYNC_ID_NAMESPACE = uuid.NAMESPACE_URL


@api_view(["POST"])
@permission_classes([AllowAny])
def desktop_login(request):
    """
    Authenticate desktop user, return JWT tokens + full user profile.
    """
    email    = request.data.get("email", "").strip().lower()
    password = request.data.get("password", "")

    if not email or not password:
        return Response({"detail": "Email and password are required."}, status=400)

    # django-tenants ensures we're in the right schema already
    # (the subdomain routing middleware sets connection.schema_name)
    user = authenticate(request, username=email, password=password)

    if user is None:
        # Try email-based lookup in case username != email
        try:
            from accounts.models import CustomUser
            user_obj = CustomUser.objects.get(email=email)
            user = authenticate(request, username=user_obj.username, password=password)
        except Exception:
            pass

    if user is None:
        logger.warning(f"Desktop login failed for: {email}")
        return Response({"detail": "Invalid email or password."}, status=401)

    if not user.is_active:
        return Response({"detail": "Account is inactive. Contact your administrator."}, status=403)

    # ── Ensure sync_id is set ─────────────────────────────────────────────
    if not user.sync_id:
        # Auto-generate deterministic UUID
        schema_name = _get_schema_name(request)
        seed = f"{schema_name}:uid:{user.pk}"
        new_sync_id = str(uuid.uuid5(SYNC_ID_NAMESPACE, seed))
        type(user).objects.filter(pk=user.pk).update(sync_id=new_sync_id)
        user.sync_id = new_sync_id
        logger.info(f"Auto-generated sync_id for user {email}: {new_sync_id}")

    # ── Generate JWT tokens ───────────────────────────────────────────────
    refresh = RefreshToken.for_user(user)
    access_token  = str(refresh.access_token)
    refresh_token = str(refresh)

    # ── Build user profile ────────────────────────────────────────────────
    schema_name  = _get_schema_name(request)
    company_id   = _get_company_id(request, user)
    company_name = _get_company_name(request)
    role_name    = _get_role_name(user)
    permissions  = _get_permissions(user)

    user_data = {
        "id":           user.pk,
        "sync_id":      str(user.sync_id),
        "email":        user.email,
        "username":     user.username,
        "first_name":   user.first_name or "",
        "last_name":    user.last_name  or "",
        "company_id":   company_id,
        "company_name": company_name,
        "schema_name":  schema_name,
        "role_name":    role_name,
        "is_active":    user.is_active,
        "is_staff":     user.is_staff,
        "permissions":  permissions,
        "phone_number": getattr(user, "phone_number", "") or "",
    }

    logger.info(f"Desktop login success: {email} (schema={schema_name})")

    return Response({
        "token":   access_token,   # auth.py style
        "access":  access_token,   # simplejwt style — both present for compat
        "refresh": refresh_token,
        "user":    user_data,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_schema_name(request) -> str:
    if hasattr(request, "tenant"):
        return request.tenant.schema_name
    return ""


def _get_company_id(request, user) -> str:
    """Return the company's external ID (not the auto-increment PK)."""
    if hasattr(request, "tenant"):
        tenant = request.tenant
        return str(getattr(tenant, "company_id", "") or tenant.schema_name)
    if hasattr(user, "company") and user.company:
        return str(getattr(user.company, "company_id", "") or "")
    return ""


def _get_company_name(request) -> str:
    if hasattr(request, "tenant"):
        return getattr(request.tenant, "name", "") or ""
    return ""


def _get_role_name(user) -> str:
    """
    Try to get primary role name. Handles various role patterns gracefully.
    """
    # Pattern 1: user.primary_role (FK to a Role model)
    if hasattr(user, "primary_role") and user.primary_role:
        return getattr(user.primary_role, "name", "") or ""

    # Pattern 2: user.role (direct FK)
    if hasattr(user, "role") and user.role:
        return getattr(user.role, "name", "") or ""

    # Pattern 3: user.roles (M2M) — use first/highest priority
    if hasattr(user, "roles"):
        try:
            role = user.roles.order_by("-priority").first()
            if role:
                return role.name or ""
        except Exception:
            pass

    # Pattern 4: user.role_name (text field)
    return getattr(user, "role_name", "") or ""


def _get_permissions(user) -> list:
    """
    Return a flat list of permission codenames for offline checking.
    Desktop uses these for show/hide UI decisions only — not security.
    """
    if not user.is_active:
        return []

    # Superusers get all permissions flagged
    if user.is_superuser:
        return ["__superuser__"]

    perms = []

    # Django's built-in permission system
    try:
        perms = [
            p.split(".")[-1]  # strip app label, keep codename
            for p in user.get_all_permissions()
        ]
    except Exception:
        pass

    # Custom role-based permissions (your accounts app)
    try:
        if hasattr(user, "primary_role") and user.primary_role:
            role_perms = user.primary_role.permissions.values_list("codename", flat=True)
            perms.extend(list(role_perms))
        elif hasattr(user, "role") and user.role:
            role_perms = user.role.permissions.values_list("codename", flat=True)
            perms.extend(list(role_perms))
    except Exception:
        pass

    return list(set(perms))  # deduplicate