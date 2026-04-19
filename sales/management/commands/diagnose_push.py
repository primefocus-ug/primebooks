"""
management/commands/diagnose_push.py

Full end-to-end diagnostic for FCM push notifications.

Usage:
    python manage.py diagnose_push --schema=your_tenant_schema
    python manage.py diagnose_push --schema=your_tenant_schema --user=1
    python manage.py diagnose_push --schema=your_tenant_schema --send-test

Place this file at:
    <any_app>/management/commands/diagnose_push.py
"""

from django.core.management.base import BaseCommand
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Diagnose FCM push notification setup end-to-end'

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            required=True,
            help='Tenant schema name to check (e.g. your_company_schema)',
        )
        parser.add_argument(
            '--user',
            type=int,
            default=None,
            help='User ID to check subscriptions and send a test push to',
        )
        parser.add_argument(
            '--send-test',
            action='store_true',
            help='Actually send a test FCM push to the user (requires --user)',
        )

    def handle(self, *args, **options):
        schema   = options['schema']
        user_id  = options.get('user')
        do_send  = options.get('send_test')

        self.stdout.write('\n' + '═' * 60)
        self.stdout.write('  FCM PUSH NOTIFICATION DIAGNOSTICS')
        self.stdout.write('═' * 60 + '\n')

        # ── STEP 1: Django settings ───────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING('\n[1] Checking Django settings...'))

        cred_path = getattr(settings, 'FIREBASE_CREDENTIALS_PATH', None)
        vapid_key = getattr(settings, 'FIREBASE_VAPID_PUBLIC_KEY', None)

        if cred_path:
            self.stdout.write(self.style.SUCCESS(
                f'    ✓ FIREBASE_CREDENTIALS_PATH = {cred_path}'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                '    ✗ FIREBASE_CREDENTIALS_PATH is not set in settings!'
            ))

        if vapid_key:
            self.stdout.write(self.style.SUCCESS(
                f'    ✓ FIREBASE_VAPID_PUBLIC_KEY = {vapid_key[:30]}...'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                '    ✗ FIREBASE_VAPID_PUBLIC_KEY is not set in settings!'
            ))

        # ── STEP 2: Credentials file exists and is valid ──────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING('\n[2] Checking Firebase credentials file...'))

        if cred_path:
            import os, json
            path = str(cred_path)
            if os.path.exists(path):
                self.stdout.write(self.style.SUCCESS(f'    ✓ File exists: {path}'))
                try:
                    with open(path) as f:
                        cred_data = json.load(f)
                    project_id = cred_data.get('project_id', '???')
                    client_email = cred_data.get('client_email', '???')
                    self.stdout.write(self.style.SUCCESS(
                        f'    ✓ project_id    = {project_id}'
                    ))
                    self.stdout.write(self.style.SUCCESS(
                        f'    ✓ client_email  = {client_email}'
                    ))
                    if 'private_key' not in cred_data:
                        self.stdout.write(self.style.ERROR(
                            '    ✗ private_key is MISSING from credentials file!'
                        ))
                    else:
                        self.stdout.write(self.style.SUCCESS('    ✓ private_key present'))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(
                        f'    ✗ Could not parse credentials JSON: {e}'
                    ))
            else:
                self.stdout.write(self.style.ERROR(
                    f'    ✗ File NOT found at: {path}'
                ))
        else:
            self.stdout.write(self.style.WARNING('    ⚠ Skipped — FIREBASE_CREDENTIALS_PATH not set'))

        # ── STEP 3: firebase-admin SDK can initialise ─────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING('\n[3] Initialising Firebase Admin SDK...'))

        messaging = None
        try:
            import firebase_admin
            from firebase_admin import credentials as fb_creds, messaging as fb_msg

            # Re-use existing app if already initialised
            try:
                app = firebase_admin.get_app()
                self.stdout.write(self.style.SUCCESS('    ✓ Firebase app already initialised'))
            except ValueError:
                cred = fb_creds.Certificate(str(cred_path))
                app  = firebase_admin.initialize_app(cred)
                self.stdout.write(self.style.SUCCESS('    ✓ Firebase app initialised successfully'))

            messaging = fb_msg
            self.stdout.write(self.style.SUCCESS('    ✓ firebase_admin.messaging imported OK'))

        except ImportError:
            self.stdout.write(self.style.ERROR(
                '    ✗ firebase-admin is NOT installed!\n'
                '      Run: pip install firebase-admin'
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'    ✗ Firebase init failed: {e}'))

        # ── STEP 4: Check subscriptions in DB ────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\n[4] Checking PushSubscription records in schema "{schema}"...'
        ))

        from django_tenants.utils import schema_context

        total_subs = 0
        active_subs = 0
        fcm_subs = 0
        user_subs = []

        try:
            with schema_context(schema):
                from push_notifications.models import PushSubscription
                total_subs  = PushSubscription.objects.count()
                active_subs = PushSubscription.objects.filter(is_active=True).count()
                fcm_subs    = PushSubscription.objects.filter(
                    is_active=True
                ).exclude(fcm_token='').count()

                self.stdout.write(f'    Total subscriptions : {total_subs}')
                self.stdout.write(f'    Active              : {active_subs}')
                self.stdout.write(f'    Active WITH FCM token: {fcm_subs}')

                if fcm_subs == 0:
                    self.stdout.write(self.style.ERROR(
                        '\n    ✗ NO active FCM tokens found!\n'
                        '      This is almost certainly why notifications are not arriving.\n'
                        '      → Open the website in your browser, grant notification\n'
                        '        permission, then check this count again.'
                    ))
                else:
                    self.stdout.write(self.style.SUCCESS(
                        f'\n    ✓ {fcm_subs} active FCM token(s) found'
                    ))

                if user_id:
                    user_subs = list(
                        PushSubscription.objects.filter(
                            user_id=user_id,
                            is_active=True,
                        ).exclude(fcm_token='').values('id', 'fcm_token', 'user_agent', 'last_used_at')
                    )
                    self.stdout.write(f'\n    Subscriptions for user {user_id}: {len(user_subs)}')
                    for sub in user_subs:
                        self.stdout.write(
                            f'      • id={sub["id"]} '
                            f'token={sub["fcm_token"][:40]}... '
                            f'last_used={sub["last_used_at"]}'
                        )
                    if not user_subs:
                        self.stdout.write(self.style.ERROR(
                            f'    ✗ User {user_id} has NO active FCM subscriptions.\n'
                            '      They need to open the site and grant permission.'
                        ))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'    ✗ DB check failed: {e}'))

        # ── STEP 5: Check UserPushPreference ─────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\n[5] Checking UserPushPreference for "sale_created" in schema "{schema}"...'
        ))

        try:
            with schema_context(schema):
                from push_notifications.models import UserPushPreference, PushNotificationType

                try:
                    ntype = PushNotificationType.objects.get(code='sale_created')
                    self.stdout.write(self.style.SUCCESS(
                        f'    ✓ PushNotificationType "sale_created" exists (active={ntype.is_active})'
                    ))
                    if not ntype.is_active:
                        self.stdout.write(self.style.ERROR(
                            '    ✗ "sale_created" type is INACTIVE — notifications will be skipped!'
                        ))
                except PushNotificationType.DoesNotExist:
                    self.stdout.write(self.style.WARNING(
                        '    ⚠ PushNotificationType "sale_created" does not exist yet.\n'
                        '      It will be auto-created when the first sale fires notify_event().\n'
                        '      If you have never completed a sale in this schema, that is expected.'
                    ))
                    ntype = None

                if ntype and user_id:
                    pref = UserPushPreference.objects.filter(
                        user_id=user_id,
                        notification_type=ntype,
                    ).first()
                    if pref:
                        status = '✓ enabled' if pref.enabled else '✗ DISABLED'
                        style  = self.style.SUCCESS if pref.enabled else self.style.ERROR
                        self.stdout.write(style(
                            f'    User {user_id} preference for "sale_created": {status}'
                        ))
                    else:
                        self.stdout.write(self.style.WARNING(
                            f'    ⚠ No UserPushPreference row for user {user_id} / "sale_created".\n'
                            '      notify_event() will auto-create it on the next sale.'
                        ))

                enabled_count = (
                    UserPushPreference.objects
                    .filter(notification_type=ntype, enabled=True)
                    .count()
                ) if ntype else 0
                self.stdout.write(f'    Users with "sale_created" enabled: {enabled_count}')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'    ✗ Preference check failed: {e}'))

        # ── STEP 6: Celery worker reachable ──────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING('\n[6] Checking Celery worker...'))
        try:
            from celery import current_app
            inspect = current_app.control.inspect(timeout=3)
            active  = inspect.active()
            if active:
                worker_names = list(active.keys())
                self.stdout.write(self.style.SUCCESS(
                    f'    ✓ Celery workers online: {worker_names}'
                ))
            else:
                self.stdout.write(self.style.ERROR(
                    '    ✗ No Celery workers responded!\n'
                    '      Notifications go through Celery — if no worker is running,\n'
                    '      pushes are queued but never sent.\n'
                    '      → Run: celery -A your_project worker -l info'
                ))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'    ⚠ Could not inspect Celery: {e}'))

        # ── STEP 7: Actually send a test push ─────────────────────────────────
        if do_send and user_id and messaging:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f'\n[7] Sending live FCM test push to user {user_id}...'
            ))
            try:
                with schema_context(schema):
                    from push_notifications.tasks import send_push_to_user
                    result = send_push_to_user(
                        user_id=user_id,
                        title='🔔 PrimeBooks FCM Test',
                        body='If you see this, FCM push is working end-to-end!',
                        url='/',
                        notification_type_code=None,
                        schema_name=schema,
                    )
                    self.stdout.write(self.style.SUCCESS(f'    ✓ Result: {result}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'    ✗ Test push failed: {e}'))
        elif do_send and not user_id:
            self.stdout.write(self.style.WARNING(
                '\n[7] Skipped — pass --user=<id> to send a test push'
            ))
        elif do_send and not messaging:
            self.stdout.write(self.style.ERROR(
                '\n[7] Skipped — Firebase SDK failed to initialise (see step 3)'
            ))

        # ── SUMMARY ───────────────────────────────────────────────────────────
        self.stdout.write('\n' + '═' * 60)
        self.stdout.write('  SUMMARY — most common causes of no notifications:')
        self.stdout.write('═' * 60)
        self.stdout.write("""
  1. fcm_token column is empty / nobody re-subscribed after FCM migration
     → Open the site in Chrome, grant permission, check step 4 again

  2. sws.js still has YOUR_... placeholders — Firebase config not replaced
     → Edit sws.js and firebase-init.js with real project values

  3. sws.js is served from /static/js/ but registered as /sws.js
     → Either serve it from root OR change the register() path in base.html

  4. Celery worker is not running — tasks queue up but never execute
     → celery -A <project> worker -l info

  5. UserPushPreference row missing or disabled for the user
     → Run notify_event() once manually, or complete a test sale

  6. FIREBASE_CREDENTIALS_PATH points to a file that doesn't exist
     → Check settings.py and make sure the JSON file is deployed
""")
        self.stdout.write('═' * 60 + '\n')