def assign_role_push_defaults(user, role):
    """
    Public utility — call this from accounts whenever a role is assigned.
    Safe to call even if push_notifications tables don't exist yet.
    """
    from django.db import connection

    try:
        from django.db import connection as conn
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = %s
                    AND table_name = 'push_notifications_userpushpreference'
                )
            """, [conn.schema_name])
            exists = cursor.fetchone()[0]

        if not exists:
            return

        from .signals import apply_role_push_defaults
        apply_role_push_defaults(user, role)

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            f"Could not apply push defaults for user {user} role {role}: {e}"
        )