# Run in Django shell after sync
from primebooks.sync import SyncManager

sync = SyncManager('PF-N212467', 'rem', 'your_token')

# Check if sequences are correct
from django.db import connection
from django_tenants.utils import schema_context

with schema_context('rem'):
    with connection.cursor() as cursor:
        # Check notification sequence
        cursor.execute("SELECT MAX(id) FROM notifications_notification;")
        max_id = cursor.fetchone()[0]

        cursor.execute("SELECT nextval('notifications_notification_id_seq');")
        next_id = cursor.fetchone()[0]

        print(f"Max ID: {max_id}")
        print(f"Next ID: {next_id}")
        print(f"✅ OK" if next_id > max_id else "❌ PROBLEM!")