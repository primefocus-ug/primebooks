"""
accounts/sharing_detection.py

Login-sharing detection engine.

Three independent detectors run on every login:
  1. DeviceFingerprintDetector  — flags rapid fingerprint changes on same account
  2. ImpossibleTravelDetector   — flags logins from locations too far apart too fast
  3. ConcurrentRequestDetector  — flags overlapping requests from different IPs

Each detector returns a SuspicionResult(score, reason, evidence).
Scores are summed; if the total crosses LOCK_THRESHOLD the account is
auto-locked, the company admin is emailed, and an AuditLog entry is created.

Django-tenants compatible: every DB write is guarded with try/except and
table_exists checks so a cold migration never breaks requests.
"""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Thresholds  (tune these for your user base)
# ---------------------------------------------------------------------------

# Total suspicion score that triggers auto-lock + alert
LOCK_THRESHOLD = 70

# Impossible travel: minimum speed (km/h) that flags as suspicious
IMPOSSIBLE_TRAVEL_SPEED_KMH = 800   # roughly commercial flight speed

# Fingerprint: how many distinct fingerprints within this window raises a flag
FINGERPRINT_WINDOW_HOURS = 2
FINGERPRINT_MAX_DISTINCT = 2        # 3rd distinct fingerprint in window → flag

# Concurrent: two requests from different IPs within this many seconds
CONCURRENT_WINDOW_SECONDS = 30


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SuspicionResult:
    score: int                          # 0–100
    reason: str                         # short human-readable label
    evidence: dict[str, Any] = field(default_factory=dict)
    is_suspicious: bool = False

    def __post_init__(self):
        self.is_suspicious = self.score >= 40


