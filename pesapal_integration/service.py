"""
pesapal_integration/service.py
───────────────────────────────
Tenant-aware Pesapal API service.

Usage:
    # Platform keys (SaaS billing — tenant pays YOU)
    svc = PesapalService()

    # Tenant keys (tenant collects from their customers)
    svc = PesapalService.for_tenant(company)

All methods return a dict with a top-level 'success' bool.
"""

import logging
from datetime import datetime, timedelta

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

STATUS_CODE_MAP = {
    0: 'INVALID',
    1: 'COMPLETED',
    2: 'FAILED',
    3: 'REVERSED',
}


def _pesapal_urls(environment: str = None) -> dict:
    env = environment or getattr(settings, 'PESAPAL_ENV', 'sandbox')
    return settings.PESAPAL_URLS[env]


def _headers(token: str = None) -> dict:
    h = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    if token:
        h['Authorization'] = f'Bearer {token}'
    return h


# ─────────────────────────────────────────────────────────────────────────────
# Service class
# ─────────────────────────────────────────────────────────────────────────────

class PesapalService:
    """
    One instance per request / task.  Holds resolved credentials and caches
    the Bearer token for its own lifetime (not cross-request).
    """

    def __init__(
        self,
        consumer_key: str = None,
        consumer_secret: str = None,
        environment: str = None,
    ):
        self.consumer_key    = consumer_key    or settings.PESAPAL_CONSUMER_KEY
        self.consumer_secret = consumer_secret or settings.PESAPAL_CONSUMER_SECRET
        self.environment     = environment     or getattr(settings, 'PESAPAL_ENV', 'sandbox')
        self._token: str     = None
        self._token_expiry   = None

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def for_tenant(cls, company) -> 'PesapalService':
        """
        Return a service instance using the tenant's own Pesapal keys if
        configured, otherwise fall back to the platform keys.
        """
        try:
            cfg = company.pesapal_config
            if cfg.use_own_keys and cfg.consumer_key and cfg.consumer_secret and cfg.is_active:
                logger.debug('Using tenant Pesapal keys for %s', company.schema_name)
                return cls(
                    consumer_key=cfg.consumer_key,
                    consumer_secret=cfg.consumer_secret,
                    environment=cfg.environment,
                )
        except Exception:
            pass

        logger.debug('Using platform Pesapal keys for %s', getattr(company, 'schema_name', '?'))
        return cls()

    # ── URL resolver ─────────────────────────────────────────────────────────

    def _url(self, endpoint: str) -> str:
        return _pesapal_urls(self.environment)[endpoint]

    # ── Token management ─────────────────────────────────────────────────────

    def get_token(self, force: bool = False) -> dict:
        now = timezone.now()
        if not force and self._token and self._token_expiry and now < self._token_expiry:
            return {'success': True, 'token': self._token}

        try:
            resp = requests.post(
                self._url('auth'),
                json={'consumer_key': self.consumer_key, 'consumer_secret': self.consumer_secret},
                headers=_headers(),
                timeout=30,
            )
            data = resp.json()
            if resp.status_code == 200 and data.get('token'):
                expiry_str = data.get('expiryDate', '')
                try:
                    expiry_dt = datetime.fromisoformat(expiry_str.replace('Z', '+00:00'))
                    self._token_expiry = expiry_dt - timedelta(seconds=30)
                except Exception:
                    self._token_expiry = now + timedelta(minutes=4, seconds=30)
                self._token = data['token']
                return {'success': True, 'token': self._token}

            return {'success': False, 'error': data.get('message', 'Auth failed'), 'raw': data}
        except requests.RequestException as exc:
            logger.exception('Pesapal auth error: %s', exc)
            return {'success': False, 'error': str(exc)}

    # ── Internal HTTP helpers ─────────────────────────────────────────────────

    def _post(self, endpoint: str, payload: dict) -> dict:
        tok = self.get_token()
        if not tok['success']:
            return tok
        try:
            resp = requests.post(
                self._url(endpoint),
                json=payload,
                headers=_headers(tok['token']),
                timeout=30,
            )
            return {'success': resp.status_code == 200, 'data': resp.json(), 'status_code': resp.status_code}
        except requests.RequestException as exc:
            logger.exception('Pesapal POST %s error: %s', endpoint, exc)
            return {'success': False, 'error': str(exc)}

    def _get(self, endpoint: str, params: dict = None) -> dict:
        tok = self.get_token()
        if not tok['success']:
            return tok
        try:
            resp = requests.get(
                self._url(endpoint),
                params=params,
                headers=_headers(tok['token']),
                timeout=30,
            )
            return {'success': resp.status_code == 200, 'data': resp.json(), 'status_code': resp.status_code}
        except requests.RequestException as exc:
            logger.exception('Pesapal GET %s error: %s', endpoint, exc)
            return {'success': False, 'error': str(exc)}

    # ── IPN ───────────────────────────────────────────────────────────────────

    def register_ipn(self, ipn_url: str, notification_type: str = 'GET') -> dict:
        result = self._post('register_ipn', {
            'url': ipn_url,
            'ipn_notification_type': notification_type,
        })
        if result['success'] and result['data'].get('ipn_id'):
            return {'success': True, 'ipn_id': result['data']['ipn_id'], 'data': result['data']}
        return {'success': False, 'error': result.get('data', {}).get('message', 'IPN registration failed')}

    def get_ipn_list(self) -> dict:
        result = self._get('get_ipn_list')
        if result['success']:
            return {'success': True, 'ipns': result['data']}
        return result

    def get_or_register_ipn(self, ipn_url: str) -> dict:
        """Return existing IPN id for url or register a new one."""
        list_result = self.get_ipn_list()
        if list_result['success']:
            for ipn in list_result['ipns']:
                if ipn.get('url') == ipn_url:
                    return {'success': True, 'ipn_id': ipn['ipn_id'], 'already_existed': True}
        return self.register_ipn(ipn_url)

    # ── Order submission ──────────────────────────────────────────────────────

    def submit_order(
        self,
        merchant_reference: str,
        amount: float,
        currency: str,
        description: str,
        notification_id: str,
        billing_address: dict,
        callback_url: str,
        cancellation_url: str = '',
        redirect_mode: str = 'TOP_WINDOW',
        branch: str = '',
        account_number: str = None,
        subscription_details: dict = None,
    ) -> dict:
        payload = {
            'id':               merchant_reference,
            'currency':         currency,
            'amount':           float(amount),
            'description':      description[:100],
            'callback_url':     callback_url,
            'cancellation_url': cancellation_url,
            'redirect_mode':    redirect_mode,
            'notification_id':  notification_id,
            'billing_address':  billing_address,
        }
        if branch:
            payload['branch'] = branch
        if account_number:
            payload['account_number'] = account_number
        if subscription_details:
            payload['subscription_details'] = subscription_details

        result = self._post('submit_order', payload)
        if result['success'] and result['data'].get('order_tracking_id'):
            d = result['data']
            return {
                'success':            True,
                'order_tracking_id':  d['order_tracking_id'],
                'merchant_reference': d.get('merchant_reference'),
                'redirect_url':       d.get('redirect_url'),
            }
        return {
            'success': False,
            'error':   result.get('data', {}).get('message', 'Order submission failed'),
            'raw':     result.get('data'),
        }

    # ── Transaction status ────────────────────────────────────────────────────

    def get_transaction_status(self, order_tracking_id: str) -> dict:
        result = self._get('get_status', params={'orderTrackingId': order_tracking_id})
        if result['success']:
            d = result['data']
            code = d.get('status_code')
            return {
                'success':                   True,
                'status_code':               code,
                'status_description':        STATUS_CODE_MAP.get(code, 'UNKNOWN'),
                'payment_method':            d.get('payment_method'),
                'amount':                    d.get('amount'),
                'currency':                  d.get('currency'),
                'confirmation_code':         d.get('confirmation_code'),
                'payment_account':           d.get('payment_account'),
                'merchant_reference':        d.get('merchant_reference'),
                'payment_status_description': d.get('payment_status_description'),
                'description':               d.get('description'),
                'created_date':              d.get('created_date'),
                'subscription_transaction_info': d.get('subscription_transaction_info'),
                'raw': d,
            }
        return result

    # ── Refund ────────────────────────────────────────────────────────────────

    def request_refund(self, confirmation_code: str, amount: float, username: str, remarks: str) -> dict:
        result = self._post('refund', {
            'confirmation_code': confirmation_code,
            'amount':            str(amount),
            'username':          username,
            'remarks':           remarks,
        })
        if result['success']:
            return {'success': True, 'message': result['data'].get('message', 'Refund submitted')}
        return {'success': False, 'error': result.get('data', {}).get('message', 'Refund failed')}

    # ── Cancel order ──────────────────────────────────────────────────────────

    def cancel_order(self, order_tracking_id: str) -> dict:
        result = self._post('cancel_order', {'order_tracking_id': order_tracking_id})
        if result['success']:
            return {'success': True, 'message': result['data'].get('message', 'Cancelled')}
        return {'success': False, 'error': result.get('data', {}).get('message', 'Cancellation failed')}
