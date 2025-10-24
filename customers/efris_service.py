import requests
import json
import logging
from django.conf import settings
from django.utils import timezone
from typing import Dict, Any, Optional
from .models import Customer, EFRISCustomerSync

logger = logging.getLogger(__name__)


class EFRISCustomerService:
    """Service class to handle eFRIS customer operations"""

    def __init__(self):
        self.base_url = getattr(settings, 'EFRIS_BASE_URL', '')
        self.api_key = getattr(settings, 'EFRIS_API_KEY', '')
        self.tin = getattr(settings, 'EFRIS_COMPANY_TIN', '')
        self.device_no = getattr(settings, 'EFRIS_DEVICE_NO', '')
        self.timeout = getattr(settings, 'EFRIS_TIMEOUT', 30)

        if not all([self.base_url, self.api_key, self.tin, self.device_no]):
            logger.warning("eFRIS configuration is incomplete")

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers for eFRIS API"""
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
            'X-Company-TIN': self.tin,
            'X-Device-No': self.device_no,
        }

    def _make_request(self, endpoint: str, payload: Dict[str, Any], method: str = 'POST') -> Dict[str, Any]:
        """Make HTTP request to eFRIS API"""
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        headers = self._get_headers()

        try:
            if method.upper() == 'POST':
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout
                )
            elif method.upper() == 'GET':
                response = requests.get(
                    url,
                    headers=headers,
                    params=payload,
                    timeout=self.timeout
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return {
                'success': True,
                'data': response.json(),
                'status_code': response.status_code
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"eFRIS API request failed: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'status_code': getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
            }
        except Exception as e:
            logger.error(f"Unexpected error in eFRIS request: {str(e)}")
            return {
                'success': False,
                'error': f"Unexpected error: {str(e)}"
            }

    def register_customer(self, customer: Customer) -> Dict[str, Any]:
        """Register a customer with eFRIS"""
        if not customer.can_sync_to_efris:
            return {
                'success': False,
                'error': 'Customer does not have required information for eFRIS registration'
            }

        # Create sync record
        sync_record = EFRISCustomerSync.objects.create(
            customer=customer,
            sync_type='REGISTER',
            status='PENDING'
        )

        try:
            # Update customer status
            customer.efris_status = 'PENDING'
            customer.save()

            # Prepare payload
            payload = self._prepare_customer_payload(customer)
            sync_record.request_payload = payload
            sync_record.save()

            # Make API request
            response = self._make_request('customers/register', payload)

            if response['success']:
                data = response['data']

                # Extract eFRIS customer ID from response
                efris_customer_id = data.get('customerID') or data.get('customerId')
                reference_no = data.get('referenceNo') or data.get('reference')

                if efris_customer_id:
                    # Mark customer as registered
                    customer.mark_efris_registered(efris_customer_id, reference_no)

                    # Mark sync as successful
                    sync_record.mark_success(
                        response_data=data,
                        efris_reference=reference_no
                    )

                    logger.info(f"Customer {customer.name} registered in eFRIS with ID: {efris_customer_id}")

                    return {
                        'success': True,
                        'efris_id': efris_customer_id,
                        'reference': reference_no,
                        'response_data': data
                    }
                else:
                    error_msg = "No customer ID returned from eFRIS"
                    customer.mark_efris_error(error_msg)
                    sync_record.mark_failed(error_msg)
                    return {'success': False, 'error': error_msg}
            else:
                # Handle API error
                error_msg = response.get('error', 'Unknown eFRIS API error')
                customer.mark_efris_error(error_msg)
                sync_record.mark_failed(error_msg)
                return {'success': False, 'error': error_msg}

        except Exception as e:
            error_msg = f"Exception during eFRIS registration: {str(e)}"
            logger.error(error_msg)
            customer.mark_efris_error(error_msg)
            sync_record.mark_failed(error_msg)
            return {'success': False, 'error': error_msg}

    def update_customer(self, customer: Customer) -> Dict[str, Any]:
        """Update a customer in eFRIS"""
        if not customer.is_efris_registered:
            return {
                'success': False,
                'error': 'Customer is not registered in eFRIS'
            }

        # Create sync record
        sync_record = EFRISCustomerSync.objects.create(
            customer=customer,
            sync_type='UPDATE',
            status='PENDING'
        )

        # try:
        #     # Prepare payload with eFRIS customer ID
        #     payload = self._prepare_customer_payload(customer)
        #     payload['customerID'] = customer.efris_customer_id
        #
        #     sync_record.request_payload = payload
        #     sync_record.save()