@dataclass
class DetectionContext:
    """Everything the detectors need, collected once per login."""
    user_id: int
    user_email: str
    ip_address: str
    user_agent: str
    fingerprint_hash: str               # built by the view from JS data
    latitude: float | None
    longitude: float | None
    timestamp: Any                      # timezone-aware datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cache_key(namespace: str, user_id: int) -> str:
    return f"sharing:{namespace}:{user_id}"


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance between two lat/lon points in kilometres."""
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(d_lon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Detector 1 — Device fingerprinting
# ---------------------------------------------------------------------------

class DeviceFingerprintDetector:
    """
    Tracks distinct device fingerprints seen for a user within a rolling
    time window.  More than FINGERPRINT_MAX_DISTINCT unique fingerprints
    in FINGERPRINT_WINDOW_HOURS hours is suspicious.

    Fingerprint hash is computed by the frontend (FingerprintJS or similar)
    and POSTed alongside credentials.  Falls back to a server-side hash of
    user-agent + accept-language headers if JS data is unavailable.
    """

    def detect(self, ctx: DetectionContext) -> SuspicionResult:
        key = _cache_key("fingerprints", ctx.user_id)
        window = FINGERPRINT_WINDOW_HOURS * 3600

        # Retrieve list of (fingerprint_hash, timestamp_iso) seen recently
        seen: list[dict] = cache.get(key, [])

        # Prune entries outside the window
        cutoff = ctx.timestamp - timedelta(hours=FINGERPRINT_WINDOW_HOURS)
        seen = [
            e for e in seen
            if e.get("ts") and timezone.datetime.fromisoformat(e["ts"]) > cutoff
        ]

        # Add current fingerprint
        seen.append({
            "fp": ctx.fingerprint_hash,
            "ts": ctx.timestamp.isoformat(),
            "ip": ctx.ip_address,
        })
        cache.set(key, seen, timeout=window)

        distinct = len({e["fp"] for e in seen})

        if distinct > FINGERPRINT_MAX_DISTINCT:
            score = min(100, 30 + (distinct - FINGERPRINT_MAX_DISTINCT) * 20)
            return SuspicionResult(
                score=score,
                reason="multiple_device_fingerprints",
                evidence={
                    "distinct_fingerprints": distinct,
                    "window_hours": FINGERPRINT_WINDOW_HOURS,
                    "fingerprints_seen": seen,
                },
            )

        return SuspicionResult(score=0, reason="fingerprint_ok")


# ---------------------------------------------------------------------------
# Detector 2 — Impossible travel
# ---------------------------------------------------------------------------

class ImpossibleTravelDetector:
    """
    Compares the current login's geolocation with the previous login's
    geolocation.  If the implied travel speed exceeds IMPOSSIBLE_TRAVEL_SPEED_KMH
    the login is flagged.

    Requires IP geolocation (uses the same get_location_from_ip utility
    already in your codebase).
    """

    def detect(self, ctx: DetectionContext) -> SuspicionResult:
        key = _cache_key("last_location", ctx.user_id)
        previous = cache.get(key)

        # Store current location for next comparison
        if ctx.latitude is not None and ctx.longitude is not None:
            cache.set(key, {
                "lat": ctx.latitude,
                "lon": ctx.longitude,
                "ts": ctx.timestamp.isoformat(),
                "ip": ctx.ip_address,
            }, timeout=60 * 60 * 72)  # 72 hours

        if not previous:
            return SuspicionResult(score=0, reason="travel_no_previous_location")

        prev_lat = previous.get("lat")
        prev_lon = previous.get("lon")
        prev_ts_str = previous.get("ts")

        if None in (prev_lat, prev_lon, prev_ts_str):
            return SuspicionResult(score=0, reason="travel_incomplete_previous")

        if ctx.latitude is None or ctx.longitude is None:
            return SuspicionResult(score=0, reason="travel_no_current_location")

        prev_ts = timezone.datetime.fromisoformat(prev_ts_str)
        elapsed_hours = max(
            (ctx.timestamp - prev_ts).total_seconds() / 3600,
            0.001,   # avoid division by zero
        )
        distance_km = _haversine_km(
            prev_lat, prev_lon, ctx.latitude, ctx.longitude
        )
        speed_kmh = distance_km / elapsed_hours

        if speed_kmh > IMPOSSIBLE_TRAVEL_SPEED_KMH and distance_km > 50:
            score = min(100, int(40 + (speed_kmh - IMPOSSIBLE_TRAVEL_SPEED_KMH) / 100))
            return SuspicionResult(
                score=score,
                reason="impossible_travel",
                evidence={
                    "distance_km": round(distance_km, 1),
                    "elapsed_hours": round(elapsed_hours, 2),
                    "implied_speed_kmh": round(speed_kmh, 1),
                    "previous_ip": previous.get("ip"),
                    "current_ip": ctx.ip_address,
                    "previous_location": {"lat": prev_lat, "lon": prev_lon},
                    "current_location": {"lat": ctx.latitude, "lon": ctx.longitude},
                },
            )

        return SuspicionResult(score=0, reason="travel_ok")


# ---------------------------------------------------------------------------
# Detector 3 — Concurrent requests from different IPs
# ---------------------------------------------------------------------------

class ConcurrentRequestDetector:
    """
    Watches for two requests from the *same authenticated account* hitting
    the server from *different IPs* within CONCURRENT_WINDOW_SECONDS.

    This is called on every authenticated request (not just login) from the
    middleware, making it the most real-time of the three detectors.
    """

    def detect(self, ctx: DetectionContext) -> SuspicionResult:
        key = _cache_key("recent_ips", ctx.user_id)
        window = CONCURRENT_WINDOW_SECONDS

        recent: list[dict] = cache.get(key, [])

        # Prune stale entries
        cutoff = ctx.timestamp - timedelta(seconds=window)
        recent = [
            e for e in recent
            if timezone.datetime.fromisoformat(e["ts"]) > cutoff
        ]

        # Check if a *different* IP already active in the window
        other_ips = {e["ip"] for e in recent if e["ip"] != ctx.ip_address}

        # Add current
        recent.append({"ip": ctx.ip_address, "ts": ctx.timestamp.isoformat()})
        cache.set(key, recent, timeout=window * 2)

        if other_ips:
            score = min(100, 50 + len(other_ips) * 15)
            return SuspicionResult(
                score=score,
                reason="concurrent_ips",
                evidence={
                    "current_ip": ctx.ip_address,
                    "other_active_ips": list(other_ips),
                    "window_seconds": window,
                },
            )

        return SuspicionResult(score=0, reason="concurrent_ok")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class SharingDetectionEngine:
    """
    Runs all detectors and handles the outcome.

    Usage (in your login completion helpers and middleware):

        from accounts.sharing_detection import SharingDetectionEngine, DetectionContext

        ctx = DetectionContext(
            user_id=user.pk,
            user_email=user.email,
            ip_address=ip,
            user_agent=ua,
            fingerprint_hash=fp_hash,
            latitude=lat,
            longitude=lon,
            timestamp=timezone.now(),
        )
        engine = SharingDetectionEngine()
        engine.run(user, ctx, request)
    """

    DETECTORS = [
        DeviceFingerprintDetector(),
        ImpossibleTravelDetector(),
        ConcurrentRequestDetector(),
    ]

    def run(self, user, ctx: DetectionContext, request=None) -> int:
        """
        Execute all detectors, aggregate score, take action if threshold met.
        Returns the total suspicion score (0–300 theoretically, capped at 100).
        """
        results: list[SuspicionResult] = []
        for detector in self.DETECTORS:
            try:
                result = detector.detect(ctx)
                results.append(result)
                if result.is_suspicious:
                    logger.warning(
                        f"[SharingDetection] {detector.__class__.__name__} "
                        f"flagged user {ctx.user_email}: {result.reason} "
                        f"(score={result.score})"
                    )
            except Exception as exc:
                logger.error(
                    f"[SharingDetection] {detector.__class__.__name__} error: {exc}"
                )

        total_score = min(100, sum(r.score for r in results))
        suspicious_results = [r for r in results if r.is_suspicious]

        if suspicious_results:
            self._record_suspicion(user, ctx, results, total_score)

        if total_score >= LOCK_THRESHOLD:
            self._take_action(user, ctx, results, total_score, request)

        return total_score

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _record_suspicion(self, user, ctx, results, total_score):
        """Write a suspicious_activity AuditLog entry."""
        try:
            from accounts.models import AuditLog
            from accounts.signals import table_exists

            if not table_exists('accounts_auditlog'):
                return

            evidence = {
                r.reason: r.evidence
                for r in results
                if r.is_suspicious
            }

            AuditLog.objects.create(
                user=user,
                action='suspicious_activity',
                action_description=(
                    f"Login-sharing suspicion detected for {ctx.user_email} "
                    f"(score={total_score}/100)"
                ),
                severity='critical' if total_score >= LOCK_THRESHOLD else 'warning',
                ip_address=ctx.ip_address,
                user_agent=ctx.user_agent,
                success=False,
                requires_review=True,
                company=getattr(user, 'company', None),
                metadata={
                    "total_score": total_score,
                    "detectors": evidence,
                    "lock_threshold": LOCK_THRESHOLD,
                },
            )
        except Exception as exc:
            logger.error(f"[SharingDetection] Failed to write AuditLog: {exc}")

    def _take_action(self, user, ctx, results, total_score, request):
        """Lock account + notify admin + email account owner."""
        logger.warning(
            f"[SharingDetection] THRESHOLD REACHED for {ctx.user_email} "
            f"(score={total_score}). Auto-locking."
        )

        # 1. Lock the account
        try:
            user.lock_account(duration_minutes=60)
            user.metadata = user.metadata or {}
            user.metadata['sharing_lock'] = {
                'locked_at': ctx.timestamp.isoformat(),
                'score': total_score,
                'reasons': [r.reason for r in results if r.is_suspicious],
            }
            user.save(update_fields=['metadata', 'locked_until'])
        except Exception as exc:
            logger.error(f"[SharingDetection] Failed to lock account: {exc}")

        # 2. Invalidate all active sessions immediately
        try:
            from accounts.middleware import clear_session_registry
            clear_session_registry(user.pk)
        except Exception as exc:
            logger.error(f"[SharingDetection] Failed to clear sessions: {exc}")

        # 3. Send email to account owner
        self._email_account_owner(user, ctx, results, total_score)

        # 4. Alert company admin
        self._alert_company_admins(user, ctx, results, total_score)

    def _email_account_owner(self, user, ctx, results, total_score):
        """Email the affected user that their account was locked."""
        try:
            from django.conf import settings
            from django.core.mail import send_mail
            from django.db import connection

            company_name = (
                user.company.name
                if getattr(user, 'company', None)
                else 'PrimeBooks'
            )

            reasons_text = '\n'.join(
                f'  • {r.reason.replace("_", " ").title()}'
                for r in results if r.is_suspicious
            )

            subject = f'⚠️ Security Alert: {company_name} account temporarily locked'

            plain = (
                f"Hello {user.get_short_name() or user.email},\n\n"
                f"We detected suspicious login activity on your account and have "
                f"temporarily locked it for 60 minutes to protect you.\n\n"
                f"Suspicious signals detected:\n{reasons_text}\n\n"
                f"IP address: {ctx.ip_address}\n"
                f"Time: {ctx.timestamp.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
                f"If this was you logging in from a new device, please contact "
                f"your company administrator to unlock your account.\n\n"
                f"If you did not attempt to log in, please change your password "
                f"immediately and contact support.\n\n"
                f"— The {company_name} Security Team"
            )

            send_mail(
                subject=subject,
                message=plain,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@primebooks.app'),
                recipient_list=[user.email],
                fail_silently=True,
            )
            logger.info(f"[SharingDetection] Sent lock email to {user.email}")
        except Exception as exc:
            logger.error(f"[SharingDetection] Failed to email account owner: {exc}")

    def _alert_company_admins(self, user, ctx, results, total_score):
        """Email all company admins about the suspicious account."""
        try:
            from django.conf import settings
            from django.core.mail import send_mail
            from accounts.models import CustomUser

            company = getattr(user, 'company', None)
            if not company:
                return

            admins = CustomUser.objects.filter(
                company=company,
                company_admin=True,
                is_active=True,
                is_hidden=False,
            ).exclude(pk=user.pk)

            if not admins.exists():
                return

            admin_emails = list(admins.values_list('email', flat=True))

            evidence_lines = []
            for r in results:
                if r.is_suspicious:
                    evidence_lines.append(
                        f"  • {r.reason.replace('_', ' ').title()} "
                        f"(score: {r.score}/100)"
                    )

            subject = (
                f'[Admin Alert] Possible login sharing detected — '
                f'{user.get_full_name() or user.email}'
            )

            plain = (
                f"A suspicious login was detected for one of your users.\n\n"
                f"User:      {user.get_full_name() or user.email} ({user.email})\n"
                f"Company:   {company.name}\n"
                f"IP:        {ctx.ip_address}\n"
                f"Time:      {ctx.timestamp.strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"Score:     {total_score}/100 (threshold: {LOCK_THRESHOLD})\n\n"
                f"Signals detected:\n" + '\n'.join(evidence_lines) + "\n\n"
                f"The account has been automatically locked for 60 minutes.\n"
                f"Please review the audit logs and unlock the account if appropriate.\n\n"
                f"Review at: your-admin-panel/users/{user.pk}/\n\n"
                f"— PrimeBooks Security System"
            )

            send_mail(
                subject=subject,
                message=plain,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@primebooks.app'),
                recipient_list=admin_emails,
                fail_silently=True,
            )
            logger.info(
                f"[SharingDetection] Sent admin alert to {len(admin_emails)} admin(s)"
            )
        except Exception as exc:
            logger.error(f"[SharingDetection] Failed to alert company admins: {exc}")