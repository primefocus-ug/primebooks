import importlib

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'
    verbose_name = 'Accounts'

    def ready(self):
        _patch_authtoken_migration()
        import accounts.signals


def _patch_authtoken_migration():
    """
    Monkey-patch authtoken's initial migration to depend on accounts.

    WHY THIS IS NEEDED
    ──────────────────
    django-tenants runs ALL shared-schema migrations together.  The standard
    DRF authtoken migration declares:

        dependencies = [
            migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ]

    …which resolves to ('accounts', '__first__').  Django's migration planner
    sometimes schedules authtoken before the concrete accounts migration,
    causing:

        ProgrammingError: relation "accounts_customuser" does not exist

    The safest fix is to explicitly declare the correct dependency here,
    before Django's migration executor constructs its plan.

    WHAT WE DO
    ──────────
    1. Import authtoken's 0001_initial module via importlib (so we avoid
       the "can't have a name starting with a digit" import syntax issue).
    2. Append ('accounts', '0001_initial') to its dependencies list if it
       isn't already there.

    This is idempotent and harmless if authtoken is not installed.
    """
    try:
        authtoken_migration = importlib.import_module(
            'rest_framework.authtoken.migrations.0001_initial'
        )
    except (ImportError, ModuleNotFoundError):
        return  # authtoken not installed – nothing to do

    target = ('accounts', '0001_initial')

    deps = authtoken_migration.Migration.dependencies

    if target not in deps:
        deps.append(target)