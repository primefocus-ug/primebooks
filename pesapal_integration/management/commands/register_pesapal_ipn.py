"""
python manage.py register_pesapal_ipn --platform
python manage.py register_pesapal_ipn --tenant rem
python manage.py register_pesapal_ipn --all-tenants
python manage.py register_pesapal_ipn --platform --all-tenants

Rate-limit options (Pesapal enforces ~1 registration/5s in sandbox):
  --delay 6          seconds to wait between each tenant (default: 6)
  --retries 3        how many times to retry a 409 before giving up (default: 3)
  --retry-wait 10    seconds to wait before each retry (default: 10)
"""
import time
import json
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import connection
from django_tenants.utils import get_public_schema_name

from pesapal_integration.models import TenantPesapalConfig


class Command(BaseCommand):
    help = 'Register Pesapal IPN URLs for platform and/or tenants'

    def add_arguments(self, parser):
        parser.add_argument('--platform',     action='store_true')
        parser.add_argument('--tenant',       type=str, default=None)
        parser.add_argument('--all-tenants',  action='store_true')
        parser.add_argument('--base-url',     type=str, default=None)
        parser.add_argument('--delay',        type=float, default=6,
                            help='Seconds to sleep between each tenant registration (default: 6)')
        parser.add_argument('--retries',      type=int, default=3,
                            help='Max retries on 429/409 rate-limit response (default: 3)')
        parser.add_argument('--retry-wait',   type=float, default=10,
                            help='Seconds to wait before each retry (default: 10)')

    def handle(self, *args, **options):
        base_url = (
            options.get('base_url')
            or getattr(settings, 'PESAPAL_BASE_URL', None)
            or getattr(settings, 'SITE_URL', 'http://localhost:8000')
        ).rstrip('/')

        self._delay      = options['delay']
        self._retries    = options['retries']
        self._retry_wait = options['retry_wait']

        connection.set_schema(get_public_schema_name())

        if options['platform']:
            self._register_platform(base_url)

        if options['tenant']:
            self._register_tenant(options['tenant'], base_url)

        if options['all_tenants']:
            self._register_all_tenants(base_url)

        if not any([options['platform'], options['tenant'], options['all_tenants']]):
            self.stdout.write(self.style.WARNING(
                'Nothing to do. Use --platform, --tenant <slug>, or --all-tenants'
            ))

    # ── Raw API helpers ───────────────────────────────────────────────────────

    def _get_token(self, consumer_key, consumer_secret, env):
        url = settings.PESAPAL_URLS[env]['auth']
        try:
            resp = requests.post(
                url,
                json={'consumer_key': consumer_key, 'consumer_secret': consumer_secret},
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
                timeout=30,
            )
            self.stdout.write(f'  Auth → HTTP {resp.status_code}')
            data = resp.json()
            if resp.status_code == 200 and data.get('token'):
                return data['token']
            self.stdout.write(self.style.ERROR(f'  Auth failed: {data}'))
            return None
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'  Auth exception: {exc}'))
            return None

    def _list_ipns(self, token, env):
        url = settings.PESAPAL_URLS[env]['get_ipn_list']
        try:
            resp = requests.get(
                url,
                headers={
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {token}',
                },
                timeout=30,
            )
            self.stdout.write(f'  GetIpnList → HTTP {resp.status_code}')
            self.stdout.write(f'  GetIpnList raw: {resp.text[:500]}')
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and 'data' in data:
                    return data['data']
                return []
            return []
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'  GetIpnList exception: {exc}'))
            return []

    def _is_rate_limited(self, data: dict) -> bool:
        """Return True if Pesapal's response body signals a rate-limit error."""
        # Top-level message may be a JSON string (double-encoded)
        msg = data.get('message', '')
        if isinstance(msg, str):
            try:
                msg = json.loads(msg)
            except (ValueError, TypeError):
                pass
        if isinstance(msg, dict):
            code = msg.get('error', {}).get('code', '')
            return 'too_many' in code.lower() or 'decline' in code.lower()
        if isinstance(msg, str):
            return 'too many' in msg.lower()
        return False

    def _register_ipn_raw(self, token, env, ipn_url):
        """POST to Pesapal register-IPN endpoint with retry on rate-limit."""
        url = settings.PESAPAL_URLS[env]['register_ipn']
        for attempt in range(1, self._retries + 2):   # +1 for the initial try
            try:
                resp = requests.post(
                    url,
                    json={'url': ipn_url, 'ipn_notification_type': 'GET'},
                    headers={
                        'Accept': 'application/json',
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {token}',
                    },
                    timeout=30,
                )
                self.stdout.write(f'  RegisterIPN → HTTP {resp.status_code}')
                self.stdout.write(f'  RegisterIPN raw: {resp.text[:500]}')
                data = resp.json()

                # Success
                if resp.status_code == 200:
                    return data

                # Rate-limited (409 or 429)
                if resp.status_code in (409, 429) and self._is_rate_limited(data):
                    if attempt <= self._retries:
                        self.stdout.write(self.style.WARNING(
                            f'  Rate-limited. Waiting {self._retry_wait}s before retry '
                            f'{attempt}/{self._retries}…'
                        ))
                        time.sleep(self._retry_wait)
                        continue
                    else:
                        self.stdout.write(self.style.ERROR(
                            f'  Still rate-limited after {self._retries} retries. Giving up.'
                        ))
                        return data

                # Any other error — return immediately
                return data

            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'  RegisterIPN exception: {exc}'))
                return {}

        return {}

    def _do_register(self, slug_label, ipn_url, consumer_key, consumer_secret, env, company=None):
        self.stdout.write(f'\nRegistering IPN for {slug_label}')
        self.stdout.write(f'  URL: {ipn_url}')
        self.stdout.write(f'  Env: {env}')

        token = self._get_token(consumer_key, consumer_secret, env)
        if not token:
            self.stdout.write(self.style.ERROR('  FAILED: could not authenticate'))
            return None

        # Check if already registered
        existing = self._list_ipns(token, env)
        for ipn in existing:
            existing_url = ipn.get('url', '').rstrip('/')
            target_url   = ipn_url.rstrip('/')
            if existing_url == target_url:
                ipn_id = ipn.get('ipn_id')
                self.stdout.write(self.style.SUCCESS(f'  Already registered: {ipn_id}'))
                self._save_ipn_id(ipn_id, company, env)
                return ipn_id

        data   = self._register_ipn_raw(token, env, ipn_url)
        ipn_id = data.get('ipn_id')
        status = data.get('status')
        message = data.get('message', '')

        if ipn_id:
            self.stdout.write(self.style.SUCCESS(f'  Registered: {ipn_id}'))
            self._save_ipn_id(ipn_id, company, env)
            return ipn_id
        else:
            self.stdout.write(self.style.ERROR(
                f'  FAILED — status={status} message={message} full={data}'
            ))
            return None

    def _save_ipn_id(self, ipn_id, company, env):
        if not company or not ipn_id:
            return
        try:
            cfg, _ = TenantPesapalConfig.objects.get_or_create(
                tenant=company,
                defaults={'use_own_keys': False, 'environment': env}
            )
            cfg.ipn_id = ipn_id
            cfg.save(update_fields=['ipn_id'])
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f'  Could not save ipn_id to DB: {exc}'))

    # ── Platform ──────────────────────────────────────────────────────────────

    def _register_platform(self, base_url):
        ipn_url = f'{base_url}/pesapal/ipn/platform/'
        env     = getattr(settings, 'PESAPAL_ENV', 'sandbox')
        self._do_register(
            slug_label      = 'PLATFORM',
            ipn_url         = ipn_url,
            consumer_key    = settings.PESAPAL_CONSUMER_KEY,
            consumer_secret = settings.PESAPAL_CONSUMER_SECRET,
            env             = env,
            company         = None,
        )

    # ── Single tenant ─────────────────────────────────────────────────────────

    def _register_tenant(self, tenant_slug, base_url):
        from company.models import Company
        try:
            company = Company.objects.get(schema_name=tenant_slug)
        except Company.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Tenant not found: {tenant_slug}'))
            return
        self._do_register_company(company, base_url)

    def _do_register_company(self, company, base_url):
        tenant_slug = company.schema_name
        ipn_url     = f'{base_url}/pesapal/ipn/tenant/{tenant_slug}/'

        try:
            cfg = company.pesapal_config
            if cfg.use_own_keys and cfg.consumer_key and cfg.consumer_secret and cfg.is_active:
                key    = cfg.consumer_key
                secret = cfg.consumer_secret
                env    = cfg.environment
            else:
                raise AttributeError
        except Exception:
            key    = settings.PESAPAL_CONSUMER_KEY
            secret = settings.PESAPAL_CONSUMER_SECRET
            env    = getattr(settings, 'PESAPAL_ENV', 'sandbox')

        self._do_register(
            slug_label      = tenant_slug,
            ipn_url         = ipn_url,
            consumer_key    = key,
            consumer_secret = secret,
            env             = env,
            company         = company,
        )

    # ── All tenants ───────────────────────────────────────────────────────────

    def _register_all_tenants(self, base_url):
        from company.models import Company
        tenants = Company.objects.exclude(schema_name=get_public_schema_name())
        self.stdout.write(f'Found {tenants.count()} tenant(s)')
        for i, company in enumerate(tenants):
            self._do_register_company(company, base_url)
            # Pause between tenants to avoid hitting Pesapal's rate limit.
            # Skip the sleep after the very last tenant.
            if i < tenants.count() - 1 and self._delay > 0:
                self.stdout.write(f'  Sleeping {self._delay}s before next tenant…')
                time.sleep(self._delay)