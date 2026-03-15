"""
onboarding/views.py  +  onboarding/context_processors.py
─────────────────────────────────────────────────────────
Keep in views.py; import context processor from here.

Context processor adds to every authenticated template:
  ob_is_new_user   bool   — show welcome modal
  ob_percent       int    — 0-100 completion
  ob_steps         list   — steps with 'done' key merged in
  ob_progress      obj    — OnboardingProgress instance
"""

import json
from django.http                    import JsonResponse
from django.views.decorators.http   import require_POST
from django.contrib.auth.decorators import login_required
from django.utils                   import timezone

from .models import OnboardingProgress, ALL_STEP_KEYS


# ═════════════════════════════════════════════════════════════
# Context Processor
# Add to TEMPLATES[0]['OPTIONS']['context_processors']:
#   'onboarding.views.onboarding_context'
# ═════════════════════════════════════════════════════════════

def onboarding_context(request):
    """Inject onboarding data into every template for authenticated users."""
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {
            'ob_is_new_user': False,
            'ob_percent':     0,
            'ob_steps':       [],
            'ob_progress':    None,
        }

    try:
        # Auto-detect on each request (lightweight — uses update_fields)
        progress = OnboardingProgress.auto_detect_completed_steps(request.user)
    except Exception:
        progress = OnboardingProgress.get_or_create_for_user(request.user)

    return {
        'ob_is_new_user': progress.is_new_user,
        'ob_percent':     progress.percent,
        'ob_steps':       progress.get_steps_with_status(),
        'ob_progress':    progress,
    }


# ═════════════════════════════════════════════════════════════
# API: Complete a step
# POST /onboarding/complete-step/
# Body: { "step": "first_product" }
# Returns: { "ok": true, "percent": 60, "is_complete": false }
# ═════════════════════════════════════════════════════════════

@login_required
@require_POST
def complete_step(request):
    try:
        data     = json.loads(request.body)
        step_key = str(data.get('step', '')).strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'ok': False, 'error': 'Invalid payload.'}, status=400)

    if step_key not in ALL_STEP_KEYS:
        return JsonResponse({'ok': False, 'error': f'Unknown step: {step_key}'}, status=400)

    progress = OnboardingProgress.get_or_create_for_user(request.user)
    changed  = progress.complete_step_and_save(step_key)

    return JsonResponse({
        'ok':          True,
        'changed':     changed,
        'percent':     progress.percent,
        'is_complete': progress.is_complete,
        'step':        step_key,
    })


# ═════════════════════════════════════════════════════════════
# API: Mark welcome modal as seen
# POST /onboarding/welcome-seen/
# ═════════════════════════════════════════════════════════════

@login_required
@require_POST
def mark_welcome_seen(request):
    progress = OnboardingProgress.get_or_create_for_user(request.user)
    if not progress.welcome_seen:
        progress.welcome_seen = True
        progress.save(update_fields=['welcome_seen'])
    return JsonResponse({'ok': True})


# ═════════════════════════════════════════════════════════════
# API: Dismiss onboarding permanently
# POST /onboarding/dismiss/
# ═════════════════════════════════════════════════════════════

@login_required
@require_POST
def dismiss_onboarding(request):
    progress = OnboardingProgress.get_or_create_for_user(request.user)
    if not progress.dismissed:
        progress.dismissed = True
        progress.save(update_fields=['dismissed'])
    return JsonResponse({'ok': True})


# ═════════════════════════════════════════════════════════════
# API: Get current progress (for dashboard widget AJAX refresh)
# GET /onboarding/progress/
# ═════════════════════════════════════════════════════════════

@login_required
def get_progress(request):
    progress = OnboardingProgress.get_or_create_for_user(request.user)
    return JsonResponse({
        'percent':     progress.percent,
        'is_complete': progress.is_complete,
        'dismissed':   progress.dismissed,
        'steps': [
            {
                'key':   step['key'],
                'label': step['label'],
                'done':  step['done'],
                'url':   step['url'],
                'icon':  step['icon'],
            }
            for step in progress.get_steps_with_status()
        ],
    })