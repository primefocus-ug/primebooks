import logging

logger = logging.getLogger(__name__)


def assign_role_push_defaults(user, role):
    """
    Public utility — call this from accounts whenever a role is assigned.
    Safe to call even if push_notifications tables don't exist yet,
    or if django-tenants is not installed.
    """
    try:
        from django.db import connection

        # connection.schema_name is a django-tenants extension; fall back
        # gracefully if the attribute doesn't exist (non-tenant setup).
        schema_name = getattr(connection, 'schema_name', None)

        if schema_name is not None:
            # We're in a django-tenants project — verify the table exists in
            # this schema before touching it.
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = %s
                          AND table_name = 'push_notifications_userpushpreference'
                    )
                    """,
                    [schema_name],
                )
                exists = cursor.fetchone()[0]

            if not exists:
                return
        # (If schema_name is None we're in a non-tenant project; the table
        # will be in the default schema and we trust it exists.)

        from .signals import apply_role_push_defaults
        apply_role_push_defaults(user, role)

    except Exception as e:
        logger.warning(
            f"Could not apply push defaults for user {user} role {role}: {e}"
        )