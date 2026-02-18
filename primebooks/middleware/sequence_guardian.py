# primebooks/middleware/sequence_guardian.py

import logging
from django.db import connection
from django_tenants.utils import schema_context, get_tenant

logger = logging.getLogger(__name__)


class SequenceGuardianMiddleware:
    """
    Safety net: reset ALL sequences after any write request.
    Zero risk - just ensures sequences are always correct.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Only reset after write operations
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            try:
                tenant = get_tenant(request)
                if tenant and hasattr(tenant, 'schema_name'):
                    self._reset_sequences(tenant.schema_name)
            except Exception as e:
                # Never break the request - just log
                logger.debug(f"Sequence reset skipped: {e}")

        return response

    def _reset_sequences(self, schema_name):
        """Reset ALL sequences in the schema automatically."""
        try:
            with schema_context(schema_name):
                with connection.cursor() as cursor:
                    # Discover ALL sequences in this schema
                    cursor.execute("""
                                   SELECT s.sequencename, c.relname, a.attname
                                   FROM pg_sequences s
                                            JOIN pg_class seq_cls
                                                 ON seq_cls.relname = s.sequencename
                                                     AND seq_cls.relnamespace = (SELECT oid
                                                                                 FROM pg_namespace
                                                                                 WHERE nspname = %s)
                                            JOIN pg_depend dep
                                                 ON dep.objid = seq_cls.oid
                                                     AND dep.classid = 'pg_class'::regclass
                            AND dep.deptype = 'a'
                        JOIN pg_attribute a
                                   ON a.attrelid = dep.refobjid
                                       AND a.attnum = dep.refobjsubid
                                       JOIN pg_class c ON c.oid = dep.refobjid
                                   WHERE s.schemaname = %s
                                   ORDER BY s.sequencename;
                                   """, [schema_name, schema_name])

                    sequences = cursor.fetchall()

                    # Fallback if join returns nothing
                    if not sequences:
                        cursor.execute("""
                                       SELECT sequencename
                                       FROM pg_sequences
                                       WHERE schemaname = %s;
                                       """, [schema_name])

                        sequences = []
                        for (seq_name,) in cursor.fetchall():
                            # Parse table/column from sequence name
                            # Standard Django: tablename_columnname_seq
                            parts = seq_name.rsplit('_', 2)
                            if len(parts) == 3 and parts[2] == 'seq':
                                table_name = parts[0]
                                col_name = parts[1]
                                sequences.append((seq_name, table_name, col_name))

                    # Reset each sequence
                    for seq_name, table_name, col_name in sequences:
                        try:
                            # Verify table exists
                            cursor.execute(
                                "SELECT to_regclass(%s)",
                                [f"{schema_name}.{table_name}"]
                            )
                            if cursor.fetchone()[0] is None:
                                continue

                            # Get max value from table
                            cursor.execute(
                                f'SELECT COALESCE(MAX("{col_name}"), 0) '
                                f'FROM "{schema_name}"."{table_name}";'
                            )
                            max_val = cursor.fetchone()[0]

                            # Reset sequence to max + 1
                            cursor.execute(
                                f'SELECT setval(\'"{schema_name}"."{seq_name}"\', '
                                f'GREATEST(%s, 1), true);',
                                [max_val]
                            )
                        except Exception as e:
                            # Skip individual sequence errors (table might be empty, etc.)
                            logger.debug(f"Skipped sequence {seq_name}: {e}")

        except Exception as e:
            # Never crash the request - middleware must be bulletproof
            logger.debug(f"Sequence reset error: {e}")