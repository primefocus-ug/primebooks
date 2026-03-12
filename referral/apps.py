from django.apps import AppConfig


class ReferralConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'referral'

    def ready(self):
        try:
            import referral.public_admin  # noqa
        except ImportError:
            pass
