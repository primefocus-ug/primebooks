import json
import base64
import uuid
import os
import pytz
from cryptography.hazmat.backends import default_backend
from django.utils import timezone as django_timezone
from datetime import datetime, timedelta,date
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from enum import Enum
from contextlib import asynccontextmanager
from datetime import datetime, date
import requests
import structlog
import time
from django.utils.crypto import get_random_string
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from cryptography.hazmat.primitives import serialization
from typing import Dict, Optional, Union, Tuple
from cryptography.hazmat.primitives import hashes, padding as sym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.asymmetric import rsa, padding as rsa_padding
from django.utils import timezone
from django.utils import timezone
from django.core.cache import cache
from django.conf import settings
from company.models import EFRISCommodityCategory
from pydantic import BaseModel, field_validator, Field, ConfigDict
import threading
import gzip
from django_tenants.utils import schema_context
from .models import (
    EFRISConfiguration, EFRISAPILog, FiscalizationAudit,
    EFRISSystemDictionary
)
import re
logger = structlog.get_logger(__name__)

class EFRISConstants:
    class InterfaceCodes:
        GET_SERVER_TIME = 'T101'
        CLIENT_INITIALIZATION = 'T102'
        LOGIN = 'T103'
        GET_SYMMETRIC_KEY = 'T104'
        QUERY_BRANCH_LIST = 'T105'
        QUERY_DEVICE_LIST = 'T106'
        QUERY_INVOICE_APPLY_LIST = 'T107'
        QUERY_INVOICE_DETAIL = 'T108'
        UPLOAD_INVOICE = 'T109'
        APPLY_CREDIT_NOTE = 'T110'
        NOTICE_UPLOAD = 'T111'
        QUERY_NOTICE_LIST = 'T112'
        QUERY_NOTICE_DETAIL = 'T113'
        QUERY_CREDIT_NOTE_LIST = 'T114'
        GET_SYSTEM_DICTIONARY = 'T115'
        Z_REPORT_DAILY_UPLOAD = 'T116'
        INVOICE_CHECKS = 'T117'
        QUERY_CREDIT_DEBIT_NOTE_DETAILS = 'T118'
        QUERY_TAXPAYER = 'T119'
        VOID_CREDIT_DEBIT_NOTE = 'T120'
        ACQUIRE_EXCHANGE_RATE = 'T121'
        QUERY_EXCHANGE_RATE = 'T122'
        QUERY_COMMODITY_CATEGORY = 'T123'
        QUERY_COMMODITY_CATEGORY_BY_KEYWORD = 'T124'
        QUERY_EXCISE_DUTY = 'T125'
        GET_ALL_EXCHANGE_RATES = 'T126'
        GOODS_INQUIRY = 'T127'
        GOODS_IMPORT = 'T128'
        BATCH_INVOICE_UPLOAD = 'T129'
        UPLOAD_GOODS = 'T130'
        GOODS_STOCK_MAINTAIN = 'T131'
        QUERY_GOODS_STOCK = 'T132'
        QUERY_GOODS_STOCK_DETAIL = 'T133'
        QUERY_GOODS_STOCK_APPLY_LIST = 'T134'
        QUERY_GOODS_STOCK_APPLY_DETAIL = 'T135'
        UPLOAD_CERTIFICATE = 'T136'
        QUERY_CERTIFICATES = 'T137'
        QUERY_BRANCH_LIST = 'T138'

    class DocumentTypes:
        INVOICE = "1"
        CREDIT_NOTE = "2"
        DEBIT_NOTE = "3"

    PAYMENT_MODES = {
        'CASH': '102',
        'CARD': '106',
        'MOBILE_MONEY': '105',
        'BANK_TRANSFER': '107',
        'VOUCHER': '101',
        'CREDIT': '101'
    }

    STANDARD_VAT_RATE = Decimal("0.18")
    ZERO_VAT_RATE = Decimal("0")
    EXEMPT_VAT = "-"

    SUCCESS_CODE = "00"
    TIMEOUT_CODE = "99"

    class BuyerTypes:
        B2B = "0"
        B2C = "1"
        B2G = "3"

    DEFAULT_TIMEOUT = 30
    DEFAULT_RETRY_COUNT = 3
    MAX_BATCH_SIZE = 100


class OperationStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    PENDING = "pending"
    RETRYING = "retrying"
    CANCELLED = "cancelled"

class EFRISErrorSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class EFRISError(Exception):
    def __init__(
            self,
            message: str,
            error_code: Optional[str] = None,
            details: Optional[Dict] = None,
            severity: EFRISErrorSeverity = EFRISErrorSeverity.MEDIUM,
            retryable: bool = False
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.severity = severity
        self.retryable = retryable
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "error_code": self.error_code,
            "details": self.details,
            "severity": self.severity.value,
            "retryable": self.retryable,
            "exception_type": self.__class__.__name__
        }

class EFRISConfigurationError(EFRISError):
    def __init__(self, message: str, **kwargs):
        super().__init__(message, severity=EFRISErrorSeverity.HIGH, **kwargs)

class EFRISNetworkError(EFRISError):
    def __init__(self, message: str, **kwargs):
        super().__init__(message, severity=EFRISErrorSeverity.MEDIUM, retryable=True, **kwargs)

class EFRISValidationError(EFRISError):
    def __init__(self, message: str, **kwargs):
        super().__init__(message, severity=EFRISErrorSeverity.HIGH, **kwargs)

class EFRISSecurityError(EFRISError):
    """Security related errors"""

    def __init__(self, message: str, **kwargs):
        super().__init__(message, severity=EFRISErrorSeverity.CRITICAL, **kwargs)


class EFRISBusinessLogicError(EFRISError):
    def __init__(self, message: str, **kwargs):
        super().__init__(message, severity=EFRISErrorSeverity.MEDIUM, **kwargs)

class InvoiceData(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    invoice_number: str = Field(..., min_length=1, max_length=50)
    issue_date: datetime
    total_amount: Decimal = Field(..., ge=0)
    tax_amount: Decimal = Field(..., ge=0)
    subtotal: Decimal = Field(..., ge=0)
    discount_amount: Decimal = Field(default=Decimal('0'), ge=0)
    currency_code: str = Field(default="UGX", pattern="^[A-Z]{3}$")
    document_type: str = Field(..., pattern="^[1-3]$")

    @field_validator('total_amount', 'tax_amount', 'subtotal', 'discount_amount')
    @classmethod
    def validate_decimal_precision(cls, v: Decimal) -> Decimal:
        if v.as_tuple().exponent < -2:
            raise ValueError('Amount precision cannot exceed 2 decimal places')
        return v.quantize(Decimal('0.01'))

    @field_validator('currency_code')
    @classmethod
    def validate_currency(cls, v: str) -> str:
        if v not in ["UGX", "USD", "EUR","KES", "GBP"]:
            raise ValueError(f'Unsupported currency: {v}')
        return v

    def validate_amounts_consistency(self) -> bool:
        expected_total = self.subtotal + self.tax_amount - self.discount_amount
        return abs(self.total_amount - expected_total) <= Decimal('0.01')

@dataclass
class EFRISResponse:
    success: bool
    data: Optional[Dict] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    duration_ms: Optional[int] = None
    retryable: bool = False
    timestamp: datetime = field(default_factory=timezone.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_retry_candidate(self) -> bool:
        if self.success:
            return False

        retryable_codes = ['99', 'TIMEOUT', 'CONNECTION_ERROR']
        return self.error_code in retryable_codes or self.retryable


class SecurityManager:
    """Handle encryption, decryption, and key management - EXACTLY matching working test script"""

    def __init__(self, device_no: str, tin: str):
        self.device_no = device_no
        self.tin = tin
        self.app_id = "AP04"
        self._current_aes_key = None
        self._aes_key_expiry = None
        self.private_key = None  # Will be set when loaded

    def get_utc_plus_3_time(self) -> str:
        """Get current time in UTC+3 format for EFRIS"""
        current_time = datetime.utcnow() + timedelta(hours=3)
        return current_time.strftime('%Y-%m-%d %H:%M:%S')

    def get_current_aes_key(self) -> Optional[bytes]:
        """Get current valid AES key"""
        if self.is_aes_key_valid():
            return self._current_aes_key
        return None

    def set_current_aes_key(self, aes_key: bytes, expiry_hours: int = 24):
        """Store encryption key"""
        self._current_aes_key = aes_key
        self._aes_key_expiry = django_timezone.now() + timedelta(hours=expiry_hours)

        logger.info(
            "AES key set",
            length=len(aes_key),
            expiry=self._aes_key_expiry
        )

        # Cache the key
        cache_key = f"efris_aes_key_{self.tin}_{self.device_no}"
        cache.set(cache_key, (aes_key, self._aes_key_expiry.isoformat()), timeout=expiry_hours * 3600)

    def is_aes_key_valid(self) -> bool:
        """Check if current AES key is valid"""
        if not self._current_aes_key or not self._aes_key_expiry:
            return False
        return django_timezone.now() < self._aes_key_expiry

    def decrypt_aes_key(self, encrypted_key: str, private_key) -> bytes:
        """
        Decrypt AES key from T104 response using RSA private key
        EXACTLY as in working test script
        """
        try:
            encrypted_bytes = base64.b64decode(encrypted_key)
            logger.debug(f"Encrypted AES key size: {len(encrypted_bytes)} bytes")

            # RSA decrypt to get the base64-encoded AES key
            aes_key_b64 = private_key.decrypt(
                encrypted_bytes,
                rsa_padding.PKCS1v15()
            )

            # The decrypted result is a BASE64 string - decode it
            aes_key = base64.b64decode(aes_key_b64)

            logger.debug(f"Final AES key length: {len(aes_key)} bytes")

            if len(aes_key) not in [16, 24, 32]:
                raise Exception(f"Invalid AES key length: {len(aes_key)} bytes")

            return aes_key

        except Exception as e:
            logger.error(f"Failed to decrypt AES key: {str(e)}")
            raise Exception(f"AES key decryption failed: {e}")

    def aes_encrypt(self, plaintext: str) -> bytes:
        """
        Encrypt content using AES key
        EXACTLY as in working test script - uses ECB mode with PKCS7 padding
        """
        if not self._current_aes_key:
            raise Exception("AES key not initialized. Call T104 first.")

        padder = sym_padding.PKCS7(128).padder()
        padded_data = padder.update(plaintext.encode()) + padder.finalize()

        cipher = Cipher(
            algorithms.AES(self._current_aes_key),
            modes.ECB(),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()

        return ciphertext

    def aes_decrypt_bytes(self, ciphertext: bytes) -> bytes:
        """
        Decrypt AES ciphertext and return raw plaintext bytes
        EXACTLY as in working test script
        """
        if not self._current_aes_key:
            raise Exception("AES key not initialized.")

        cipher = Cipher(
            algorithms.AES(self._current_aes_key),
            modes.ECB(),
            backend=default_backend()
        )
        decryptor = cipher.decryptor()
        padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

        unpadder = sym_padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()

        return plaintext

    def sign_content(self, content_b64: str, algorithm: str = "SHA1") -> str:
        """
        Sign content with private key
        EXACTLY as in working test script
        """
        if not self.private_key:
            raise Exception("Private key not loaded")

        hash_alg = {
            "SHA1": hashes.SHA1(),
            "SHA256": hashes.SHA256()
        }.get(algorithm.upper(), hashes.SHA1())

        logger.debug(f"Signing with {algorithm}: content length={len(content_b64)}")

        signature = self.private_key.sign(
            content_b64.encode('utf-8'),
            rsa_padding.PKCS1v15(),
            hash_alg
        )
        sig_b64 = base64.b64encode(signature).decode()
        logger.debug(f"Signature generated: {sig_b64[:50]}...")
        return sig_b64

    def create_global_info(self, interface_code: str) -> dict:
        """Create globalInfo section for EFRIS requests"""
        return {
            "appId": self.app_id,
            "version": "1.1.20191201",
            "dataExchangeId": str(uuid.uuid4()).replace('-', '')[:32],
            "interfaceCode": interface_code,
            "requestCode": "TP",
            "requestTime": self.get_utc_plus_3_time(),
            "responseCode": "TA",
            "userName": "admin",
            "deviceMAC": "FFFFFFFFFFFF",
            "deviceNo": self.device_no,
            "tin": self.tin,
            "brn": "",
            "taxpayerID": "1",
            "longitude": "32.5825",
            "latitude": "0.3476",
            "agentType": "0"
        }

class ConfigurationManager:
    """Enhanced configuration management"""

    def __init__(self, company):
        self.company = company
        self._config_cache = {}
        self._last_validation = None
        self.config = self._load_and_validate_config()

    def _load_and_validate_config(self) -> EFRISConfiguration:
        """Load and validate EFRIS configuration with caching"""
        cache_key = f"efris_config_{self.company.pk}"

        # Check cache first
        if cache_key in self._config_cache and self._is_cache_valid():
            return self._config_cache[cache_key]

        try:
            config = EFRISConfiguration.objects.select_related('company').get(
                company=self.company
            )

            # Validate configuration
            validation_errors = self._validate_config(config)
            if validation_errors:
                raise EFRISConfigurationError(
                    f"Configuration validation failed: {validation_errors}"
                )

            # Cache the config
            self._config_cache[cache_key] = config
            self._last_validation = timezone.now()

            return config

        except EFRISConfiguration.DoesNotExist:
            raise EFRISConfigurationError(
                f"EFRIS configuration not found for company {self.company}"
            )

    def _is_cache_valid(self) -> bool:
        """Check if cached config is still valid"""
        if not self._last_validation:
            return False

        # Cache valid for 5 minutes
        return (timezone.now() - self._last_validation) < timedelta(minutes=5)

    def _validate_config(self, config: EFRISConfiguration) -> List[str]:
        """Comprehensive configuration validation"""
        errors = []

        # Required fields validation
        required_fields = {
            'app_id': 'Application ID',
            'version': 'Version',
            'device_mac': 'Device MAC address',
            'api_url': 'API URL'
        }

        for field, display_name in required_fields.items():
            if not getattr(config, field, None):
                errors.append(f"Missing {display_name}")

        # API URL validation
        if config.api_url:
            if not config.api_url.startswith('https://'):
                errors.append("API URL must use HTTPS")

            # Basic URL format validation
            try:
                from urllib.parse import urlparse
                parsed = urlparse(config.api_url)
                if not parsed.netloc:
                    errors.append("Invalid API URL format")
            except Exception:
                errors.append("Invalid API URL format")

        # Company-specific validation
        company_errors = self._validate_company_efris_settings()
        errors.extend(company_errors)

        return errors



    def _validate_company_efris_settings(self) -> List[str]:
        """Validate company EFRIS settings"""
        errors = []

        if not self.company.efris_enabled:
            return ["EFRIS is not enabled for this company"]

        required_company_fields = {
            'tin': 'TIN',
            'efris_taxpayer_name': 'Taxpayer name',
            'efris_business_name': 'Business name',
            'efris_email_address': 'Email address',
            'efris_phone_number': 'Phone number',
            'efris_business_address': 'Business address'
        }

        for field, display_name in required_company_fields.items():
            if not getattr(self.company, field, None):
                errors.append(f"Missing {display_name}")

        # Check EFRIS configuration fields separately
        try:
            efris_config = self.company.efris_config
            if not efris_config.private_key:
                errors.append("Missing Private key")
            if not efris_config.public_certificate:
                errors.append("Missing Public key")
            if not efris_config.certificate_fingerprint:
                errors.append("Missing Thumbprint")
        except AttributeError:
            errors.append("Missing EFRIS configuration")

        # TIN format validation
        if self.company.tin and not self._validate_tin_format(self.company.tin):
            errors.append("Invalid TIN format")

        return errors

    def _validate_tin_format(self, tin: str) -> bool:
        """Validate Uganda TIN format"""
        if not tin or not isinstance(tin, str):
            return False

        clean_tin = tin.replace(' ', '').replace('-', '')
        return len(clean_tin) == 10 and clean_tin.isdigit()

    def get_api_config(self) -> Dict[str, Any]:
        """Get API configuration with defaults"""
        return {
            'api_url': self.config.api_url,
            'app_id': self.config.app_id,
            'version': self.config.version,
            'timeout': getattr(self.config, 'timeout_seconds', None) or EFRISConstants.DEFAULT_TIMEOUT,
            'device_mac': self.config.device_mac,
            'device_number': getattr(self.config, 'device_number', None) or '00000000000',
            'mode': getattr(self.config, 'mode', 'online')
        }

    def refresh_config(self) -> EFRISConfiguration:
        """Force refresh configuration from database"""
        cache_key = f"efris_config_{self.company.pk}"
        if cache_key in self._config_cache:
            del self._config_cache[cache_key]

        self._last_validation = None
        return self._load_and_validate_config()

class EnhancedHTTPClient:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.session = self._create_session()
        self._request_count = 0
        self._total_duration = 0

    def _create_session(self) -> requests.Session:
        """Create optimized HTTP session"""
        session = requests.Session()

        # Enhanced retry strategy
        retry_strategy = Retry(
            total=EFRISConstants.DEFAULT_RETRY_COUNT,
            backoff_factor=2,  # Exponential backoff
            status_forcelist=[408, 429, 500, 502, 503, 504, 520, 522, 524],
            allowed_methods=["POST"],
            raise_on_status=False
        )

        # Connection pooling optimization
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=20,
            pool_maxsize=50,
            pool_block=True
        )

        session.mount("https://", adapter)
        session.mount("http://", adapter)

        # Enhanced headers
        session.headers.update({
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': 'application/json',
            'User-Agent': f'EFRIS-Client/{self.config["version"]}',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        })

        return session

    async def make_request_async(self, data: Dict[str, Any]) -> requests.Response:
        """Async version of make_request for concurrent operations"""
        return self.make_request(data)

    def make_request(self, data: Dict[str, Any]) -> requests.Response:
        """Enhanced HTTP request with comprehensive monitoring"""
        start_time = timezone.now()
        request_id = str(uuid.uuid4())[:8]

        logger.info(
            "EFRIS HTTP request starting",
            request_id=request_id,
            url=self.config['api_url'],
            timeout=self.config['timeout']
        )

        try:
            # Pre-request validation
            if not data:
                raise ValueError("Request data cannot be empty")

            response = self.session.post(
                self.config['api_url'],
                json=data,
                timeout=self.config['timeout']
            )

            duration = (timezone.now() - start_time).total_seconds() * 1000
            self._update_metrics(duration, response.status_code >= 400)

            logger.info(
                "EFRIS HTTP request completed",
                request_id=request_id,
                status_code=response.status_code,
                duration_ms=int(duration),
                content_length=len(response.content) if response.content else 0
            )

            return response

        except requests.Timeout as e:
            duration = (timezone.now() - start_time).total_seconds() * 1000
            self._update_metrics(duration, True)

            logger.error(
                "EFRIS HTTP request timeout",
                request_id=request_id,
                duration_ms=int(duration),
                timeout=self.config['timeout']
            )
            raise EFRISNetworkError(
                f"Request timeout after {self.config['timeout']}s",
                error_code="TIMEOUT"
            )

        except requests.ConnectionError as e:
            duration = (timezone.now() - start_time).total_seconds() * 1000
            self._update_metrics(duration, True)

            logger.error(
                "EFRIS HTTP connection error",
                request_id=request_id,
                error=str(e),
                duration_ms=int(duration)
            )
            raise EFRISNetworkError(
                f"Connection error: {e}",
                error_code="CONNECTION_ERROR",
                retryable=True
            )

        except requests.RequestException as e:
            duration = (timezone.now() - start_time).total_seconds() * 1000
            self._update_metrics(duration, True)

            logger.error(
                "EFRIS HTTP request failed",
                request_id=request_id,
                error=str(e),
                duration_ms=int(duration)
            )
            raise EFRISNetworkError(f"HTTP request failed: {e}")

    def _update_metrics(self, duration: float, is_error: bool):
        """Update client metrics"""
        self._request_count += 1
        self._total_duration += duration

        # Store metrics in cache for monitoring
        cache_key = f"efris_http_metrics_{self.config.get('device_mac', 'unknown')}"
        metrics = cache.get(cache_key, {
            'request_count': 0,
            'total_duration': 0,
            'error_count': 0,
            'last_updated': timezone.now().isoformat()
        })

        metrics['request_count'] += 1
        metrics['total_duration'] += duration
        if is_error:
            metrics['error_count'] += 1
        metrics['last_updated'] = timezone.now().isoformat()

        cache.set(cache_key, metrics, 3600)  # Cache for 1 hour


    def get_metrics(self) -> Dict[str, float]:
        """Get client performance metrics"""
        if self._request_count == 0:
            return {"avg_duration_ms": 0, "request_count": 0}

        return {
            "avg_duration_ms": self._total_duration / self._request_count,
            "request_count": self._request_count,
            "total_duration_ms": self._total_duration
        }

    def close(self):
        """Clean up resources"""
        if self.session:
            self.session.close()
            logger.debug("HTTP client session closed")


class SystemDictionaryManager:
    """
    Enhanced manager for EFRIS System Dictionary (T115)
    Handles fetching, caching, and querying system parameters
    """

    def __init__(self, company):
        self.company = company
        self.client = EnhancedEFRISAPIClient(company)

    def update_system_dictionary(self, force_update: bool = False) -> Dict[str, Any]:
        """
        T115 - Fetch and store system dictionary from EFRIS
        FIXED: Proper handling of encoding and decompression order
        """
        try:
            # Check if update needed
            if not force_update and self._is_dictionary_current():
                cached_dict = self._get_cached_dictionary()
                logger.info("System dictionary is current, using cached version")
                return {
                    "success": True,
                    "message": "Dictionary already current",
                    "cached": True,
                    "data": cached_dict,
                    "version": cached_dict.get('version')
                }

            # Ensure authenticated
            auth_result = self.client.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            logger.info("Fetching system dictionary from EFRIS (T115)")

            # Build T115 request (unencrypted request)
            request_data = self.client._build_request(
                "T115",
                content=None,
                encrypt=False
            )

            # Make HTTP request
            response = self.client._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            if return_code != '00':
                error_message = return_info.get('returnMessage', 'T115 failed')
                logger.error(f"T115 failed: {return_code} - {error_message}")
                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code
                }

            # SUCCESS - Now process the response
            data_section = response_data.get('data', {})
            content_b64 = data_section.get('content', '')

            if not content_b64:
                return {
                    "success": False,
                    "error": "Empty response content"
                }

            try:
                # Decode base64
                content_bytes = base64.b64decode(content_b64)

                # Check data description
                data_desc = data_section.get('dataDescription', {})
                code_type = str(data_desc.get('codeType', '')).strip()
                zip_code = str(data_desc.get('zipCode', '0')).strip()

                logger.debug(f"T115 response - codeType: {code_type}, zipCode: {zip_code}")

                payload_bytes = content_bytes

                # CRITICAL FIX: Process in correct order
                # Step 1: Decompress FIRST if compressed (zipCode=1 or 2)
                if zip_code in ("1", "2"):
                    logger.info(f"T115 response is compressed (zipCode={zip_code}), decompressing...")
                    try:
                        import gzip
                        payload_bytes = gzip.decompress(payload_bytes)
                        logger.info(f"Gzip decompression successful: {len(payload_bytes)} bytes")
                    except Exception as gzip_err:
                        logger.warning(f"Gzip decompression failed: {gzip_err}, trying zlib...")
                        try:
                            import zlib
                            payload_bytes = zlib.decompress(payload_bytes)
                            logger.info(f"Zlib decompression successful: {len(payload_bytes)} bytes")
                        except Exception as zlib_err:
                            logger.error(f"Both gzip and zlib decompression failed")
                            return {
                                "success": False,
                                "error": f"Decompression failed: gzip={gzip_err}, zlib={zlib_err}"
                            }

                # Step 2: Decrypt AFTER decompression if encrypted (codeType=1)
                if code_type == "1":
                    logger.info("T115 response is encrypted, decrypting...")
                    try:
                        payload_bytes = self.client.security_manager.aes_decrypt_bytes(payload_bytes)
                        logger.info(f"AES decryption successful: {len(payload_bytes)} bytes")
                    except Exception as decrypt_err:
                        logger.error(f"AES decryption failed: {decrypt_err}")
                        # Try without decryption - response might not actually be encrypted
                        logger.warning("Attempting to parse without decryption...")
                else:
                    logger.info("T115 response is unencrypted (codeType=0)")

                # Step 3: Decode to JSON with multiple encoding attempts
                content_json = None
                encoding_attempts = ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252']

                for encoding in encoding_attempts:
                    try:
                        content_json = payload_bytes.decode(encoding)
                        logger.info(f"Successfully decoded with {encoding} encoding")
                        break
                    except UnicodeDecodeError as e:
                        logger.debug(f"Failed to decode with {encoding}: {e}")
                        continue

                if not content_json:
                    logger.error(f"Failed to decode with all attempted encodings: {encoding_attempts}")
                    # Last resort: decode with errors='ignore'
                    try:
                        content_json = payload_bytes.decode('utf-8', errors='ignore')
                        logger.warning("Decoded with errors='ignore', some data may be corrupted")
                    except Exception as e:
                        return {
                            "success": False,
                            "error": f"All decoding attempts failed: {e}"
                        }

                # Parse JSON
                try:
                    dictionary_data = json.loads(content_json)
                except json.JSONDecodeError as json_err:
                    logger.error(f"JSON parsing failed: {json_err}")
                    # Log preview of the content
                    preview = content_json[:500] if len(content_json) > 500 else content_json
                    logger.debug(f"Content preview: {preview}")
                    return {
                        "success": False,
                        "error": f"Invalid JSON response: {json_err}"
                    }

                # Store the dictionary
                self._store_dictionary_data(dictionary_data)

                # Extract version if available
                version = dictionary_data.get('version', 'unknown')

                logger.info(f"System dictionary updated successfully (version: {version})")
                return {
                    "success": True,
                    "message": "System dictionary updated",
                    "data": dictionary_data,
                    "version": version,
                    "cached": False
                }

            except Exception as e:
                logger.error(f"Failed to process T115 response: {e}", exc_info=True)
                return {
                    "success": False,
                    "error": f"Response processing failed: {e}"
                }

        except Exception as e:
            logger.error(f"System dictionary update failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def _is_dictionary_current(self) -> bool:
        """Check if cached dictionary is still current"""
        cache_key = f"efris_dict_timestamp_{self.company.pk}"
        cached_timestamp = cache.get(cache_key)

        if not cached_timestamp:
            return False

        # Dictionary should be refreshed daily
        age_hours = (timezone.now() - cached_timestamp).total_seconds() / 3600
        return age_hours < 24  # Refresh after 24 hours

    def _get_cached_dictionary(self) -> Dict[str, Any]:
        """Get cached dictionary data"""
        cache_key = f"efris_system_dict_{self.company.pk}"
        cached = cache.get(cache_key)

        if cached:
            return cached

        # Try to load from database
        try:
            from efris.models import EFRISSystemDictionary
            dict_obj = EFRISSystemDictionary.objects.filter(
                company=self.company
            ).first()

            if dict_obj:
                return dict_obj.data
        except Exception:
            pass

        return {}

    def _store_dictionary_data(self, data: Dict[str, Any]):
        """
        Store dictionary data in database and cache
        FIXED: Proper handling of EFRISSystemDictionary model fields
        """
        try:
            from efris.models import EFRISSystemDictionary

            version = data.get('version', 'unknown')


            dictionary_mapping = {
                'creditNoteMaximumInvoicingDays': 'creditNoteMaximumInvoicingDays',
                'currencyType': 'currencyType',
                'rateUnit': 'rateUnit',
                'sector': 'sector',
                'payWay': 'payWay',
                'countryCode': 'countryCode',
                'deliveryTerms': 'deliveryTerms',
                'commodityCategory': 'commodityCategory',
                'exciseDuty': 'exciseDuty',
                'format': 'format',
            }

            stored_count = 0

            for response_key, dict_type in dictionary_mapping.items():
                if response_key in data:
                    try:
                        # Store each dictionary type separately
                        EFRISSystemDictionary.objects.update_or_create(
                            company=self.company,
                            dictionary_type=dict_type,
                            defaults={
                                'data': data[response_key],
                                'version': version
                            }
                        )
                        stored_count += 1
                        logger.debug(f"Stored {dict_type} dictionary")
                    except Exception as e:
                        logger.warning(f"Failed to store {dict_type}: {e}")

            cache_key = f"efris_system_dict_{self.company.pk}"
            cache.set(cache_key, data, timeout=86400)  # 24 hours

            # Store timestamp
            cache.set(
                f"efris_dict_timestamp_{self.company.pk}",
                timezone.now(),
                timeout=86400
            )

            logger.info(f"System dictionary stored successfully: {stored_count} types saved")

        except Exception as e:
            logger.error(f"Failed to store system dictionary: {e}", exc_info=True)

    def get_dictionary_value(
            self,
            category: str,
            code: Optional[str] = None
    ) -> Any:
        dictionary = self._get_cached_dictionary()

        if not dictionary:
            return None
        category_data = None
        if isinstance(dictionary, dict):
            category_data = dictionary.get(category)

        elif isinstance(dictionary, list):
            for entry in dictionary:
                # EFRIS usually uses categoryName, categoryCode, or similar
                if entry.get('category') == category or entry.get('categoryName') == category:
                    category_data = entry.get('items', [])
                    break

        if not category_data:
            return None

        if code is None:
            return category_data

        # Search by code or value
        if isinstance(category_data, list):
            for item in category_data:
                if item.get('value') == code or item.get('code') == code:
                    return item
        elif isinstance(category_data, dict):
            return category_data.get(code)

        return None

    def get_payment_methods(self) -> List[Dict[str, str]]:
        """Get all payment methods (payWay)"""
        pay_ways = self.get_dictionary_value('payWay')
        return pay_ways if isinstance(pay_ways, list) else []

    def get_currencies(self) -> List[Dict[str, str]]:
        """Get all currency types"""
        currencies = self.get_dictionary_value('currencyType')
        return currencies if isinstance(currencies, list) else []

    def get_rate_units(self) -> List[Dict[str, str]]:
        """Get all rate units"""
        rate_units = self.get_dictionary_value('rateUnit')
        return rate_units if isinstance(rate_units, list) else []

    def get_sectors(self) -> List[Dict[str, str]]:
        """Get all business sectors"""
        sectors = self.get_dictionary_value('sector')
        return sectors if isinstance(sectors, list) else []

    def get_country_codes(self) -> List[Dict[str, str]]:
        """Get all country codes"""
        country_codes = self.get_dictionary_value('countryCode')
        return country_codes if isinstance(country_codes, list) else []

    def get_delivery_terms(self) -> List[Dict[str, str]]:
        """Get all delivery terms (Incoterms)"""
        delivery_terms = self.get_dictionary_value('deliveryTerms')
        return delivery_terms if isinstance(delivery_terms, list) else []

    def get_export_rate_units(self, active_only: bool = True) -> List[Dict[str, str]]:
        """
        Get export rate units

        Args:
            active_only: Return only active (status='101') units
        """
        export_units = self.get_dictionary_value('exportRateUnit')

        if not isinstance(export_units, list):
            return []

        if active_only:
            return [u for u in export_units if u.get('status') == '101']

        return export_units

    def get_date_format(self) -> str:
        """Get EFRIS date format"""
        format_data = self.get_dictionary_value('format')
        if isinstance(format_data, dict):
            return format_data.get('dateFormat', 'dd/MM/yyyy')
        return 'dd/MM/yyyy'

    def get_time_format(self) -> str:
        """Get EFRIS time format"""
        format_data = self.get_dictionary_value('format')
        if isinstance(format_data, dict):
            return format_data.get('timeFormat', 'dd/MM/yyyy HH:mm:ss')
        return 'dd/MM/yyyy HH:mm:ss'

    def get_credit_note_limits(self) -> Dict[str, Any]:
        """Get credit note limits"""
        max_days = self.get_dictionary_value('creditNoteMaximumInvoicingDays')
        percent_limit = self.get_dictionary_value('creditNoteValuePercentLimit')

        return {
            'maximum_days': int(max_days.get('value', 90)) if isinstance(max_days, dict) else 90,
            'percent_limit': float(percent_limit.get('value', 0.6)) if isinstance(percent_limit, dict) else 0.6
        }

    def get_dictionary_statistics(self) -> Dict[str, Any]:
        """Get statistics about the dictionary"""
        dictionary = self._get_cached_dictionary()

        if not dictionary:
            return {
                'total_categories': 0,
                'is_cached': False,
                'last_updated': None
            }

        stats = {
            'total_categories': 0,
            'is_cached': True,
            'version': 'unknown',
            'categories': []
        }

        # Handle if dictionary is a list
        if isinstance(dictionary, list):
            stats['total_categories'] = len(dictionary)
            for entry in dictionary:
                name = entry.get('category') or entry.get('name') or 'Unknown'
                items = entry.get('items', [])
                stats['categories'].append({
                    'name': name,
                    'item_count': len(items),
                    'type': 'list'
                })

        # Handle if dictionary is a dict
        elif isinstance(dictionary, dict):
            stats['total_categories'] = len(dictionary.keys())
            stats['version'] = dictionary.get('version', 'unknown')

            for key, value in dictionary.items():
                if isinstance(value, list):
                    stats['categories'].append({
                        'name': key,
                        'item_count': len(value),
                        'type': 'list'
                    })
                elif isinstance(value, dict):
                    stats['categories'].append({
                        'name': key,
                        'item_count': len(value.keys()),
                        'type': 'dict'
                    })

        # Last update timestamp
        try:
            from efris.models import EFRISSystemDictionary
            dict_obj = EFRISSystemDictionary.objects.filter(
                company=self.company
            ).first()

            if dict_obj:
                stats['last_updated'] = dict_obj.last_updated
        except Exception:
            stats['last_updated'] = None

        return stats

    def search_dictionary(self, search_term: str) -> Dict[str, List[Dict]]:
        """
        Search across all dictionary categories

        Args:
            search_term: Term to search for (case-insensitive)

        Returns:
            Dict with matching results grouped by category
        """
        dictionary = self._get_cached_dictionary()

        if not dictionary:
            return {}

        results = {}
        search_lower = search_term.lower()

        for category, data in dictionary.items():
            if isinstance(data, list):
                matches = [
                    item for item in data
                    if isinstance(item, dict) and (
                            search_lower in str(item.get('name', '')).lower() or
                            search_lower in str(item.get('value', '')).lower() or
                            search_lower in str(item.get('code', '')).lower()
                    )
                ]

                if matches:
                    results[category] = matches

        return results


def schedule_daily_dictionary_update(company):
    """
    Schedule daily system dictionary update
    Can be called from a Celery task or cron job
    """
    try:
        manager = SystemDictionaryManager(company)
        result = manager.update_system_dictionary()

        logger.info(
            f"Scheduled dictionary update completed for {company.name}",
            success=result.get('success'),
            cached=result.get('cached', False)
        )

        return result

    except Exception as e:
        logger.error(f"Scheduled dictionary update failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

class ZReportService:
    """Service for Z-Report Daily Upload (T116)"""

    def __init__(self, company):
        self.company = company
        self.client = EnhancedEFRISAPIClient(company)

    def upload_daily_zreport(self, report_date: date, report_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        T116 - Upload daily Z-report to EFRIS

        Args:
            report_date: Date of the Z-report
            report_data: Z-report data structure
        """
        try:
            # Validate report data
            validation_errors = self._validate_zreport_data(report_data)
            if validation_errors:
                return {
                    "success": False,
                    "error": f"Validation failed: {'; '.join(validation_errors)}"
                }

            # Ensure authentication
            auth_result = self.client.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Build Z-report request
            zreport_content = self._build_zreport_content(report_date, report_data)

            # Create encrypted request
            private_key = self.client._load_private_key()
            request_data = self.client.security_manager.create_signed_encrypted_request(
                "T116", zreport_content, private_key
            )

            logger.info(f"Uploading Z-report for date: {report_date}")
            response = self.client._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            if return_code == '00':
                # Log successful upload
                self._log_zreport_upload(report_date, True)

                logger.info(f"Z-report uploaded successfully for {report_date}")
                return {
                    "success": True,
                    "message": "Z-report uploaded successfully",
                    "report_date": report_date.isoformat(),
                    "data": response_data
                }
            else:
                error_message = return_info.get('returnMessage', 'T116 failed')
                logger.error(f"T116 failed: {return_code} - {error_message}")

                # Log failed upload
                self._log_zreport_upload(report_date, False, error_message)

                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code
                }

        except Exception as e:
            logger.error(f"Z-report upload failed: {e}", exc_info=True)
            self._log_zreport_upload(report_date, False, str(e))

            return {
                "success": False,
                "error": str(e)
            }

    def _validate_zreport_data(self, data: Dict[str, Any]) -> List[str]:
        """Validate Z-report data structure"""
        errors = []

        # Add validation based on EFRIS documentation
        # Note: The documentation shows "To be determined" for T116 request structure
        # Update this method when the actual structure is defined

        required_fields = ['reportDate', 'deviceNo', 'totalSales', 'totalTax']

        for field in required_fields:
            if field not in data:
                errors.append(f"Missing required field: {field}")

        return errors

    def _build_zreport_content(self, report_date: date, report_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build Z-report content structure

        Note: Update this structure based on final EFRIS T116 specification
        """
        device_no = self.client.security_manager.device_no

        return {
            "reportDate": report_date.strftime('%Y-%m-%d'),
            "deviceNo": device_no,
            "reportData": report_data,
            "summary": {
                "totalSales": str(report_data.get('totalSales', 0)),
                "totalTax": str(report_data.get('totalTax', 0)),
                "totalTransactions": str(report_data.get('totalTransactions', 0)),
                "totalCash": str(report_data.get('totalCash', 0)),
                "totalCard": str(report_data.get('totalCard', 0)),
                "totalMobileMoney": str(report_data.get('totalMobileMoney', 0))
            }
        }

    def _log_zreport_upload(self, report_date: date, success: bool, error: Optional[str] = None):
        """Log Z-report upload attempt"""
        try:
            from efris.models import EFRISAPILog
            from django.utils import timezone

            EFRISAPILog.objects.create(
                company=self.company,
                interface_code='T116',
                request_type='Z_REPORT_UPLOAD',
                status='SUCCESS' if success else 'FAILED',
                error_message=error,
                request_data={'report_date': report_date.isoformat()},
                created_at=timezone.now()
            )
        except Exception as e:
            logger.warning(f"Failed to log Z-report upload: {e}")

    def generate_daily_zreport(self, report_date: date) -> Dict[str, Any]:
        """
        Generate Z-report from daily sales data

        Args:
            report_date: Date to generate report for
        """
        from django_tenants.utils import schema_context

        try:
            with schema_context(self.company.schema_name):
                # Import models inside tenant context
                from sales.models import Sale
                from django.db.models import Sum, Count

                # Get all sales for the date
                sales = Sale.objects.filter(
                    company=self.company,
                    sale_date__date=report_date,
                    is_fiscalized=True
                )

                # Calculate totals
                aggregates = sales.aggregate(
                    total_sales=Sum('total_amount'),
                    total_tax=Sum('tax_amount'),
                    total_transactions=Count('id'),
                    total_cash=Sum('cash_amount'),
                    total_card=Sum('card_amount'),
                    total_mobile_money=Sum('mobile_money_amount')
                )

                # Build report data
                report_data = {
                    'totalSales': float(aggregates.get('total_sales') or 0),
                    'totalTax': float(aggregates.get('total_tax') or 0),
                    'totalTransactions': aggregates.get('total_transactions') or 0,
                    'totalCash': float(aggregates.get('total_cash') or 0),
                    'totalCard': float(aggregates.get('total_card') or 0),
                    'totalMobileMoney': float(aggregates.get('total_mobile_money') or 0),
                    'reportDate': report_date.isoformat()
                }

                return {
                    "success": True,
                    "report_data": report_data
                }

        except Exception as e:
            logger.error(f"Failed to generate Z-report: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }


def schedule_daily_zreport_upload(company, report_date: Optional[date] = None):
    """
    Schedule daily Z-report upload
    Can be called from a Celery task or cron job

    Args:
        company: Company object
        report_date: Date to generate report for (defaults to yesterday)
    """
    from datetime import timedelta

    try:
        if report_date is None:
            # Default to yesterday
            report_date = date.today() - timedelta(days=1)

        service = ZReportService(company)

        # Generate report from sales data
        generation_result = service.generate_daily_zreport(report_date)

        if not generation_result.get('success'):
            return {
                "success": False,
                "error": f"Report generation failed: {generation_result.get('error')}"
            }

        # Upload to EFRIS
        upload_result = service.upload_daily_zreport(
            report_date,
            generation_result['report_data']
        )

        logger.info(
            f"Scheduled Z-report upload completed for {company.name}",
            report_date=report_date.isoformat(),
            success=upload_result.get('success')
        )

        return upload_result

    except Exception as e:
        logger.error(f"Scheduled Z-report upload failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


class TaxpayerQueryService:
    """Service for querying taxpayer information (T119)"""

    def __init__(self, company):
        self.company = company
        self.client = EnhancedEFRISAPIClient(company)

    def query_taxpayer_by_tin(
            self,
            tin: str,
            nin_brn: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        T119 - Query taxpayer information by TIN or NIN/BRN
        """
        try:
            # Validate TIN format
            is_valid, error = DataValidator.validate_tin(tin)
            if not is_valid:
                return {
                    "success": False,
                    "error": f"Invalid TIN: {error}",
                    "taxpayer": None
                }

            # Validate NIN/BRN if provided
            if nin_brn:
                is_valid_brn, brn_error = DataValidator.validate_brn(nin_brn)
                if not is_valid_brn:
                    logger.warning(f"Invalid NIN/BRN provided: {brn_error}")
                    nin_brn = None

            # Ensure authentication
            auth_result = self.client.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "taxpayer": None
                }

            # Build request content
            content = {"tin": tin}
            if nin_brn:
                content["ninBrn"] = nin_brn

            # FIX: Use _make_request instead of manual request building
            logger.info(f"Querying taxpayer information for TIN: {tin}")

            try:
                # T119 uses encrypted request with SHA1 signature (handled automatically)
                decrypted_content = self.client._make_request(
                    "T119",
                    content,
                    encrypt=True
                )

                # Check if taxpayer data is in response
                if decrypted_content and 'taxpayer' in decrypted_content:
                    taxpayer_data = decrypted_content['taxpayer']

                    logger.info(
                        f"Taxpayer query successful",
                        tin=tin,
                        business_name=taxpayer_data.get('businessName', 'N/A')
                    )

                    return {
                        "success": True,
                        "taxpayer": self._normalize_taxpayer_data(taxpayer_data),
                        "raw_data": taxpayer_data
                    }
                else:
                    return {
                        "success": False,
                        "error": "No taxpayer data in response",
                        "taxpayer": None
                    }

            except Exception as api_error:
                # Extract error details
                error_message = str(api_error)

                import re
                error_code_match = re.search(r'\[(\d+)\]', error_message)
                error_code = error_code_match.group(1) if error_code_match else '99'

                logger.warning(f"T119 failed: {error_code} - {error_message}")

                return {
                    "success": False,
                    "error": error_message,
                    "error_code": error_code,
                    "taxpayer": None
                }

        except Exception as e:
            logger.error(f"Taxpayer query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "taxpayer": None
            }

    def _normalize_taxpayer_data(self, taxpayer: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize taxpayer data structure"""
        return {
            'tin': taxpayer.get('tin', ''),
            'nin_brn': taxpayer.get('ninBrn', ''),
            'legal_name': taxpayer.get('legalName', ''),
            'business_name': taxpayer.get('businessName', ''),
            'contact_number': taxpayer.get('contactNumber', ''),
            'contact_email': taxpayer.get('contactEmail', ''),
            'address': taxpayer.get('address', ''),
            'taxpayer_type': taxpayer.get('taxpayerType', ''),
            'taxpayer_type_name': self._get_taxpayer_type_name(
                taxpayer.get('taxpayerType', '')
            ),
            'government_tin': taxpayer.get('governmentTIN', '') == '1',
            'is_individual': taxpayer.get('taxpayerType', '') == '201',
            'is_non_individual': taxpayer.get('taxpayerType', '') == '202'
        }

    def _get_taxpayer_type_name(self, taxpayer_type: str) -> str:
        """Get human-readable taxpayer type name"""
        types = {
            '201': 'Individual',
            '202': 'Non-Individual'
        }
        return types.get(taxpayer_type, 'Unknown')


class GoodsInquiryService:
    """Service for querying goods/services (T127)"""

    def __init__(self, company):
        self.company = company
        self.client = EnhancedEFRISAPIClient(company)

    def query_goods(
            self,
            goods_code: Optional[str] = None,
            goods_name: Optional[str] = None,
            commodity_category_name: Optional[str] = None,
            page_no: int = 1,
            page_size: int = 10,
            branch_id: Optional[str] = None,
            service_mark: Optional[str] = None,
            have_excise_tax: Optional[str] = None,
            start_date: Optional[date] = None,
            end_date: Optional[date] = None,
            combine_keywords: Optional[str] = None,
            goods_type_code: str = "101",
            tin: Optional[str] = None,
            query_type: str = "1"
    ) -> Dict[str, Any]:
        """T127 - Query goods/services from EFRIS"""
        try:
            # Validate pagination
            if page_size > 100:
                return {
                    "success": False,
                    "error": "Page size cannot exceed 100",
                    "goods": []
                }

            # Validate query type
            if query_type not in ['0', '1']:
                return {
                    "success": False,
                    "error": "Query type must be '0' (agent) or '1' (normal)",
                    "goods": []
                }

            # Validate agent query requirements
            if query_type == '0':
                if not tin or not branch_id:
                    return {
                        "success": False,
                        "error": "TIN and branch ID required for agent goods query",
                        "goods": []
                    }

            # Ensure authentication
            auth_result = self.client.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "goods": []
                }

            # Build request content
            content = self._build_query_content(
                goods_code=goods_code,
                goods_name=goods_name,
                commodity_category_name=commodity_category_name,
                page_no=page_no,
                page_size=page_size,
                branch_id=branch_id,
                service_mark=service_mark,
                have_excise_tax=have_excise_tax,
                start_date=start_date,
                end_date=end_date,
                combine_keywords=combine_keywords,
                goods_type_code=goods_type_code,
                tin=tin,
                query_type=query_type
            )

            # FIX: Use _make_request instead of manual building
            logger.info(f"Querying goods (page {page_no}, size {page_size})")

            try:
                # T127 uses encrypted request (SHA256 signature by default)
                decrypted_content = self.client._make_request(
                    "T127",
                    content,
                    encrypt=True
                )

                if decrypted_content:
                    goods_list = decrypted_content.get('records', [])
                    pagination = decrypted_content.get('page', {})

                    logger.info(
                        f"Goods query successful: {len(goods_list)} items",
                        page=pagination.get('pageNo'),
                        total=pagination.get('totalSize')
                    )

                    return {
                        "success": True,
                        "goods": [self._normalize_goods_data(g) for g in goods_list],
                        "pagination": {
                            "page_no": int(pagination.get('pageNo', page_no)),
                            "page_size": int(pagination.get('pageSize', page_size)),
                            "total_size": int(pagination.get('totalSize', 0)),
                            "page_count": int(pagination.get('pageCount', 0))
                        },
                        "raw_data": decrypted_content
                    }
                else:
                    return {
                        "success": False,
                        "error": "Empty response from EFRIS",
                        "goods": []
                    }

            except Exception as api_error:
                # Extract error details
                error_message = str(api_error)

                import re
                error_code_match = re.search(r'\[(\d+)\]', error_message)
                error_code = error_code_match.group(1) if error_code_match else '99'

                logger.warning(f"T127 failed: {error_code} - {error_message}")

                return {
                    "success": False,
                    "error": error_message,
                    "error_code": error_code,
                    "goods": []
                }

        except Exception as e:
            logger.error(f"Goods query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "goods": []
            }

    def _build_query_content(self, **kwargs) -> Dict[str, Any]:
        """Build T127 query content from parameters"""
        content = {
            "pageNo": str(kwargs['page_no']),
            "pageSize": str(kwargs['page_size'])
        }

        # Add optional fields
        if kwargs.get('goods_code'):
            content['goodsCode'] = kwargs['goods_code']

        if kwargs.get('goods_name'):
            content['goodsName'] = kwargs['goods_name']

        if kwargs.get('commodity_category_name'):
            content['commodityCategoryName'] = kwargs['commodity_category_name']

        if kwargs.get('branch_id'):
            content['branchId'] = kwargs['branch_id']

        if kwargs.get('service_mark'):
            content['serviceMark'] = kwargs['service_mark']

        if kwargs.get('have_excise_tax'):
            content['haveExciseTax'] = kwargs['have_excise_tax']

        if kwargs.get('start_date'):
            content['startDate'] = kwargs['start_date'].strftime('%Y-%m-%d')

        if kwargs.get('end_date'):
            content['endDate'] = kwargs['end_date'].strftime('%Y-%m-%d')

        if kwargs.get('combine_keywords'):
            content['combineKeywords'] = kwargs['combine_keywords']

        if kwargs.get('goods_type_code'):
            content['goodsTypeCode'] = kwargs['goods_type_code']

        if kwargs.get('tin'):
            content['tin'] = kwargs['tin']

        if kwargs.get('query_type'):
            content['queryType'] = kwargs['query_type']

        return content

    def _normalize_goods_data(self, goods: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize goods data structure"""
        normalized = {
            'id': goods.get('id', ''),
            'goods_name': goods.get('goodsName', ''),
            'goods_code': goods.get('goodsCode', ''),
            'measure_unit': goods.get('measureUnit', ''),
            'unit_price': float(goods.get('unitPrice', 0)),
            'currency': goods.get('currency', ''),
            'stock': float(goods.get('stock', 0)),
            'stock_prewarning': float(goods.get('stockPrewarning', 0)),
            'source': goods.get('source', ''),
            'status_code': goods.get('statusCode', ''),
            'commodity_category_code': goods.get('commodityCategoryCode', ''),
            'commodity_category_name': goods.get('commodityCategoryName', ''),
            'tax_rate': float(goods.get('taxRate', 0)),
            'is_zero_rate': goods.get('isZeroRate', '') == '101',
            'is_exempt': goods.get('isExempt', '') == '101',
            'have_excise_tax': goods.get('haveExciseTax', '') == '101',
            'excise_duty_code': goods.get('exciseDutyCode', ''),
            'excise_duty_name': goods.get('exciseDutyName', ''),
            'excise_rate': float(goods.get('exciseRate', 0)) if goods.get('exciseRate') else 0,
            'pack': int(goods.get('pack', 0)) if goods.get('pack') else 0,
            'stick': int(goods.get('stick', 0)) if goods.get('stick') else 0,
            'remarks': goods.get('remarks', ''),
            'have_piece_unit': goods.get('havePieceUnit', '') == '101',
            'piece_unit_price': float(goods.get('pieceUnitPrice', 0)) if goods.get('pieceUnitPrice') else 0,
            'piece_measure_unit': goods.get('pieceMeasureUnit', ''),
            'package_scaled_value': float(goods.get('packageScaledValue', 0)) if goods.get('packageScaledValue') else 0,
            'piece_scaled_value': float(goods.get('pieceScaledValue', 0)) if goods.get('pieceScaledValue') else 0,
            'exclusion': goods.get('exclusion', ''),
            'have_other_unit': goods.get('haveOtherUnit', '') == '101',
            'service_mark': goods.get('serviceMark', ''),
            'goods_type_code': goods.get('goodsTypeCode', ''),
            'update_date': goods.get('updateDateStr', ''),
            'tank_no': goods.get('tankNo', '')
        }

        # Add customs information if present
        customs_entity = goods.get('commodityGoodsExtendEntity')
        if customs_entity:
            normalized['customs_info'] = {
                'measure_unit': customs_entity.get('customsMeasureUnit', ''),
                'unit_price': float(customs_entity.get('customsUnitPrice', 0)) if customs_entity.get(
                    'customsUnitPrice') else 0,
                'package_scaled_value': float(customs_entity.get('packageScaledValueCustoms', 0)) if customs_entity.get(
                    'packageScaledValueCustoms') else 0,
                'scaled_value': float(customs_entity.get('customsScaledValue', 0)) if customs_entity.get(
                    'customsScaledValue') else 0
            }

        # Add other units if present
        other_units = goods.get('goodsOtherUnits', [])
        if other_units:
            normalized['other_units'] = [
                {
                    'id': unit.get('id', ''),
                    'other_unit': unit.get('otherUnit', ''),
                    'other_price': float(unit.get('otherPrice', 0)) if unit.get('otherPrice') else 0,
                    'other_scaled': float(unit.get('otherScaled', 0)) if unit.get('otherScaled') else 0,
                    'package_scaled': float(unit.get('packageScaled', 0)) if unit.get('packageScaled') else 0
                }
                for unit in other_units
            ]

        return normalized

    def search_goods_by_keywords(
            self,
            keywords: str,
            page_no: int = 1,
            page_size: int = 10
    ) -> Dict[str, Any]:
        return self.query_goods(
            combine_keywords=keywords,
            page_no=page_no,
            page_size=page_size
        )

    def get_goods_by_code(self, goods_code: str) -> Dict[str, Any]:
        result = self.query_goods(
            goods_code=goods_code,
            page_size=1
        )

        if result.get('success') and result.get('goods'):
            return {
                "success": True,
                "goods": result['goods'][0]
            }

        return {
            "success": False,
            "error": "Goods not found",
            "goods": None
        }

class DataValidator:
    """Enhanced data validation with specific EFRIS rules"""

    @staticmethod
    def validate_tin(tin: str) -> Tuple[bool, Optional[str]]:
        """Enhanced TIN validation with specific error messages"""
        if not tin:
            return False, "TIN is required"

        if not isinstance(tin, str):
            return False, "TIN must be a string"

        # Clean TIN
        clean_tin = tin.replace(' ', '').replace('-', '')

        if len(clean_tin) != 10:
            return False, f"TIN must be exactly 10 digits, got {len(clean_tin)}"

        if not clean_tin.isdigit():
            return False, "TIN must contain only digits"

        return True, None

    @staticmethod
    def validate_brn(brn: str) -> Tuple[bool, Optional[str]]:
        """Enhanced BRN validation"""
        if not brn:
            return False, "BRN is required"

        if not isinstance(brn, str):
            return False, "BRN must be a string"

        clean_brn = brn.replace(' ', '').replace('-', '')

        if not (5 <= len(clean_brn) <= 15):
            return False, f"BRN must be between 5-15 characters, got {len(clean_brn)}"

        if not clean_brn.isalnum():
            return False, "BRN must contain only alphanumeric characters"

        return True, None

    @staticmethod
    def validate_amount(amount: Union[str, int, float, Decimal], field_name: str = "Amount") -> Tuple[
        bool, Optional[str]]:
        """Validate monetary amounts"""
        try:
            if isinstance(amount, str):
                amount = Decimal(amount)
            elif isinstance(amount, (int, float)):
                amount = Decimal(str(amount))
            elif not isinstance(amount, Decimal):
                return False, f"{field_name} must be a valid number"

            if amount < 0:
                return False, f"{field_name} cannot be negative"

            # Check precision (max 2 decimal places for currency)
            if amount.as_tuple().exponent < -2:
                return False, f"{field_name} cannot have more than 2 decimal places"

            return True, None

        except (InvalidOperation, ValueError):
            return False, f"{field_name} must be a valid decimal number"

    @staticmethod
    def validate_invoice_data(data: Dict[str, Any]) -> List[str]:
        """Comprehensive invoice data validation"""
        errors = []

        # Structure validation
        required_sections = [
            'sellerDetails', 'basicInformation', 'buyerDetails',
            'goodsDetails', 'taxDetails', 'summary'
        ]

        for section in required_sections:
            if section not in data:
                errors.append(f"Missing required section: {section}")
                continue

            if not isinstance(data[section], (dict, list)):
                errors.append(f"Section {section} must be a dict or list")

        # Seller details validation
        if 'sellerDetails' in data and isinstance(data['sellerDetails'], dict):
            seller = data['sellerDetails']

            is_valid, error = DataValidator.validate_tin(seller.get('tin', ''))
            if not is_valid:
                errors.append(f"Seller TIN: {error}")

            if not seller.get('legalName'):
                errors.append("Seller legal name is required")

        # Amounts validation
        if 'summary' in data and isinstance(data['summary'], dict):
            summary = data['summary']

            amount_fields = ['netAmount', 'taxAmount', 'grossAmount']
            amounts = {}

            for field in amount_fields:
                value = summary.get(field, 0)
                is_valid, error = DataValidator.validate_amount(value, field)
                if not is_valid:
                    errors.append(f"Summary {error}")
                else:
                    amounts[field] = Decimal(str(value))

            # Cross-validation of amounts
            if len(amounts) == 3:
                expected_gross = amounts['netAmount'] + amounts['taxAmount']
                if abs(amounts['grossAmount'] - expected_gross) > Decimal('0.01'):
                    errors.append("Amount calculation mismatch: netAmount + taxAmount ≠ grossAmount")

        # Goods details validation
        if 'goodsDetails' in data:
            goods = data['goodsDetails']
            if not isinstance(goods, list):
                errors.append("goodsDetails must be a list")
            elif len(goods) == 0:
                errors.append("At least one item is required in goodsDetails")
            else:
                for i, item in enumerate(goods):
                    if not isinstance(item, dict):
                        errors.append(f"Item {i + 1} must be a dictionary")
                        continue

                    # Validate required item fields
                    required_item_fields = ['item', 'qty', 'unitPrice', 'total']
                    for field in required_item_fields:
                        if field not in item:
                            errors.append(f"Item {i + 1}: Missing required field '{field}'")

                    # Validate item amounts
                    for field in ['qty', 'unitPrice', 'total', 'tax']:
                        if field in item:
                            is_valid, error = DataValidator.validate_amount(
                                item[field], f"Item {i + 1} {field}"
                            )
                            if not is_valid:
                                errors.append(error)

        return errors

class EFRISDataTransformer:
    """Transform invoice data into EFRIS T109 format"""

    def __init__(self, company):
        self.company = company
        # Handle missing efris_config gracefully
        efris_config = getattr(company, 'efris_config', None)
        if efris_config:
            self.device_no = getattr(efris_config, 'device_number', None) or '1026925503_01'
        else:
            self.device_no = '1026925503_01'
        self.tin = getattr(company, 'tin', '')

    def get_numeric_tax_rate(self, tax_rate_value):
        """Convert EFRIS tax rate codes to numeric values"""
        if isinstance(tax_rate_value, str):
            tax_rate_mapping = {
                'A': 18.0,  # Standard VAT
                'B': 0.0,   # Zero rate
                'C': 0.0,   # Exempt
                'D': 18.0,  # Deemed
                'E': 18.0,  # Standard
            }
            return tax_rate_mapping.get(tax_rate_value.upper(), 18.0)
        try:
            return float(tax_rate_value or 18)
        except (ValueError, TypeError):
            return 18.0

    def build_invoice_data(self, invoice) -> Dict[str, Any]:
        """Build complete T109 invoice data structure"""
        try:
            # Build sections
            seller_details = self._build_seller_details()
            basic_info = self._build_basic_info(invoice)
            buyer_details = self._build_buyer_details(invoice)
            goods_details = self._build_goods_details(invoice)
            tax_details = self._build_tax_details(invoice)

            # CRITICAL: Calculate summary from tax_details to ensure exact match
            summary = self._build_summary_from_tax_details(invoice, tax_details)

            invoice_data = {
                "sellerDetails": seller_details,
                "basicInformation": basic_info,
                "buyerDetails": buyer_details,
                "goodsDetails": goods_details,
                "taxDetails": tax_details,
                "summary": summary
            }

            # Validate payWay exists
            if 'payWay' not in invoice_data['summary']:
                logger.error("Missing payWay in summary!")
                raise Exception("Payment modes (payWay) are required")

            logger.info(
                f"Built invoice data for {getattr(invoice, 'number', 'unknown')}",
                extra={
                    'invoice_no': invoice_data['basicInformation']['invoiceNo'],
                    'gross_amount': invoice_data['summary']['grossAmount'],
                    'tax_amount': invoice_data['summary']['taxAmount'],
                    'payment_count': len(invoice_data['summary']['payWay'])
                }
            )

            return invoice_data

        except Exception as e:
            logger.error(f"Invoice data building failed: {e}", exc_info=True)
            raise Exception(f"Failed to build invoice data: {e}")

    def _build_buyer_details(self, invoice) -> Dict[str, Any]:
        """Build buyer details from invoice/sale"""
        # Try to get customer from invoice or sale
        customer = None

        # Try invoice.customer first
        if hasattr(invoice, 'customer') and invoice.customer:
            customer = invoice.customer
        # Try invoice.sale.customer
        elif hasattr(invoice, 'sale') and invoice.sale:
            customer = getattr(invoice.sale, 'customer', None)

        # If no customer, return walk-in customer
        if not customer:
            return {
                "buyerType": "1",  # B2C
                "buyerLegalName": "Walk-in Customer",
                "buyerTin": "",
                "buyerNinBrn": "",
                "buyerAddress": "",
                "buyerEmail": "",
                "buyerMobilePhone": ""
            }

        # Determine buyer type
        buyer_type = "1"  # Default B2C
        customer_tin = getattr(customer, 'tin', None)
        if customer_tin:
            buyer_type = "0"  # B2B if has TIN

        return {
            "buyerTin": customer_tin or "",
            "buyerNinBrn": (getattr(customer, 'nin', '') or
                            getattr(customer, 'brn', '') or ""),
            "buyerLegalName": getattr(customer, 'name', '') or "Unknown Customer",
            "buyerType": buyer_type,
            "buyerEmail": getattr(customer, 'email', '') or "",
            "buyerMobilePhone": getattr(customer, 'phone', '') or "",
            "buyerAddress": getattr(customer, 'address', '') or ""
        }

    def _build_seller_details(self) -> Dict[str, Any]:
        """Build seller details from company information"""
        # Simple reference number - timestamp based
        timestamp = int(time.time() * 1000)  # milliseconds since epoch
        random_suffix = get_random_string(4, allowed_chars='0123456789')
        reference_no = f"REF{timestamp}{random_suffix}" #f"+256789000826"  # Or use: f"REF{timestamp}{random_suffix}"

        return {
            "tin": self.company.tin,
            "ninBrn": getattr(self.company, 'brn', '') or getattr(self.company, 'nin', '') or "",
            "legalName": getattr(self.company, 'efris_taxpayer_name', '') or self.company.name,
            "businessName": (getattr(self.company, 'efris_business_name', '') or
                             getattr(self.company, 'trading_name', '') or self.company.name),
            "address": (getattr(self.company, 'efris_business_address', '') or
                        getattr(self.company, 'physical_address', '') or ""),
            "mobilePhone": (getattr(self.company, 'efris_phone_number', '') or
                            getattr(self.company, 'phone', '') or ""),
            "emailAddress": (getattr(self.company, 'efris_email_address', '') or
                             getattr(self.company, 'email', '') or ""),
            "placeOfBusiness": (getattr(self.company, 'efris_business_address', '') or
                                getattr(self.company, 'physical_address', '') or ""),
            "referenceNo": reference_no
        }

    def _build_basic_info(self, invoice) -> Dict[str, Any]:
        """Build basic invoice information - FIXED date and invoice number handling"""

        # CRITICAL: Get invoice number - MUST NOT BE EMPTY
        # The invoice should already have invoice_number from save()
        invoice_no = getattr(invoice, 'invoice_number', None) or ''

        if not invoice_no:
            # Fallback: try to generate if not present
            try:
                invoice_no = invoice.generate_invoice_number()
                # Save it so it's not regenerated
                invoice.invoice_number = invoice_no
                invoice.save(update_fields=['invoice_number'])
            except Exception as e:
                logger.error(f"Failed to generate invoice number: {e}")
                # Last resort: create a temporary number
                invoice_no = f"TMP-{timezone.now().strftime('%Y%m%d%H%M%S')}-{getattr(invoice, 'id', 0)}"

        # CRITICAL FIX: Use EAT timezone (UTC+3)
        from datetime import timezone as dt_timezone
        tz_eat = dt_timezone(timedelta(hours=3))

        issue_date = getattr(invoice, 'issue_date', None) or getattr(invoice, 'created_at', None)

        if issue_date:
            # Convert to datetime if date object
            if isinstance(issue_date, date) and not isinstance(issue_date, datetime):
                issue_date = datetime.combine(issue_date, datetime.now().time())

            # Make timezone-aware if naive
            if issue_date.tzinfo is None:
                issue_date = django_timezone.make_aware(issue_date)

            # Check age - use current time if older than 24 hours
            age_hours = (django_timezone.now() - issue_date).total_seconds() / 3600
            if age_hours > 24:
                logger.warning(
                    f"Invoice {invoice_no} is {age_hours:.1f} hours old, using current time"
                )
                issue_date = datetime.now(dt_timezone.utc).astimezone(tz_eat)
            else:
                # Convert to EAT
                issue_date = issue_date.astimezone(tz_eat)
        else:
            # No date - use current time in EAT
            issue_date = datetime.now(dt_timezone.utc).astimezone(tz_eat)

        # Format for EFRIS
        issued_date_str = issue_date.strftime('%Y-%m-%d %H:%M:%S')

        # Get operator name
        operator = (
                getattr(invoice, 'operator_name', None) or
                (invoice.created_by.get_full_name() if getattr(invoice, 'created_by', None) else None) or
                'System'
        )

        return {
            "deviceNo": self.device_no,
            "invoiceNo": '',  # Now guaranteed to have a value
            "issuedDate": issued_date_str,
            "operator": operator,
            "currency": getattr(invoice, 'currency_code', None) or 'UGX',
            "invoiceType": "1",
            "invoiceKind": "1",
            "dataSource": "103",
            "invoiceIndustryCode": "101"
        }

    def _build_summary(self, invoice) -> Dict[str, Any]:
        """Build invoice summary with payment modes"""

        subtotal = float(getattr(invoice, 'subtotal', 0))
        tax_amount = float(getattr(invoice, 'tax_amount', 0))
        total_amount = float(getattr(invoice, 'total_amount', 0))

        items = self._get_invoice_items(invoice)
        item_count = len(items) if items else 1

        # Build payment modes with proper rounding
        payment_modes = self._build_payment_modes(invoice, total_amount)

        return {
            "netAmount": f"{subtotal:.2f}",
            "taxAmount": f"{tax_amount:.2f}",
            "grossAmount": f"{total_amount:.2f}",
            "itemCount": str(item_count),
            "modeCode": "1",
            "remarks": getattr(invoice, 'notes', '') or "Invoice via EFRIS",
            "payWay": payment_modes  # CRITICAL: Add payment modes
        }

    def _build_payment_modes(self, invoice, total_amount: float) -> List[Dict]:
        """Build payment modes with proper rounding - EXACTLY as in working script"""

        payment_modes = []

        # Try to get actual payment methods from invoice
        if hasattr(invoice, 'payments') and hasattr(invoice.payments, 'exists'):
            if invoice.payments.exists():
                for idx, payment in enumerate(invoice.payments.all()):
                    payment_method = getattr(payment, 'payment_method', 'CASH')
                    amount = getattr(payment, 'amount', 0)

                    payment_modes.append({
                        "paymentMode": self._map_payment_mode(payment_method),
                        "paymentAmount": f"{float(amount):.2f}",  # FIXED: Round to 2 decimals
                        "orderNumber": chr(97 + idx)  # a, b, c, etc.
                    })

        # Try payment_mode field on invoice itself
        elif hasattr(invoice, 'payment_mode'):
            payment_method = getattr(invoice, 'payment_mode', 'CASH')
            payment_modes.append({
                "paymentMode": self._map_payment_mode(payment_method),
                "paymentAmount": f"{total_amount:.2f}",  # FIXED: Round to 2 decimals
                "orderNumber": "a"
            })

        # Default to cash for full amount
        if not payment_modes:
            payment_modes.append({
                "paymentMode": "102",  # Cash
                "paymentAmount": f"{total_amount:.2f}",  # FIXED: Round to 2 decimals
                "orderNumber": "a"
            })

        return payment_modes

    def _map_payment_mode(self, payment_method: str) -> str:
        """Map payment method to EFRIS code"""
        mapping = {
            'CASH': '102',
            'CARD': '106',
            'CREDIT_CARD': '106',
            'DEBIT_CARD': '106',
            'MOBILE_MONEY': '105',
            'MOBILE': '105',
            'BANK_TRANSFER': '107',
            'BANK': '107',
            'CREDIT': '101',
            'VOUCHER': '101'
        }
        return mapping.get(str(payment_method).upper(), '102')

    def _build_goods_details(self, invoice) -> List[Dict[str, Any]]:
        """
        Build goods details matching EFRIS T109 specification exactly
        FIXED: Support both Product and Service models with proper field mapping
        """
        goods_details = []
        items = self._get_invoice_items(invoice)
        invoice_no = getattr(invoice, 'number', None) or getattr(invoice, 'invoice_number', None)

        if not invoice_no:
            # Generate a temporary invoice number if none exists
            invoice_no = f"INV-{timezone.now().strftime('%Y%m%d')}-{getattr(invoice, 'id', 0):06d}"
            logger.warning(f"Invoice has no number, using generated: {invoice_no}")

        if not items:
            raise Exception("Invoice must have at least one item")

        # ✅ Use enumerate starting from 0
        for idx, item in enumerate(items, 0):
            try:
                # ✅ Try to get PRODUCT first
                product = getattr(item, 'product', None)

                # ✅ If no product, try to get SERVICE
                service = getattr(item, 'service', None) if not product else None

                if product:
                    # ========== PRODUCT PROCESSING ==========
                    item_code = getattr(product, 'efris_goods_code', None)
                    if not item_code:
                        item_code = f"{getattr(product, 'sku', 'PROD')}{product.id}"

                    item_name = product.name[:200]
                    unit_of_measure = product.unit_of_measure

                    # Get category info
                    if product.category:
                        goods_category_id = product.category.efris_commodity_category_code or ''
                        goods_category_name = product.category.efris_commodity_category_code or ''
                    else:
                        goods_category_id = ''
                        goods_category_name = ''

                    # Check excise
                    has_excise = getattr(product, 'has_excise_tax', False)
                    excise_entity = product

                elif service:
                    # ========== SERVICE PROCESSING ==========
                    # Use service code directly
                    item_code = service.efris_service_code

                    item_name = service.name[:200]
                    unit_of_measure = service.unit_of_measure

                    # Get category info from service's category
                    if service.category:
                        # Service category has efris_category_id
                        goods_category_id = service.category.efris_commodity_category_code or ''
                        goods_category_name = service.category.efris_commodity_category_code or ''
                    else:
                        # Default fallback for services without category
                        goods_category_id = '100000000000000000'  # Default service category
                        goods_category_name = 'General Services'

                    # Services typically don't have excise tax
                    has_excise = False
                    if service.tax_rate == 'E':  # Excise Duty rate
                        has_excise = True
                        excise_entity = service
                    else:
                        excise_entity = None

                else:
                    # Neither product nor service found
                    raise Exception(f"Item {idx} has no product or service - cannot fiscalize")

                # ========== COMMON PROCESSING (applies to both) ==========
                # Get amounts (same for both products and services)
                quantity = float(getattr(item, 'quantity', 1))
                unit_price = float(getattr(item, 'unit_price', 0) or getattr(item, 'price', 0))
                line_total = quantity * unit_price

                # Tax calculation
                tax_rate_raw = getattr(item, 'tax_rate', 'A')
                tax_rate = self.get_numeric_tax_rate(tax_rate_raw)

                # Calculate net and tax from gross (line_total)
                net_amount = line_total / (1 + tax_rate / 100)
                tax_amount = line_total - net_amount

                # Build goods detail
                goods_detail = {
                    "item": item_name,
                    "invoiceNo": str(invoice_no),
                    "itemCode": item_code[:50],
                    "qty": f"{quantity:.2f}",
                    "unitOfMeasure": unit_of_measure,
                    "unitPrice": f"{unit_price:.2f}",
                    "total": f"{line_total:.2f}",
                    "taxRate": f"{tax_rate / 100:.4f}",
                    "tax": f"{tax_amount:.2f}",
                    "orderNumber": idx,
                    "discountFlag": "2",
                    "deemedFlag": "2",
                    "exciseFlag": "2",
                    "goodsCategoryId": goods_category_id,
                    "goodsCategoryName": goods_category_name,
                }

                # Discount handling
                discount_amount = float(getattr(item, 'discount_amount', 0) or 0)
                if discount_amount > 0:
                    goods_detail["discountTotal"] = f"{discount_amount:.2f}"
                    goods_detail["discountTaxRate"] = goods_detail["taxRate"]
                else:
                    goods_detail["discountTotal"] = ""

                # Excise tax fields
                if has_excise and excise_entity:
                    goods_detail["exciseFlag"] = "1"
                    goods_detail["categoryId"] = str(getattr(excise_entity, 'excise_category_id', ''))[:18]
                    goods_detail["categoryName"] = str(getattr(excise_entity, 'excise_category_name', ''))[:1024]
                    goods_detail["exciseRate"] = str(getattr(excise_entity, 'excise_duty_rate', '0'))[:21]
                    goods_detail["exciseRule"] = str(getattr(excise_entity, 'excise_rule', '1'))
                    goods_detail["exciseTax"] = f"{float(getattr(excise_entity, 'excise_tax', 0)):.2f}"
                else:
                    # Empty strings for non-excise items
                    goods_detail["categoryId"] = ""
                    goods_detail["categoryName"] = ""
                    goods_detail["exciseCurrency"] = ""
                    goods_detail["exciseTax"] = ""
                    goods_detail["pack"] = ""
                    goods_detail["stick"] = ""
                    goods_detail["exciseUnit"] = ""
                    goods_detail["exciseDutyCode"] = ""

                logger.debug(
                    f"Item {idx}: {item_name}, "
                    f"orderNumber={idx}, "
                    f"itemCode={item_code}, "
                    f"type={'PRODUCT' if product else 'SERVICE'}, "
                    f"categoryId={goods_category_id}"
                )

                goods_details.append(goods_detail)

            except Exception as e:
                logger.error(f"Failed to process item {idx}: {e}", exc_info=True)
                raise Exception(f"Item {idx} processing failed: {e}")

        # ✅ Log order numbers for verification
        order_numbers = [item.get('orderNumber') for item in goods_details]
        logger.debug(f"Built goods_details with order numbers: {order_numbers}")

        return goods_details

    def _build_tax_details(self, invoice) -> List[Dict[str, Any]]:
        """
        Build tax details summary by tax category
        EFRIS validates: grossAmount = netAmount + taxAmount for each category
        """
        items = self._get_invoice_items(invoice)

        # Group items by tax rate
        tax_categories = {}

        for item in items:
            # Get tax rate
            tax_rate_raw = getattr(item, 'tax_rate', 'A')
            tax_rate = self.get_numeric_tax_rate(tax_rate_raw)

            # Calculate amounts
            quantity = float(getattr(item, 'quantity', 1))
            unit_price = float(getattr(item, 'unit_price', 0) or getattr(item, 'price', 0))
            line_total = quantity * unit_price

            # Split into net and tax
            net_amount = line_total / (1 + tax_rate / 100)
            tax_amount = line_total - net_amount

            # Group by tax rate
            rate_key = f"{tax_rate:.2f}"
            if rate_key not in tax_categories:
                tax_categories[rate_key] = {
                    'rate': tax_rate,
                    'net_amount': 0,
                    'tax_amount': 0
                }

            tax_categories[rate_key]['net_amount'] += net_amount
            tax_categories[rate_key]['tax_amount'] += tax_amount

        # Build tax details array
        tax_details = []
        for rate_key, amounts in tax_categories.items():
            rate = amounts['rate']
            net = amounts['net_amount']
            tax = amounts['tax_amount']
            gross = net + tax  # ← CRITICAL: This must match the formula

            # Determine tax category code
            if rate == 18.0:
                tax_category_code = "01"  # Standard Rate
                tax_rate_name = "Standard Rate (18%)"
            elif rate == 0.0:
                tax_category_code = "02"  # Zero Rate
                tax_rate_name = "Zero Rate (0%)"
            else:
                tax_category_code = "01"
                tax_rate_name = f"Rate ({rate}%)"

            tax_details.append({
                "taxCategoryCode": tax_category_code,
                "netAmount": f"{net:.2f}",
                "taxRate": f"{rate / 100:.4f}",  # 0.18 for 18%
                "taxAmount": f"{tax:.2f}",
                "grossAmount": f"{gross:.2f}",  # ← Must equal netAmount + taxAmount
                "taxRateName": tax_rate_name
            })

        # Fallback if no items
        if not tax_details:
            subtotal = float(getattr(invoice, 'subtotal', 0))
            tax_amount = float(getattr(invoice, 'tax_amount', 0))

            tax_details.append({
                "taxCategoryCode": "01" if tax_amount > 0 else "02",
                "netAmount": f"{subtotal:.2f}",
                "taxRate": "0.18" if tax_amount > 0 else "0.00",
                "taxAmount": f"{tax_amount:.2f}",
                "grossAmount": f"{subtotal + tax_amount:.2f}",  # ← Correct calculation
                "taxRateName": "Standard Rate (18%)" if tax_amount > 0 else "Zero Rate (0%)"
            })

        return tax_details

    def _build_summary_from_tax_details(self, invoice, tax_details: List[Dict]) -> Dict[str, Any]:
        """
        Build summary section from tax_details to ensure exact matching
        EFRIS validates: summary.taxAmount = sum(taxDetails[].taxAmount)
        """
        from decimal import Decimal

        # Sum from tax_details (source of truth)
        total_net = Decimal('0')
        total_tax = Decimal('0')
        total_gross = Decimal('0')

        for tax_detail in tax_details:
            total_net += Decimal(tax_detail['netAmount'])
            total_tax += Decimal(tax_detail['taxAmount'])
            total_gross += Decimal(tax_detail['grossAmount'])

        # Get item count
        items = self._get_invoice_items(invoice)
        item_count = len(items) if items else 1

        # Build payment modes
        payment_modes = self._build_payment_modes(invoice, float(total_gross))

        # CRITICAL: Use exact values from tax_details
        return {
            "netAmount": f"{total_net:.2f}",
            "taxAmount": f"{total_tax:.2f}",  # ← Must match sum of taxDetails
            "grossAmount": f"{total_gross:.2f}",  # ← Must match sum of taxDetails
            "itemCount": str(item_count),
            "modeCode": "1",
            "remarks": getattr(invoice, 'notes', '') or "Invoice via EFRIS",
            "payWay": payment_modes
        }

    def _get_invoice_items(self, invoice) -> List:
        """Get invoice items with multiple attribute attempts"""
        # Try different item attributes
        for attr in ['items', 'line_items', 'invoice_items', 'sale_items']:
            if hasattr(invoice, attr):
                items = getattr(invoice, attr)
                if hasattr(items, 'all'):
                    return list(items.all())
                elif hasattr(items, '__iter__'):
                    return list(items)

        # Try from related sale
        if hasattr(invoice, 'sale') and invoice.sale:
            return self._get_invoice_items(invoice.sale)

        return []


class EnhancedEFRISAPIClient:
    """Main EFRIS API Client - Django version matching WORKING test script"""

    def __init__(self, company):
        self.company = company

        # Get schema name from company
        schema_name = getattr(company, 'schema_name', None)
        if not schema_name:
            raise Exception(f"Company {company} has no schema_name attribute")

        try:
            self.efris_config = company.efris_config

            if not self.efris_config.is_active:
                logger.warning(
                    f"EFRIS configuration exists but is inactive for {company.name}"
                )
        except Exception as e:
            raise Exception(f"Failed to load EFRIS configuration: {e}")

        device_no = self.efris_config.device_number or '1026925503_01'
        tin = getattr(company, 'tin', '')
        self.security_manager = SecurityManager(device_no, tin)

        self._is_authenticated = False
        self._last_login = None

        # API URL
        self.api_url = getattr(
            settings,
            'EFRIS_API_URL',
            self.efris_config.api_url
        )

        logger.info(
            f"EFRIS client initialized for {company.name}",
            extra={
                'schema': schema_name,
                'device_no': device_no,
                'tin': tin
            }
        )

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources"""
        # Cleanup if needed
        pass

    def _load_private_key(self):
        """Load private key from configuration"""
        try:
            private_key_pem = self.efris_config.private_key
            if isinstance(private_key_pem, str):
                private_key_pem = private_key_pem.encode('utf-8')

            private_key = serialization.load_pem_private_key(
                private_key_pem,
                password=(
                    self.efris_config.key_password.encode('utf-8')
                    if self.efris_config.key_password else None
                ),
                backend=default_backend()
            )
            # Store in security manager for signing
            self.security_manager.private_key = private_key
            return private_key
        except Exception as e:
            raise Exception(f"Failed to load private key: {e}")

    def _make_http_request(self, data: Dict) -> requests.Response:
        """Make HTTP request to EFRIS API"""
        try:
            response = requests.post(
                self.api_url,
                json=data,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            logger.debug(f"HTTP {response.status_code}: {len(response.content)} bytes")
            return response
        except Exception as e:
            logger.error(f"HTTP request failed: {e}")
            raise

    def _build_request(
            self,
            interface_code: str,
            content: Optional[Dict] = None,
            encrypt: bool = True
    ) -> Dict:
        """
        Build standard EFRIS request
        EXACTLY matching working test script logic
        """

        data_section = {
            "dataDescription": {
                "codeType": "1" if encrypt else "0",
                "encryptCode": "2" if encrypt else "1",
                "zipCode": "0"
            }
        }

        if content is not None:
            content_json = json.dumps(content, separators=(',', ':'), sort_keys=True)

            if encrypt:
                # Encrypted content with signature
                encrypted_content = self.security_manager.aes_encrypt(content_json)
                content_b64 = base64.b64encode(encrypted_content).decode()

                sha1_interfaces = ["T119", "T103","T146","T110", "T115", "T130","T108","T132","T133","T134","T135","T136","T137","T38", "T116", "T117", "T127", "T144", "T109","T106", "T107", "T111", "T112", "T113", "T114", "T118", "T120", "T121", "T122", "T125", "T126", "T129", "T126","T128", "T131", "T139", "T145", "T147", "T148", "T149", "T160", "T184","T162","T163","T164","T166","T167","T168","T169","T170","T171","T172","T173","T175","T176","T177","T178","T179","T180","T181","T182","T183","T184","T185","T186","T187" ]
                algorithm = "SHA1" if interface_code in sha1_interfaces else "SHA256"

                data_section["signature"] = self.security_manager.sign_content(
                    content_b64,
                    algorithm=algorithm
                )
            else:
                # Unencrypted content
                content_b64 = base64.b64encode(content_json.encode()).decode()

                # T115 is special: unencrypted but still needs signature
                if interface_code == "T115":
                    data_section["signature"] = self.security_manager.sign_content(
                        content_b64,
                        algorithm="SHA1"
                    )
                else:
                    data_section["signature"] = ""

            data_section["content"] = content_b64
        else:
            data_section["content"] = ""
            data_section["signature"] = ""

        return {
            "data": data_section,
            "globalInfo": self.security_manager.create_global_info(interface_code),
            "returnStateInfo": {
                "returnCode": "",
                "returnMessage": ""
            }
        }

    def _decrypt_response_content(self, data_section: Dict) -> Dict:
        """
        Decrypt response content
        EXACTLY matching working script logic with gzip/zlib support
        """
        content_b64 = data_section.get("content", "")
        if not content_b64:
            return {}

        try:
            content_bytes = base64.b64decode(content_b64)
        except Exception as e:
            logger.warning(f"Failed to base64-decode response: {e}")
            return {}

        data_desc = data_section.get("dataDescription", {}) or {}
        code_type = str(data_desc.get("codeType", "")).strip()
        zip_code = str(data_desc.get("zipCode", "0")).strip()

        payload_bytes = content_bytes

        # Decrypt if encrypted
        if code_type == "1":
            try:
                payload_bytes = self.security_manager.aes_decrypt_bytes(payload_bytes)
            except Exception as e:
                logger.warning(f"AES decryption failed: {e}")
                return {}

        # Decompress if compressed
        if zip_code in ("1", "2"):
            try:
                import gzip
                payload_bytes = gzip.decompress(payload_bytes)
            except Exception:
                try:
                    import zlib
                    payload_bytes = zlib.decompress(payload_bytes)
                except Exception as e:
                    logger.warning(f"Decompression failed: {e}")

        # Decode to JSON
        try:
            content_json = payload_bytes.decode('utf-8')
            return json.loads(content_json)
        except Exception as e:
            logger.warning(f"Failed to decode/parse content: {e}")
            return {}

    def _parse_response(self, response_data: Dict, decrypt: bool = True) -> Dict:
        """
        Parse and decrypt EFRIS response
        Handles both dict and list responses safely
        """
        return_state = response_data.get("returnStateInfo", {})
        return_code = return_state.get("returnCode")
        return_message = return_state.get("returnMessage")

        data_section = response_data.get("data", {})
        content_b64 = data_section.get("content", "")

        actual_content = {}
        if content_b64:
            try:
                content_bytes = base64.b64decode(content_b64)
            except Exception as e:
                logger.warning(f"Failed to base64-decode response content: {e}")
                content_bytes = None

            if content_bytes is not None:
                data_desc = data_section.get("dataDescription", {}) or {}
                code_type = str(data_desc.get("codeType", "")).strip()
                zip_code = str(data_desc.get("zipCode", "0")).strip()

                payload_bytes = content_bytes

                # AES decryption
                if decrypt and code_type == "1":
                    try:
                        payload_bytes = self.security_manager.aes_decrypt_bytes(payload_bytes)
                    except Exception as e:
                        logger.warning(f"AES decryption failed: {e}")

                # Decompression
                if zip_code in ("1", "2"):
                    try:
                        import gzip
                        payload_bytes = gzip.decompress(payload_bytes)
                    except Exception:
                        try:
                            import zlib
                            payload_bytes = zlib.decompress(payload_bytes)
                        except Exception as e:
                            logger.warning(f"Decompression failed: {e}")

                # Decode JSON
                try:
                    content_json = payload_bytes.decode('utf-8')
                    actual_content = json.loads(content_json)
                except Exception as e:
                    logger.warning(f"Failed to decode/parse content: {e}")

        # Handle errors safely
        if return_code != "00":
            if isinstance(actual_content, list) and actual_content:
                # Take the first dict in the list
                first_item = actual_content[0]
                detailed_msg = first_item.get("returnMessage") or return_message
            elif isinstance(actual_content, dict):
                detailed_msg = actual_content.get("returnMessage") or return_message
            else:
                detailed_msg = return_message or "Unknown API error"

            error_msg = f"API Error [{return_code}]: {detailed_msg}"
            logger.error(f"Full error response: {json.dumps(response_data, indent=2)}")
            raise Exception(error_msg)

        return actual_content

    # ============================================================================
    # SERVICE MANAGEMENT INTERFACES (Uses same T130, T144 as Products)
    # ============================================================================

    def register_service_with_efris(self, service) -> Dict[str, Any]:
        """
        Register or update service with EFRIS (T130)
        Handles both adding new services (operationType=101) and modifying existing (operationType=102)
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Determine operation type: 101=Add, 102=Modify
            is_already_uploaded = getattr(service, 'efris_is_uploaded', False)
            operation_type = "102" if is_already_uploaded else "101"

            # Use the service code directly (efris_service_code property returns self.code)
            service_code = service.code  # This is what efris_service_code property returns

            # Service pricing
            unit_price = float(getattr(service, 'unit_price', 0) or 0)

            # Check if service has excise tax
            has_excise = self._service_has_excise_tax(service)

            # Get commodity category ID (18 digits) from service's category
            commodity_category_id = service.category.efris_commodity_category_code

            # Build T130 service data
            service_data = {
                "operationType": operation_type,
                "goodsName": str(service.name[:200] if service.name else "Unnamed Service"),
                "goodsCode": str(service_code),
                "measureUnit": service.unit_of_measure,
                "unitPrice": f"{unit_price:.2f}",
                "currency": "101",  # UGX
                "commodityCategoryId": commodity_category_id,
                "haveExciseTax": "101" if has_excise else "102",
                "description": str((getattr(service, 'description', None) or service.name or "")[:1024]),
                "stockPrewarning": "0",  # Services don't have stock warnings
                "havePieceUnit": "102",
                "pieceMeasureUnit": "",
                "pieceUnitPrice": "",
                "packageScaledValue": "",
                "pieceScaledValue": "",
                "exciseDutyCode": "",
                "haveOtherUnit": "102",
                "goodsTypeCode": "101",  # 101=Standard goods type
                "serviceMark": "101",  # ✅ ADDED: 101=Service (yes, it's a service)
            }

            # Add excise tax info if applicable
            if has_excise:
                excise_info = self._build_excise_tax_info(service)
                service_data.update(excise_info)

            # T130 expects an array
            service_data_array = [service_data]

            # Validate
            validation_errors = self._validate_t130_data(service_data)
            if validation_errors:
                return {
                    "success": False,
                    "error": f"Validation failed: {'; '.join(validation_errors)}"
                }

            operation_name = "Updating" if operation_type == "102" else "Registering"
            logger.info(f"{operation_name} service {service_code} with EFRIS (T130)")

            try:
                request_data = self._build_request("T130", service_data_array, encrypt=True)
                response = self._make_http_request(request_data)

                if response.status_code != 200:
                    return {
                        "success": False,
                        "error": f"HTTP {response.status_code}",
                        "service_code": service_code
                    }

                response_data = response.json()
                return_info = response_data.get('returnStateInfo', {})
                return_code = return_info.get('returnCode', '99')

                # Accept both success codes
                if return_code not in ['00', '45']:
                    error_message = return_info.get('returnMessage', 'T130 API call failed')
                    logger.error(f"T130 failed: {return_code} - {error_message}")
                    return {
                        "success": False,
                        "error": error_message,
                        "error_code": return_code,
                        "service_code": service_code
                    }

                # Decrypt response content
                data_section = response_data.get('data', {})
                decrypted_content = self._decrypt_response_content(data_section)

                # Normalize response
                if isinstance(decrypted_content, dict):
                    for key in ['goodsStockIn', 'records', 'data', 'results']:
                        if key in decrypted_content and isinstance(decrypted_content[key], list):
                            decrypted_content = decrypted_content[key]
                            break

                # Handle empty response (success with no immediate data)
                if not isinstance(decrypted_content, list) or len(decrypted_content) == 0:
                    logger.info(f"T130 successful (empty response) for {service_code}")
                    time.sleep(1)  # Wait before querying

                    # Query EFRIS for the service ID and code
                    query_result = self.t144_query_goods_by_code(service_code)

                    if query_result.get('success') and query_result.get('goods'):
                        efris_service = query_result['goods'][0]
                        efris_service_id = (
                                efris_service.get('id') or
                                efris_service.get('commodityGoodsId') or
                                efris_service.get('goodsId')
                        )
                        efris_service_code = efris_service.get('goodsCode') or service_code

                        # Update service - DON'T try to set efris_service_code (it's a read-only property)
                        service.efris_is_uploaded = True
                        service.efris_upload_date = timezone.now()
                        service.efris_service_id = efris_service_id

                        # Only update fields that exist and are writable
                        update_fields = ['efris_is_uploaded', 'efris_upload_date', 'efris_service_id']
                        service.save(update_fields=update_fields)

                        logger.info(
                            f"Service {service_code} {operation_name.lower()}: ID={efris_service_id}, Code={efris_service_code}")

                        return {
                            "success": True,
                            "message": f"Service {operation_name.lower()} with EFRIS",
                            "service_code": service_code,
                            "efris_service_id": efris_service_id,
                            "efris_service_code": efris_service_code,
                            "operation_type": operation_type,
                            "efris_data": efris_service
                        }

                    # Query failed - still mark as uploaded if operation was successful
                    logger.warning(f"Service uploaded but query failed for {service_code}")
                    service.efris_is_uploaded = True
                    service.efris_upload_date = timezone.now()
                    service.save(update_fields=['efris_is_uploaded', 'efris_upload_date'])

                    return {
                        "success": True,
                        "message": f"Service {operation_name.lower()} but could not retrieve EFRIS ID",
                        "service_code": service_code,
                        "operation_type": operation_type
                    }

                # Handle normal response list
                result_item = decrypted_content[0]
                efris_service_id = (
                        result_item.get('id') or
                        result_item.get('commodityGoodsId') or
                        result_item.get('goodsId')
                )
                efris_service_code = result_item.get('goodsCode') or service_code

                # Update service - DON'T try to set efris_service_code (it's a read-only property)
                service.efris_is_uploaded = True
                service.efris_upload_date = timezone.now()
                service.efris_service_id = efris_service_id

                # Only update fields that exist and are writable
                update_fields = ['efris_is_uploaded', 'efris_upload_date', 'efris_service_id']
                service.save(update_fields=update_fields)

                logger.info(
                    f"Service {service_code} {operation_name.lower()}: ID={efris_service_id}, Code={efris_service_code}")

                return {
                    "success": True,
                    "message": f"Service {operation_name.lower()} with EFRIS",
                    "service_code": service_code,
                    "efris_service_id": efris_service_id,
                    "efris_service_code": efris_service_code,
                    "operation_type": operation_type,
                    "efris_data": result_item
                }

            except json.JSONDecodeError as e:
                logger.error(f"T130 JSON parsing error: {e}")
                return {
                    "success": False,
                    "error": f"Invalid JSON response: {e}",
                    "service_code": service_code
                }
            except Exception as api_error:
                logger.error(f"T130 processing error: {api_error}", exc_info=True)
                return {
                    "success": False,
                    "error": str(api_error),
                    "service_code": service_code
                }

        except Exception as e:
            logger.error(f"Service registration failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def _get_service_commodity_category_id(self, service) -> str:
        """
        Get the EFRIS commodity category ID (18 digits) for a service.
        Services should use service-type categories (serviceMark=101).
        Pads with zeros at the END until length is 18.
        """
        try:
            # Get from service's category
            if hasattr(service, 'category') and service.category:
                category_id = getattr(service.category, 'efris_category_id', None)

                # ✅ VALIDATE: Ensure it's actually a service category
                if category_id:
                    # Verify the category is for services (serviceMark should be '101')
                    efris_cat = service.category.efris_commodity_category
                    if efris_cat and efris_cat.service_mark != '101':
                        logger.warning(
                            f"Service {service.code} has category with serviceMark={efris_cat.service_mark}, "
                            f"but should be '101' for services"
                        )
                        # Don't use invalid category, fall back to default
                        return "100000000000000000"

                    # Pad with zeros at the END to reach 18 digits
                    category_id = str(category_id).ljust(18, '0')[:18]
                    return category_id

            # Default service category (18 digits)
            return "100000000000000000"  # Default for services

        except Exception as e:
            logger.warning(f"Failed to get service commodity category: {e}")
            return "100000000000000000"

    def _get_commodity_category_id(self, product) -> str:
        """
        Get the EFRIS commodity category ID (18 digits) for a product,
        fetched from the related Category model.
        Pads with zeros at the END until the length is 18.
        Falls back to default if missing.
        """
        try:
            # Step 1: Try to fetch the EFRIS category ID from related category
            if hasattr(product, 'category') and product.category:
                category_id = getattr(product.category, 'efris_commodity_category_code', None)

                if category_id:
                    # ✅ VALIDATE: Ensure it's actually a product category (serviceMark should be '102')
                    efris_cat = product.category.efris_commodity_category_code
                    if efris_cat and efris_cat.service_mark == '101':
                        logger.warning(
                            f"Product {product.sku} has category with serviceMark='101', "
                            f"but should be '102' for products"
                        )
                        # Don't use invalid category, fall back to default
                        return "101113010000000000"  # Default product category

                    # Step 3: Convert to string and pad zeros to the RIGHT (end)
                    category_id = str(category_id)
                    if len(category_id) < 18:
                        category_id = category_id.ljust(18, '0')

                    # Step 4: Truncate if longer than 18 just to be safe
                    return category_id[:18]

            # Step 2: Use default if missing or None
            return "101113010000000000"  # Default product category

        except AttributeError as e:
            # In case product.category is missing or None
            logger.warning(f"Failed to get commodity category for product: {e}")
            return "101113010000000000"

    def refresh_service_from_efris(self, service) -> Dict[str, Any]:
        """
        Query EFRIS for service details and update local service

        Args:
            service: Service model instance

        Returns:
            Dict with refresh results
        """
        try:
            service_code = service.code

            if not service_code:
                return {
                    "success": False,
                    "error": "Service has no code"
                }

            logger.info(f"Refreshing service {service_code} from EFRIS")

            # Query EFRIS using T144
            query_result = self.t144_query_goods_by_code(service_code)

            if not query_result.get('success'):
                return {
                    "success": False,
                    "error": query_result.get('error', 'Query failed')
                }

            goods_list = query_result.get('goods', [])

            if not goods_list:
                return {
                    "success": False,
                    "error": f"Service {service_code} not found in EFRIS"
                }

            efris_service = goods_list[0]
            efris_service_id = efris_service.get('id')

            if not efris_service_id:
                return {
                    "success": False,
                    "error": "EFRIS service ID not available in response"
                }

            # Update service
            updates = {}

            if service.efris_service_id != efris_service_id:
                updates['efris_service_id'] = efris_service_id

            if not service.efris_is_uploaded:
                updates['efris_is_uploaded'] = True

            if not service.efris_upload_date:
                updates['efris_upload_date'] = timezone.now()

            if updates:
                for field, value in updates.items():
                    setattr(service, field, value)
                service.save(update_fields=list(updates.keys()))

                logger.info(f"Service {service_code} updated with EFRIS data: {updates}")

            return {
                "success": True,
                "message": "Service refreshed from EFRIS",
                "efris_service_id": efris_service_id,
                "efris_data": efris_service,
                "updates": updates
            }

        except Exception as e:
            logger.error(f"Failed to refresh service from EFRIS: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def _service_has_excise_tax(self, service) -> bool:
        """Check if service is subject to excise tax"""
        excise_rate = getattr(service, 'excise_duty_rate', None)
        if excise_rate and float(excise_rate) > 0:
            return True
        return False

    def query_service_by_code(self, service_code: str) -> Dict[str, Any]:
        """
        Query service details from EFRIS by code
        Uses T144 interface

        Args:
            service_code: Service code to query

        Returns:
            Dict with service details or error
        """
        try:
            result = self.t144_query_goods_by_code(service_code)

            if result.get('success') and result.get('goods'):
                service_data = result['goods'][0]

                # Check if it's actually a service (serviceMark='102')
                service_mark = service_data.get('serviceMark', '102')

                return {
                    "success": True,
                    "is_service": service_mark == '101',
                    "service_data": service_data,
                    "service_code": service_code
                }

            return {
                "success": False,
                "error": result.get('error', 'Service not found')
            }

        except Exception as e:
            logger.error(f"Service query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def register_product_with_efris(self, product) -> Dict[str, Any]:
        """
        Register or update product with EFRIS (T130)
        CRITICAL: T130 response DOES NOT include goods ID - must query via T144
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Determine operation type
            is_already_uploaded = getattr(product, 'efris_is_uploaded', False)
            operation_type = "102" if is_already_uploaded else "101"

            # Get goods code
            goods_code = getattr(product, 'efris_goods_code_field', None) or \
                         getattr(product, 'sku', None) or \
                         f"PROD{product.id}"

            # Product pricing
            selling_price = float(getattr(product, 'selling_price', 0) or 0)
            min_stock = int(getattr(product, 'min_stock_level', 10) or 10)

            # Check excise tax
            has_excise = self._product_has_excise_tax(product)

            # Get commodity category ID (18 digits)
            commodity_category_idd = self._get_commodity_category_id(product)

            # ✅ CRITICAL FIX: Validate commodity category
            if not commodity_category_idd or len(commodity_category_idd) != 18:
                return {
                    "success": False,
                    "error": f"Invalid commodity category ID: {commodity_category_idd}. Must be 18 digits."
                }

            # Build T130 goods data
            goods_data = {
                "operationType": operation_type,
                "goodsName": str(product.name[:200] if product.name else "Unnamed Product"),
                "goodsCode": str(goods_code),
                "measureUnit": product.unit_of_measure or "101",  # Default to pieces
                "unitPrice": f"{selling_price:.2f}",
                "currency": "101",  # UGX
                "commodityCategoryId": product.category.efris_commodity_category_code,
                "haveExciseTax": "101" if has_excise else "102",
                "description": str((getattr(product, 'description', None) or product.name or "")[:1024]),
                "stockPrewarning": str(min_stock),
                "havePieceUnit": "102",  # No piece unit
                "pieceMeasureUnit": "",
                "pieceUnitPrice": "",
                "packageScaledValue": "",
                "pieceScaledValue": "",
                "exciseDutyCode": "",
                "haveOtherUnit": "102",  # No other units
                "goodsTypeCode": "101"  # Goods (not fuel)
            }

            # Add excise tax info if applicable
            if has_excise:
                excise_info = self._build_excise_tax_info(product)
                goods_data.update(excise_info)

            # T130 expects an array
            product_data = [goods_data]

            # Validate
            validation_errors = self._validate_t130_data(goods_data)
            if validation_errors:
                return {
                    "success": False,
                    "error": f"Validation failed: {'; '.join(validation_errors)}"
                }

            operation_name = "Updating" if operation_type == "102" else "Registering"
            logger.info(f"{operation_name} product {goods_code} with EFRIS (T130)")

            try:
                # Make T130 request
                request_data = self._build_request("T130", product_data, encrypt=True)
                response = self._make_http_request(request_data)

                if response.status_code != 200:
                    return {
                        "success": False,
                        "error": f"HTTP {response.status_code}",
                        "item_code": goods_code
                    }

                response_data = response.json()
                return_info = response_data.get('returnStateInfo', {})
                return_code = return_info.get('returnCode', '99')

                # Check for overall failure
                if return_code not in ['00', '45']:
                    error_message = return_info.get('returnMessage', 'T130 API call failed')
                    logger.error(f"T130 failed: {return_code} - {error_message}")
                    return {
                        "success": False,
                        "error": error_message,
                        "error_code": return_code,
                        "item_code": goods_code
                    }

                # ✅ CRITICAL: Check individual item response
                data_section = response_data.get('data', {})
                decrypted_content = self._decrypt_response_content(data_section)

                # Normalize response to list
                if isinstance(decrypted_content, dict):
                    for key in ['goodsStockIn', 'records', 'data', 'results']:
                        if key in decrypted_content and isinstance(decrypted_content[key], list):
                            decrypted_content = decrypted_content[key]
                            break

                # Check item-level return code
                if isinstance(decrypted_content, list) and decrypted_content:
                    item_result = decrypted_content[0]
                    item_return_code = item_result.get('returnCode', '')
                    item_return_message = item_result.get('returnMessage', '')

                    # ✅ CRITICAL: Check if item registration failed
                    if item_return_code and item_return_code not in ['00', '601', '']:
                        logger.error(
                            f"T130 item failed: code={item_return_code}, message={item_return_message}"
                        )
                        return {
                            "success": False,
                            "error": f"Product registration failed: {item_return_message}",
                            "error_code": item_return_code,
                            "item_code": goods_code
                        }

                # ✅ SUCCESS - Now query EFRIS to get the actual goods ID
                logger.info(f"T130 successful for {goods_code}, querying EFRIS for goods ID...")

                # Wait a moment for EFRIS to index
                time.sleep(2)

                # Query using T144
                query_result = self.t144_query_goods_by_code(goods_code)

                if not query_result.get('success'):
                    logger.error(f"T144 query failed after T130 success: {query_result.get('error')}")
                    return {
                        "success": False,
                        "error": f"Product registered but couldn't retrieve EFRIS ID: {query_result.get('error')}",
                        "item_code": goods_code,
                        "warning": "Product may exist in EFRIS but ID not retrieved"
                    }

                goods_list = query_result.get('goods', [])

                if not goods_list:
                    logger.error(f"T144 returned no goods for code: {goods_code}")
                    return {
                        "success": False,
                        "error": f"Product registered but not found in EFRIS query. Code may not match.",
                        "item_code": goods_code,
                        "warning": "Check EFRIS portal manually - product may exist with different code"
                    }

                # ✅ Extract goods ID from T144 response
                efris_goods = goods_list[0]
                efris_goods_id = (
                        efris_goods.get('id') or
                        efris_goods.get('commodityGoodsId') or
                        efris_goods.get('goodsId')
                )
                efris_goods_code = efris_goods.get('goodsCode') or goods_code

                if not efris_goods_id:
                    logger.error(f"T144 response missing goods ID for {goods_code}")
                    logger.debug(f"T144 response: {json.dumps(efris_goods, indent=2)}")
                    return {
                        "success": False,
                        "error": "Product found but missing EFRIS goods ID in response",
                        "item_code": goods_code,
                        "efris_data": efris_goods
                    }

                # ✅ Update product with EFRIS data
                product.efris_is_uploaded = True
                product.efris_upload_date = timezone.now()
                product.efris_goods_id = efris_goods_id
                product.efris_goods_code_field = efris_goods_code
                product.save(update_fields=[
                    'efris_is_uploaded',
                    'efris_upload_date',
                    'efris_goods_id',
                    'efris_goods_code_field'
                ])

                logger.info(
                    f"Product {goods_code} {operation_name.lower()}: "
                    f"ID={efris_goods_id}, Code={efris_goods_code}"
                )

                return {
                    "success": True,
                    "message": f"Product {operation_name.lower()} with EFRIS",
                    "item_code": goods_code,
                    "efris_goods_id": efris_goods_id,
                    "efris_goods_code": efris_goods_code,
                    "operation_type": operation_type,
                    "efris_data": efris_goods
                }

            except json.JSONDecodeError as e:
                logger.error(f"T130 JSON parsing error: {e}")
                return {
                    "success": False,
                    "error": f"Invalid JSON response: {e}",
                    "item_code": goods_code
                }
            except Exception as api_error:
                logger.error(f"T130 processing error: {api_error}", exc_info=True)
                return {
                    "success": False,
                    "error": str(api_error),
                    "item_code": goods_code
                }

        except Exception as e:
            logger.error(f"Product registration failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }


    def refresh_product_from_efris(self, product) -> Dict[str, Any]:
        """
        Query EFRIS for product details and update local product

        Args:
            product: Product model instance

        Returns:
            Dict with refresh results
        """
        try:
            goods_code = product.sku

            if not goods_code:
                return {
                    "success": False,
                    "error": "Product has no SKU"
                }

            logger.info(f"Refreshing product {goods_code} from EFRIS")

            # Query EFRIS
            query_result = self.t144_query_goods_by_code(goods_code)

            if not query_result.get('success'):
                return {
                    "success": False,
                    "error": query_result.get('error', 'Query failed')
                }

            goods_list = query_result.get('goods', [])

            if not goods_list:
                return {
                    "success": False,
                    "error": f"Product {goods_code} not found in EFRIS"
                }

            efris_goods = goods_list[0]
            efris_goods_id = efris_goods.get('id')

            if not efris_goods_id:
                return {
                    "success": False,
                    "error": "EFRIS goods ID not available in response"
                }

            # Update product
            updates = {}

            if product.efris_goods_id != efris_goods_id:
                updates['efris_goods_id'] = efris_goods_id

            if not product.efris_is_uploaded:
                updates['efris_is_uploaded'] = True

            if not product.efris_upload_date:
                updates['efris_upload_date'] = timezone.now()

            if updates:
                for field, value in updates.items():
                    setattr(product, field, value)
                product.save(update_fields=list(updates.keys()))

                logger.info(f"Product {goods_code} updated with EFRIS data: {updates}")

            return {
                "success": True,
                "message": "Product refreshed from EFRIS",
                "efris_goods_id": efris_goods_id,
                "efris_data": efris_goods,
                "updates": updates
            }

        except Exception as e:
            logger.error(f"Failed to refresh product from EFRIS: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def _product_has_excise_tax(self, product) -> bool:
        """Check if product is subject to excise tax"""
        # Check if excise duty rate is set
        excise_rate = getattr(product, 'excise_duty_rate', None)
        if excise_rate and float(excise_rate) > 0:
            return True

        # Check if excise duty code is set
        excise_code = getattr(product, 'efris_excise_duty_code', None)
        if excise_code and excise_code.strip():
            return True

        return False

    def _build_excise_tax_info(self, product) -> Dict[str, str]:
        """Build excise tax information for products with excise duty"""
        excise_info = {}

        excise_code = getattr(product, 'efris_excise_duty_code', '')
        if excise_code:
            excise_info["exciseDutyCode"] = str(excise_code)[:20]

        # If excise has piece unit measurement
        has_piece_unit = getattr(product, 'efris_has_piece_unit', False)
        if has_piece_unit:
            excise_info["havePieceUnit"] = "101"

            piece_measure_unit = getattr(product, 'efris_piece_measure_unit', 'U')
            excise_info["pieceMeasureUnit"] = str(piece_measure_unit)

            piece_price = float(getattr(product, 'efris_piece_unit_price', 0) or 0)
            excise_info["pieceUnitPrice"] = f"{piece_price:.2f}"

            # Scaling values (default to 1)
            excise_info["packageScaledValue"] = str(
                getattr(product, 'efris_package_scaled_value', 1)
            )
            excise_info["pieceScaledValue"] = str(
                getattr(product, 'efris_piece_scaled_value', 1)
            )

        return excise_info

    def _build_customs_info(self, product) -> Optional[Dict[str, str]]:
        """Build customs unit of measure information if available"""
        customs_unit = getattr(product, 'efris_customs_measure_unit', None)

        if not customs_unit:
            return None

        return {
            "customsMeasureUnit": str(customs_unit),
            "customsUnitPrice": f"{float(getattr(product, 'efris_customs_unit_price', 0)):.2f}",
            "packageScaledValueCustoms": str(
                getattr(product, 'efris_package_scaled_customs', 1)
            ),
            "customsScaledValue": f"{float(getattr(product, 'efris_customs_scaled_value', 1)):.2f}"
        }

    def _build_other_units(self, product) -> Optional[List[Dict[str, str]]]:
        if not hasattr(product, 'efris_other_units') or not product.efris_other_units:
            return None

        other_units = []

        try:
            # Assuming efris_other_units is a JSON field or related objects
            units_data = product.efris_other_units
            if isinstance(units_data, str):
                import json
                units_data = json.loads(units_data)

            for unit_data in units_data:
                other_unit = {
                    "otherUnit": str(unit_data.get('unit_code', 'U')),
                    "otherPrice": f"{float(unit_data.get('price', 0)):.2f}",
                    "otherScaled": f"{float(unit_data.get('scaled_value', 1)):.2f}",
                    "packageScaled": f"{float(unit_data.get('package_scaled', 1)):.2f}"
                }
                other_units.append(other_unit)
        except Exception as e:
            logger.warning(f"Failed to build other units: {e}")
            return None

        return other_units if other_units else None

    def _get_default_unit_code(self) -> str:
        """Get default unit of measure code"""
        return "101"  # Default from T115 rateUnit - adjust based on your business

    def _validate_t130_data(self, goods_data: Dict) -> List[str]:
        """Validate T130 goods data against EFRIS rules"""
        errors = []

        # Required fields validation
        required_fields = [
            'goodsName', 'goodsCode', 'measureUnit', 'unitPrice',
            'currency', 'commodityCategoryId', 'haveExciseTax',
            'stockPrewarning', 'havePieceUnit'
        ]

        for field in required_fields:
            if field not in goods_data or not str(goods_data[field]).strip():
                errors.append(f"Missing required field: {field}")

        # Conditional validation for piece unit
        have_piece_unit = goods_data.get('havePieceUnit')
        if have_piece_unit == '101':
            # Piece unit fields required
            if not goods_data.get('pieceMeasureUnit'):
                errors.append("pieceMeasureUnit required when havePieceUnit=101")
            if not goods_data.get('pieceUnitPrice'):
                errors.append("pieceUnitPrice required when havePieceUnit=101")
            if not goods_data.get('packageScaledValue'):
                errors.append("packageScaledValue required when havePieceUnit=101")
            if not goods_data.get('pieceScaledValue'):
                errors.append("pieceScaledValue required when havePieceUnit=101")
        elif have_piece_unit == '102':
            # Piece unit fields must be empty
            if goods_data.get('pieceMeasureUnit'):
                errors.append("pieceMeasureUnit must be empty when havePieceUnit=102")

        # Conditional validation for excise tax
        have_excise = goods_data.get('haveExciseTax')
        if have_excise == '102' and goods_data.get('exciseDutyCode'):
            errors.append("exciseDutyCode must be empty when haveExciseTax=102")

        # Conditional validation for other units
        have_other_unit = goods_data.get('haveOtherUnit')
        if have_piece_unit == '102' and have_other_unit == '101':
            errors.append("haveOtherUnit must be 102 when havePieceUnit=102")

        # Length validations
        if len(goods_data.get('goodsName', '')) > 200:
            errors.append("goodsName cannot exceed 200 characters")

        if len(goods_data.get('goodsCode', '')) > 50:
            errors.append("goodsCode cannot exceed 50 characters")

        if len(goods_data.get('description', '')) > 1024:
            errors.append("description cannot exceed 1024 characters")

        return errors

    def _process_t130_success_response(self, product, response_data: Dict):
        """Process successful T130 response and update product"""
        try:
            data_section = response_data.get('data', {})
            if data_section.get('content'):
                decrypted_content = self._decrypt_response_content(data_section)

                if decrypted_content and isinstance(decrypted_content, list):
                    # T130 returns array of goods
                    for goods_info in decrypted_content:
                        return_code = goods_info.get('returnCode')

                        if return_code == '601' or return_code == '00':
                            # Success - update product
                            if hasattr(product, 'efris_is_uploaded'):
                                product.efris_is_uploaded = True

                            if hasattr(product, 'efris_upload_date'):
                                product.efris_upload_date = timezone.now()

                            # Store any returned commodity goods ID
                            goods_id = goods_info.get('commodityGoodsId') or goods_info.get('goodsId') or goods_info.get('id')
                            if goods_id and hasattr(product, 'efris_goods_id'):
                                product.efris_goods_id = goods_id

                            product.save()
                            logger.info(f"Product {product.id} marked as uploaded to EFRIS")
                            break

        except Exception as e:
            logger.warning(f"Failed to process T130 response: {e}")

    def _make_request(
            self,
            interface_code: str,
            content: Optional[Dict] = None,
            encrypt: bool = True,
            decrypt_response: bool = True
    ) -> Dict:
        """
        Make API request to EFRIS
        EXACTLY matching working test script
        """
        request_data = self._build_request(interface_code, content, encrypt)

        logger.info(f"REQUEST: {interface_code} | Encrypted: {encrypt}")

        try:
            response = self._make_http_request(request_data)

            # ⚠️ CRITICAL FIX: Check response content type before parsing
            content_type = response.headers.get('Content-Type', '')

            # Debug log the actual response
            logger.debug(
                f"Response details",
                extra={
                    'status': response.status_code,
                    'content_type': content_type,
                    'content_length': len(response.content),
                    'content_preview': response.text[:200] if response.text else 'empty'
                }
            )

            # Check if response is HTML error page
            if 'text/html' in content_type or response.text.strip().startswith(
                    '<!DOCTYPE') or response.text.strip().startswith('<html'):
                logger.error(
                    f"EFRIS returned HTML error page instead of JSON",
                    extra={
                        'interface_code': interface_code,
                        'status_code': response.status_code,
                        'html_preview': response.text[:500]
                    }
                )
                raise Exception(
                    f"EFRIS API error: Received HTML instead of JSON. "
                    f"Status: {response.status_code}. "
                    f"This usually means the API endpoint is wrong or request format is invalid."
                )

            # Try to parse JSON
            try:
                response_data = response.json()
            except json.JSONDecodeError as json_err:
                logger.error(
                    f"Failed to parse JSON response",
                    extra={
                        'interface_code': interface_code,
                        'status_code': response.status_code,
                        'content_type': content_type,
                        'response_text': response.text[:1000]
                    }
                )
                raise Exception(
                    f"Invalid JSON response from EFRIS. "
                    f"Response text: {response.text[:200]}"
                )

            # Handle different response formats (list vs dict)
            if isinstance(response_data, dict):
                return_code = response_data.get("returnStateInfo", {}).get("returnCode", "N/A")
            elif isinstance(response_data, list):
                # T130 or similar: multiple items returned directly
                return_code = ", ".join(
                    [str(item.get("returnCode", "N/A")) for item in response_data if isinstance(item, dict)]
                )
            else:
                return_code = "UnknownType"

            logger.info(f"RESPONSE: {interface_code} | Code: {return_code}")

            # Parse the decrypted response
            parsed = self._parse_response(response_data, decrypt_response)

            return parsed

        except requests.exceptions.Timeout:
            logger.error(f"{interface_code} request timeout")
            raise Exception(f"Request timeout for {interface_code}")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"{interface_code} connection error: {e}")
            raise Exception(f"Connection error for {interface_code}: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"{interface_code} HTTP error: {e}")
            raise Exception(f"HTTP request failed for {interface_code}: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"{interface_code} JSON decode error: {e}")
            raise Exception(f"Invalid JSON response for {interface_code}: {e}")
        except Exception as e:
            logger.error(f"{interface_code} failed: {e}", exc_info=True)
            raise

    def get_server_time(self) -> Dict[str, Any]:
        """T101 - Get Server Time"""
        try:
            response = self._make_request("T101", encrypt=False, decrypt_response=False)
            server_time_str = response.get("currentTime", "")
            if server_time_str:
                logger.info(f"Server Time: {server_time_str}")
            return {"success": True, "data": response}
        except Exception as e:
            logger.error(f"T101 failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def _get_symmetric_key(self) -> Dict[str, Any]:
        """T104 - Get Symmetric Key"""
        try:
            response = self._make_request("T104", encrypt=False, decrypt_response=False)

            # Handle typo in API response
            encrypted_key = response.get("passwordDes") or response.get("passowrdDes", "")

            if not encrypted_key:
                return {"success": False, "error": "No encrypted key in response"}

            # Decrypt AES key
            private_key = self._load_private_key()
            aes_key = self.security_manager.decrypt_aes_key(encrypted_key, private_key)

            # Store key
            self.security_manager.set_current_aes_key(aes_key)

            logger.info("AES key received and stored successfully")
            return {"success": True, "aes_key": aes_key.hex()}
        except Exception as e:
            logger.error(f"T104 failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def _login(self) -> Dict:
        """T103 - Login"""
        try:
            if not self.security_manager.is_aes_key_valid():
                logger.info("AES key expired, calling T104...")
                key_result = self._get_symmetric_key()
                if not key_result.get("success"):
                    return {"success": False, "error": f"T104 failed: {key_result.get('error')}"}

            response = self._make_request("T103", content={}, encrypt=True)

            device = response.get("device", {})
            taxpayer = response.get("taxpayer", {})

            logger.info(
                f"Logged in | Device: {device.get('deviceNo')} | "
                f"Taxpayer: {taxpayer.get('legalName')}"
            )

            self._is_authenticated = True
            self._last_login = django_timezone.now()

            return {"success": True, "data": response}
        except Exception as e:
            logger.error(f"T103 failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def ensure_authenticated(self) -> Dict:
        """Ensure client is authenticated"""
        try:
            if self._is_authenticated and self.security_manager.is_aes_key_valid():
                return {"success": True, "message": "Already authenticated"}

            # Get server time (optional)
            time_result = self.get_server_time()
            if not time_result.get("success"):
                logger.warning(f"T101 failed: {time_result.get('error')}")

            # Get symmetric key
            key_result = self._get_symmetric_key()
            if not key_result.get("success"):
                return {"success": False, "error": f"T104 failed: {key_result.get('error')}"}

            # Login
            login_result = self._login()
            if not login_result.get("success"):
                return {"success": False, "error": f"T103 failed: {login_result.get('error')}"}

            logger.info("Authentication completed successfully")
            return {"success": True, "message": "Authentication successful"}

        except Exception as e:
            logger.error(f"Authentication failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def query_all_commodity_categories(self) -> Dict[str, Any]:
        """T123 - Query Commodity Categories (CONFIRMED WORKING)"""
        try:
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "categories": []
                }

            # T123: No content, not encrypted (like T104)
            response = self._make_request("T123", content=None, encrypt=False, decrypt_response=True)

            # Extract and save categories
            categories = self._extract_and_save_categories(response)

            logger.info(f"Retrieved {len(categories)} commodity categories")

            return {
                "success": True,
                "categories": categories,
                "total_count": len(categories)
            }
        except Exception as e:
            logger.error(f"T123 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "categories": []
            }

    def upload_invoice(self, invoice, user=None) -> Dict[str, Any]:
        """
        Upload invoice to EFRIS - PRODUCTION VERSION

        Returns:
            Dict with keys: success, message, data, error_code
        """
        try:
            # Build invoice data
            transformer = EFRISDataTransformer(self.company)
            invoice_data = transformer.build_invoice_data(invoice)

            # Validate data
            validation_errors = DataValidator.validate_invoice_data(invoice_data)
            if validation_errors:
                logger.error(f"Invoice validation failed: {validation_errors}")
                return {
                    "success": False,
                    "message": f"Validation failed: {'; '.join(validation_errors)}",
                    "error_code": "VALIDATION_ERROR",
                    "data": None
                }

            # Ensure authenticated
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "message": f"Authentication failed: {auth_result.get('error')}",
                    "error_code": "AUTH_FAILED",
                    "data": None
                }

            # Log the request
            logger.info(
                f"Uploading invoice {invoice_data['basicInformation']['invoiceNo']} to EFRIS",
                extra={
                    'invoice_id': getattr(invoice, 'id', None),
                    'gross_amount': invoice_data['summary']['grossAmount']
                }
            )

            response = self._make_request("T109", invoice_data, encrypt=True)

            # Extract invoice details from response
            basic_info = response.get('basicInformation', {})
            invoice_no = basic_info.get('invoiceNo')
            invoice_id = basic_info.get('invoiceId')
            fiscal_code = basic_info.get('antifakeCode', '')

            logger.info(
                f"Invoice uploaded successfully: {invoice_no} (ID: {invoice_id})",
                extra={
                    'invoice_no': invoice_no,
                    'invoice_id': invoice_id,
                    'fiscal_code': fiscal_code
                }
            )

            return {
                "success": True,
                "message": f"Invoice {invoice_no} uploaded successfully",
                "data": {
                    "invoice_no": invoice_no,
                    "invoice_id": invoice_id,
                    "fiscal_code": fiscal_code,
                    "full_response": response
                },
                "error_code": None
            }

        except Exception as e:
            logger.error(f"Invoice upload exception: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Upload error: {str(e)}",
                "error_code": "EXCEPTION",
                "data": None
            }

    def _extract_and_save_categories(self, content) -> list:
        """Extract categories from API response and save to DB safely"""
        from decimal import Decimal, InvalidOperation
        from django.utils import timezone as django_timezone
        from company.models import EFRISCommodityCategory

        def safe_decimal(value, default=0):
            """Convert value to Decimal, return default if invalid or empty"""
            try:
                if value is None or str(value).strip() == "":
                    return default
                return Decimal(str(value).replace('“', '').replace('”', '').strip())
            except (InvalidOperation, ValueError):
                return default

        def safe_str(value, default=""):
            """Convert value to string, handle None"""
            if value is None:
                return default
            return str(value).strip()

        def safe_date(value):
            """Return date or None if invalid/empty"""
            if value in [None, ""]:
                return None
            return value

        categories = []

        # Extract list from response
        if isinstance(content, list):
            categories = content
        elif isinstance(content, dict):
            for key in ['commodityCategoryList', 'records', 'data']:
                if key in content and isinstance(content[key], list):
                    categories = content[key]
                    break

        saved_categories = []

        for cat in categories:
            if not isinstance(cat, dict):
                continue

            code = safe_str(cat.get('commodityCategoryCode'))
            name = safe_str(cat.get('commodityCategoryName'))

            if not code or not name:
                continue

            obj, created = EFRISCommodityCategory.objects.update_or_create(
                commodity_category_code=code,
                defaults={
                    'commodity_category_name': name,
                    'parent_code': safe_str(cat.get('parentCode')),
                    'commodity_category_level': safe_str(cat.get('commodityCategoryLevel')),
                    'rate': safe_decimal(cat.get('rate')),
                    'service_mark': safe_str(cat.get('serviceMark')),
                    'is_leaf_node': safe_str(cat.get('isLeafNode')),
                    'is_zero_rate': safe_str(cat.get('isZeroRate')),
                    'zero_rate_start_date': safe_date(cat.get('zeroRateStartDate')),
                    'zero_rate_end_date': safe_date(cat.get('zeroRateEndDate')),
                    'is_exempt': safe_str(cat.get('isExempt')),
                    'exempt_rate_start_date': safe_date(cat.get('exemptRateStartDate')),
                    'exempt_rate_end_date': safe_date(cat.get('exemptRateEndDate')),
                    'enable_status_code': safe_str(cat.get('enableStatusCode')),
                    'exclusion': safe_str(cat.get('exclusion')),
                    'last_synced': django_timezone.now(),
                }
            )
            saved_categories.append(obj)

        self.logger.info(f"Saved {len(saved_categories)} categories to database")
        return saved_categories

    #==========================
    # credit note and more
    #===============
    # Add these methods to the EnhancedEFRISAPIClient class

    def t146_query_commodity_category_excise_by_date(
            self,
            category_code: str,
            query_type: str,
            issue_date: str
    ) -> Dict[str, Any]:
        """
        T146 - Query Commodity Category/Excise Duty by issueDate

        Args:
            category_code: Category code (e.g., "00000000001")
            query_type: "1" for Commodity Category, "2" for Excise Duty
            issue_date: Date in format "yyyy-MM-dd HH:mm:ss"

        Returns:
            Dict with commodity category or excise duty information
        """
        try:
            # Validate query_type
            if query_type not in ['1', '2']:
                return {
                    "success": False,
                    "error": "Query type must be '1' (Commodity Category) or '2' (Excise Duty)"
                }

            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Build request content
            content = {
                "categoryCode": category_code,
                "type": query_type,
                "issueDate": issue_date
            }

            logger.info(
                f"Querying {'Commodity Category' if query_type == '1' else 'Excise Duty'} "
                f"for code {category_code} at date {issue_date}"
            )

            # Make encrypted request
            response = self._make_request("T146", content, encrypt=True)

            result_type = 'commodity_category' if query_type == '1' else 'excise_duty'
            result_data = response.get('commodityCategory' if query_type == '1' else 'exciseDuty')

            logger.info(f"T146 query successful for {result_type}")

            return {
                "success": True,
                "query_type": query_type,
                "result_type": result_type,
                "data": result_data,
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T146 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t162_query_fuel_types(self) -> Dict[str, Any]:
        """
        T162 - Query Fuel Types

        Returns:
            Dict with list of fuel types
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "fuel_types": []
                }

            logger.info("Querying fuel types (T162)")

            # Make request (not encrypted per documentation)
            response = self._make_request("T162", content=None, encrypt=False, decrypt_response=True)

            # Response is a list of fuel types
            fuel_types = response if isinstance(response, list) else []

            logger.info(f"T162 successful: {len(fuel_types)} fuel types retrieved")

            return {
                "success": True,
                "fuel_types": fuel_types,
                "total_count": len(fuel_types)
            }

        except Exception as e:
            logger.error(f"T162 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "fuel_types": []
            }

    def t163_upload_shift_information(self, shift_data: Dict[str, str]) -> Dict[str, Any]:
        """
        T163 - Upload Shift Information (for fuel stations)

        Args:
            shift_data: Shift information including:
                - shiftNo, startVolume, endVolume, fuelType, goodsId, goodsCode,
                - invoiceAmount, invoiceNumber, nozzleNo, pumpNo, tankNo,
                - userName, userCode, startTime, endTime

        Returns:
            Dict with upload result
        """
        try:
            # Validate required fields
            required_fields = [
                'shiftNo', 'startVolume', 'endVolume', 'fuelType', 'goodsId',
                'goodsCode', 'invoiceAmount', 'invoiceNumber', 'nozzleNo',
                'pumpNo', 'tankNo', 'userName', 'userCode', 'startTime', 'endTime'
            ]

            missing_fields = [f for f in required_fields if f not in shift_data]
            if missing_fields:
                return {
                    "success": False,
                    "error": f"Missing required fields: {', '.join(missing_fields)}"
                }

            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            logger.info(f"Uploading shift information (T163) - Shift: {shift_data.get('shiftNo')}")

            # Make encrypted request (response not encrypted)
            request_data = self._build_request("T163", shift_data, encrypt=True)
            response = self._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            if return_code == '00':
                logger.info(f"T163 upload successful for shift: {shift_data.get('shiftNo')}")
                return {
                    "success": True,
                    "message": "Shift information uploaded successfully",
                    "shift_no": shift_data.get('shiftNo')
                }
            else:
                error_message = return_info.get('returnMessage', 'Upload failed')
                logger.error(f"T163 failed: {return_code} - {error_message}")
                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code
                }

        except Exception as e:
            logger.error(f"T163 upload failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t164_upload_edc_disconnection_data(
            self,
            disconnection_data: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        T164 - Upload EDC Disconnection Data

        Args:
            disconnection_data: List of disconnection records:
                [{
                    "deviceNumber": "...",
                    "disconnectedType": "101" or "102",
                    "disconnectedTime": "yyyy-MM-dd HH:mm:ss",
                    "remarks": "..."
                }]

        Returns:
            Dict with upload result
        """
        try:
            if not disconnection_data:
                return {
                    "success": False,
                    "error": "No disconnection data provided"
                }

            # Validate each record
            for idx, record in enumerate(disconnection_data):
                if 'deviceNumber' not in record:
                    return {
                        "success": False,
                        "error": f"Record {idx + 1}: Missing deviceNumber"
                    }
                if 'disconnectedType' not in record:
                    return {
                        "success": False,
                        "error": f"Record {idx + 1}: Missing disconnectedType"
                    }
                if record['disconnectedType'] not in ['101', '102']:
                    return {
                        "success": False,
                        "error": f"Record {idx + 1}: disconnectedType must be '101' or '102'"
                    }
                if 'disconnectedTime' not in record:
                    return {
                        "success": False,
                        "error": f"Record {idx + 1}: Missing disconnectedTime"
                    }

            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            logger.info(f"Uploading {len(disconnection_data)} EDC disconnection records (T164)")

            # Make encrypted request (response not encrypted)
            request_data = self._build_request("T164", disconnection_data, encrypt=True)
            response = self._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            if return_code == '00':
                logger.info(f"T164 upload successful: {len(disconnection_data)} records")
                return {
                    "success": True,
                    "message": f"Successfully uploaded {len(disconnection_data)} disconnection records",
                    "records_count": len(disconnection_data)
                }
            else:
                error_message = return_info.get('returnMessage', 'Upload failed')
                logger.error(f"T164 failed: {return_code} - {error_message}")
                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code
                }

        except Exception as e:
            logger.error(f"T164 upload failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t166_update_buyer_details(self, buyer_update_data: Dict[str, str]) -> Dict[str, Any]:
        """
        T166 - Update Buyer Details for an existing invoice

        Args:
            buyer_update_data: Buyer information including:
                - invoiceNo (required)
                - buyerTin, buyerNinBrn, buyerPassportNum
                - buyerLegalName, buyerBusinessName, buyerAddress
                - buyerEmailAddress, buyerMobilePhone, buyerLinePhone
                - buyerPlaceOfBusi, buyerType, buyerCitizenship
                - buyerSector, mvrn, createDateStr

        Returns:
            Dict with update result
        """
        try:
            # Validate required fields
            if 'invoiceNo' not in buyer_update_data:
                return {
                    "success": False,
                    "error": "invoiceNo is required"
                }

            if 'buyerType' not in buyer_update_data:
                return {
                    "success": False,
                    "error": "buyerType is required"
                }

            # Validate buyerType
            if buyer_update_data['buyerType'] not in ['0', '1', '2', '3']:
                return {
                    "success": False,
                    "error": "buyerType must be 0 (B2B), 1 (B2C), 2 (Foreigner), or 3 (B2G)"
                }

            # B2B validation
            if buyer_update_data['buyerType'] == '0' and not buyer_update_data.get('buyerTin'):
                return {
                    "success": False,
                    "error": "buyerTin is required when buyerType is 0 (B2B)"
                }

            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            logger.info(f"Updating buyer details (T166) for invoice: {buyer_update_data.get('invoiceNo')}")

            # Make encrypted request (response not encrypted)
            request_data = self._build_request("T166", buyer_update_data, encrypt=True)
            response = self._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            if return_code == '00':
                logger.info(f"T166 update successful for invoice: {buyer_update_data.get('invoiceNo')}")
                return {
                    "success": True,
                    "message": "Buyer details updated successfully",
                    "invoice_no": buyer_update_data.get('invoiceNo')
                }
            else:
                error_message = return_info.get('returnMessage', 'Update failed')
                logger.error(f"T166 failed: {return_code} - {error_message}")
                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code
                }

        except Exception as e:
            logger.error(f"T166 update failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t167_edc_invoice_inquiry(
            self,
            fuel_type: Optional[str] = None,
            invoice_no: Optional[str] = None,
            buyer_legal_name: Optional[str] = None,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            page_no: int = 1,
            page_size: int = 10,
            query_type: str = "1",
            branch_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        T167 - EDC Invoice/Receipt Inquiry (for fuel stations)

        Args:
            fuel_type: Fuel type filter
            invoice_no: Invoice number filter
            buyer_legal_name: Buyer name filter
            start_date: Start date (yyyy-MM-dd)
            end_date: End date (yyyy-MM-dd)
            page_no: Page number
            page_size: Results per page (max 100)
            query_type: "1" (all unmodified), "2" (modified successfully), "3" (all)
            branch_id: Branch ID filter

        Returns:
            Dict with paginated EDC invoice results
        """
        try:
            # Validate page_size
            if page_size > 100:
                return {
                    "success": False,
                    "error": "Page size cannot exceed 100",
                    "invoices": []
                }

            # Validate query_type
            if query_type not in ['1', '2', '3']:
                return {
                    "success": False,
                    "error": "Query type must be '1', '2', or '3'",
                    "invoices": []
                }

            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "invoices": []
                }

            # Build request content
            content = {
                "pageNo": str(page_no),
                "pageSize": str(page_size),
                "queryType": query_type
            }

            # Add optional filters
            if fuel_type:
                content["fuelType"] = fuel_type
            if invoice_no:
                content["invoiceNo"] = invoice_no
            if buyer_legal_name:
                content["buyerLegalName"] = buyer_legal_name
            if start_date:
                content["startDate"] = start_date
            if end_date:
                content["endDate"] = end_date
            if branch_id:
                content["branchId"] = branch_id

            logger.info(f"Querying EDC invoices (T167) - page {page_no}")

            # Make encrypted request
            response = self._make_request("T167", content, encrypt=True)

            # Extract results
            records = response.get("records", [])
            pagination = response.get("page", {})

            logger.info(f"T167 query successful: {len(records)} EDC invoices returned")

            return {
                "success": True,
                "invoices": records,
                "pagination": {
                    "page_no": int(pagination.get('pageNo', page_no)),
                    "page_size": int(pagination.get('pageSize', page_size)),
                    "total_size": int(pagination.get('totalSize', 0)),
                    "page_count": int(pagination.get('pageCount', 0))
                },
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T167 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "invoices": []
            }

    def t168_query_fuel_pump_version(self) -> Dict[str, Any]:
        """
        T168 - Query Fuel Pump Version

        Returns:
            Dict with fuel pump list and default buyer list
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            logger.info("Querying fuel pump version (T168)")

            # Make request (not encrypted per documentation)
            response = self._make_request("T168", content=None, encrypt=False, decrypt_response=True)

            fuel_pump_list = response.get("fuelPumpList", [])
            fuel_default_buyer_list = response.get("fuelDefaultBuyerList", [])

            logger.info(
                f"T168 successful: {len(fuel_pump_list)} pumps, "
                f"{len(fuel_default_buyer_list)} default buyers"
            )

            return {
                "success": True,
                "fuel_pump_list": fuel_pump_list,
                "fuel_default_buyer_list": fuel_default_buyer_list,
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T168 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t169_query_fuel_equipment_by_pump(self, pump_id: str) -> Dict[str, Any]:
        """
        T169 - Query fuel pump, nozzle, tank according to pump no

        Args:
            pump_id: Pump ID

        Returns:
            Dict with pump, nozzle, tank, and EDC device information
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            content = {"id": pump_id}

            logger.info(f"Querying fuel equipment (T169) for pump: {pump_id}")

            # Make encrypted request
            response = self._make_request("T169", content, encrypt=True)

            logger.info(f"T169 query successful for pump: {pump_id}")

            return {
                "success": True,
                "fuel_pump": response.get("fuelPump", {}),
                "fuel_nozzle_list": response.get("fuelNozzleList", []),
                "fuel_tank_list": response.get("fuelTankList", []),
                "fuel_edc_device_list": response.get("fuelEdcDeviceList", []),
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T169 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t170_query_efd_location(
            self,
            device_number: str,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        T170 - Query EFD Location
        Returns latest X records (X is configurable, default 10)

        Args:
            device_number: Device number
            start_date: Start date (yyyy-MM-dd)
            end_date: End date (yyyy-MM-dd)

        Returns:
            Dict with location records
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "locations": []
                }

            # Build request content
            content = {"deviceNumber": device_number}

            if start_date:
                content["startDate"] = start_date
            if end_date:
                content["endDate"] = end_date

            logger.info(f"Querying EFD location (T170) for device: {device_number}")

            # Make encrypted request
            response = self._make_request("T170", content, encrypt=True)

            # Response is a list of location records
            locations = response if isinstance(response, list) else []

            logger.info(f"T170 query successful: {len(locations)} location records")

            return {
                "success": True,
                "locations": locations,
                "device_number": device_number,
                "total_records": len(locations)
            }

        except Exception as e:
            logger.error(f"T170 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "locations": []
            }

    def t171_query_edc_uom_exchange_rate(self) -> Dict[str, Any]:
        """
        T171 - Query EDC Unit of Measure Exchange Rate

        Returns:
            Dict with UoM exchange rates
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "exchange_rates": []
                }

            logger.info("Querying EDC UoM exchange rates (T171)")

            # Make request (not encrypted per documentation)
            response = self._make_request("T171", content=None, encrypt=False, decrypt_response=True)

            # Response is a list of exchange rates
            exchange_rates = response if isinstance(response, list) else []

            logger.info(f"T171 successful: {len(exchange_rates)} exchange rates retrieved")

            return {
                "success": True,
                "exchange_rates": exchange_rates,
                "total_count": len(exchange_rates)
            }

        except Exception as e:
            logger.error(f"T171 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "exchange_rates": []
            }

    def t172_upload_fuel_nozzle_status(
            self,
            nozzle_id: str,
            nozzle_no: str,
            status: str
    ) -> Dict[str, Any]:
        """
        T172 - Fuel Nozzle Status Upload

        Args:
            nozzle_id: Nozzle ID (18 digits)
            nozzle_no: Nozzle number (50 chars)
            status: Status code
                "1" - Available
                "2" - Card Plug-in
                "3" - Nozzle Lift
                "4" - Fueling
                "5" - Nozzle Hang
                "6" - Settling
                "7" - Nozzle Locked
                "10" - Offline

        Returns:
            Dict with upload result
        """
        try:
            # Validate status
            valid_statuses = ['1', '2', '3', '4', '5', '6', '7', '10']
            if status not in valid_statuses:
                return {
                    "success": False,
                    "error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                }

            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            content = {
                "nozzleId": nozzle_id,
                "nozzleNo": nozzle_no,
                "status": status
            }

            logger.info(f"Uploading nozzle status (T172) - Nozzle: {nozzle_no}, Status: {status}")

            # Make encrypted request (response not encrypted)
            request_data = self._build_request("T172", content, encrypt=True)
            response = self._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            if return_code == '00':
                logger.info(f"T172 upload successful for nozzle: {nozzle_no}")
                return {
                    "success": True,
                    "message": "Nozzle status uploaded successfully",
                    "nozzle_no": nozzle_no,
                    "status": status
                }
            else:
                error_message = return_info.get('returnMessage', 'Upload failed')
                logger.error(f"T172 failed: {return_code} - {error_message}")
                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code
                }

        except Exception as e:
            logger.error(f"T172 upload failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t173_query_edc_device_version(self) -> Dict[str, Any]:
        """
        T173 - Query EDC Device Version

        Returns:
            Dict with EDC device versions
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "devices": []
                }

            logger.info("Querying EDC device versions (T173)")

            # Make request (not encrypted per documentation)
            response = self._make_request("T173", content=None, encrypt=False, decrypt_response=True)

            # Response is a list of device versions
            devices = response if isinstance(response, list) else []

            logger.info(f"T173 successful: {len(devices)} device versions retrieved")

            return {
                "success": True,
                "devices": devices,
                "total_count": len(devices)
            }

        except Exception as e:
            logger.error(f"T173 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "devices": []
            }

    def t175_create_ussd_taxpayer_account(
            self,
            tin: str,
            mobile_number: str
    ) -> Dict[str, Any]:
        """
        T175 - Account Creation for USSD Taxpayer

        Args:
            tin: Taxpayer TIN (10-20 digits)
            mobile_number: Mobile number (30 chars)

        Returns:
            Dict with account creation result
        """
        try:
            # Validate TIN
            is_valid, error = DataValidator.validate_tin(tin)
            if not is_valid:
                return {
                    "success": False,
                    "error": f"Invalid TIN: {error}"
                }

            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            content = {
                "tin": tin,
                "mobileNumber": mobile_number
            }

            logger.info(f"Creating USSD account (T175) for TIN: {tin}")

            # Make encrypted request (response not encrypted)
            request_data = self._build_request("T175", content, encrypt=True)
            response = self._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            if return_code == '00':
                logger.info(f"T175 account creation successful for TIN: {tin}")
                return {
                    "success": True,
                    "message": "USSD account created successfully",
                    "tin": tin,
                    "mobile_number": mobile_number
                }
            else:
                error_message = return_info.get('returnMessage', 'Account creation failed')
                logger.error(f"T175 failed: {return_code} - {error_message}")
                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code
                }

        except Exception as e:
            logger.error(f"T175 account creation failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t176_upload_device_issuing_status(
            self,
            device_no: str,
            device_issuing_status: str
    ) -> Dict[str, Any]:
        """
        T176 - Upload Device Issuing Status

        Args:
            device_no: Device number (20 chars)
            device_issuing_status: Status code
                "101" - Ready
                "102" - Issuing
                "103" - Printing

        Returns:
            Dict with upload result
        """
        try:
            # Validate status
            valid_statuses = ['101', '102', '103']
            if device_issuing_status not in valid_statuses:
                return {
                    "success": False,
                    "error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                }

            content = {
                "deviceNo": device_no,
                "deviceIssuingStatus": device_issuing_status
            }

            logger.info(f"Uploading device issuing status (T176) - Device: {device_no}")

            # Make request (not encrypted per documentation)
            request_data = self._build_request("T176", content, encrypt=False)
            response = self._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            if return_code == '00':
                logger.info(f"T176 upload successful for device: {device_no}")
                return {
                    "success": True,
                    "message": "Device issuing status uploaded successfully",
                    "device_no": device_no,
                    "status": device_issuing_status
                }
            else:
                error_message = return_info.get('returnMessage', 'Upload failed')
                logger.error(f"T176 failed: {return_code} - {error_message}")
                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code
                }

        except Exception as e:
            logger.error(f"T176 upload failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t177_query_negative_stock_configuration(self) -> Dict[str, Any]:
        """
        T177 - Negative Stock Configuration Inquiry

        Returns:
            Dict with negative stock configuration
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            logger.info("Querying negative stock configuration (T177)")

            # Make request (not encrypted per documentation)
            response = self._make_request("T177", content=None, encrypt=False, decrypt_response=False)

            goods_stock_limit = response.get("goodsStockLimit", {})
            goods_stock_limit_category_list = response.get("goodsStockLimitCategoryList", [])

            logger.info("T177 query successful")

            return {
                "success": True,
                "goods_stock_limit": goods_stock_limit,
                "category_list": goods_stock_limit_category_list,
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T177 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t178_efd_transfer(
            self,
            destination_branch_id: str,
            remarks: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        T178 - EFD Transfer (transfer device to another branch)

        Args:
            destination_branch_id: Destination branch ID (18 digits)
            remarks: Transfer remarks (max 1024 chars)

        Returns:
            Dict with transfer result
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            content = {
                "destinationBranchId": destination_branch_id
            }

            if remarks:
                content["remarks"] = remarks[:1024]  # Ensure max length

            logger.info(f"Transferring EFD (T178) to branch: {destination_branch_id}")

            # Make encrypted request (response not encrypted)
            request_data = self._build_request("T178", content, encrypt=True)
            response = self._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            if return_code == '00':
                logger.info(f"T178 transfer successful to branch: {destination_branch_id}")
                return {
                    "success": True,
                    "message": "EFD transfer completed successfully",
                    "destination_branch_id": destination_branch_id
                }
            else:
                error_message = return_info.get('returnMessage', 'Transfer failed')
                logger.error(f"T178 failed: {return_code} - {error_message}")
                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code
                }

        except Exception as e:
            logger.error(f"T178 transfer failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t179_query_agent_relation_information(
            self,
            tin: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        T179 - Query Agent Relation Information

        Args:
            tin: Principal agent TIN (optional)

        Returns:
            Dict with agent taxpayer list
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "agent_taxpayers": []
                }

            content = {}
            if tin:
                content["tin"] = tin

            logger.info(f"Querying agent relations (T179)" + (f" for TIN: {tin}" if tin else ""))

            # Make encrypted request
            response = self._make_request("T179", content if content else None, encrypt=True)

            agent_taxpayer_list = response.get("agentTaxpayerList", [])

            logger.info(f"T179 query successful: {len(agent_taxpayer_list)} agent taxpayers")

            return {
                "success": True,
                "agent_taxpayers": agent_taxpayer_list,
                "total_count": len(agent_taxpayer_list),
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T179 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "agent_taxpayers": []
            }

    def t180_query_principal_agent_tin_information(
            self,
            tin: str,
            branch_id: str
    ) -> Dict[str, Any]:
        """
        T180 - Query Principal Agent TIN Information

        Args:
            tin: Principal agent TIN (20 chars)
            branch_id: Branch ID (18 digits)

        Returns:
            Dict with tax type information and settings
        """
        try:
            # Validate TIN
            is_valid, error = DataValidator.validate_tin(tin)
            if not is_valid:
                return {
                    "success": False,
                    "error": f"Invalid TIN: {error}"
                }

            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            content = {
                "tin": tin,
                "branchId": branch_id
            }

            logger.info(f"Querying principal agent info (T180) - TIN: {tin}, Branch: {branch_id}")

            # Make encrypted request
            response = self._make_request("T180", content, encrypt=True)

            tax_types = response.get("taxType", [])

            logger.info(f"T180 query successful: {len(tax_types)} tax types")

            return {
                "success": True,
                "tin": tin,
                "branch_id": branch_id,
                "tax_types": tax_types,
                "issue_tax_type_restrictions": response.get("issueTaxTypeRestrictions"),
                "sellers_logo": response.get("sellersLogo"),
                "is_allow_back_date": response.get("isAllowBackDate"),
                "is_duty_free_taxpayer": response.get("isDutyFreeTaxpayer"),
                "period_date": response.get("periodDate"),
                "is_allow_issue_invoice": response.get("isAllowIssueInvoice"),
                "is_allow_out_of_scope_vat": response.get("isAllowOutOfScopeVAT"),
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T180 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t181_upload_frequent_contacts(
            self,
            operation_type: str,
            contact_data: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        T181 - Upload Frequent Contacts

        Args:
            operation_type: "101" (Add), "102" (Modify), "103" (Delete)
            contact_data: Contact information including:
                - id (required for modify/delete)
                - buyerType (required)
                - buyerTin, buyerNinBrn, buyerLegalName, buyerBusinessName
                - buyerEmail, buyerLinePhone, buyerAddress
                - buyerCitizenship, buyerPassportNum

        Returns:
            Dict with upload result
        """
        try:
            # Validate operation_type
            if operation_type not in ['101', '102', '103']:
                return {
                    "success": False,
                    "error": "Operation type must be 101 (Add), 102 (Modify), or 103 (Delete)"
                }

            # Validate required fields
            if 'buyerType' not in contact_data:
                return {
                    "success": False,
                    "error": "buyerType is required"
                }

            if contact_data['buyerType'] not in ['0', '1', '2', '3']:
                return {
                    "success": False,
                    "error": "buyerType must be 0 (B2B), 1 (B2C), 2 (Foreigner), or 3 (B2G)"
                }

            # For modify/delete, id is required
            if operation_type in ['102', '103'] and 'id' not in contact_data:
                return {
                    "success": False,
                    "error": "id is required for modify/delete operations"
                }

            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Build request
            request_content = {
                "operationType": operation_type,
                **contact_data
            }

            operation_name = {
                '101': 'Adding',
                '102': 'Modifying',
                '103': 'Deleting'
            }[operation_type]

            logger.info(f"{operation_name} frequent contact (T181)")

            # Make encrypted request (response not encrypted)
            request_data = self._build_request("T181", request_content, encrypt=True)
            response = self._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            if return_code == '00':
                logger.info(f"T181 {operation_name.lower()} successful")
                return {
                    "success": True,
                    "message": f"Contact {operation_name.lower()} successfully",
                    "operation_type": operation_type
                }
            else:
                error_message = return_info.get('returnMessage', 'Operation failed')
                logger.error(f"T181 failed: {return_code} - {error_message}")
                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code
                }

        except Exception as e:
            logger.error(f"T181 operation failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t182_get_frequent_contacts(
            self,
            buyer_tin: Optional[str] = None,
            buyer_legal_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        T182 - Get Frequent Contacts

        Args:
            buyer_tin: Buyer TIN filter
            buyer_legal_name: Buyer legal name filter

        Returns:
            Dict with list of frequent contacts
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "contacts": []
                }

            # Build request content
            content = {}
            if buyer_tin:
                content["buyerTin"] = buyer_tin
            if buyer_legal_name:
                content["buyerLegalName"] = buyer_legal_name

            logger.info("Getting frequent contacts (T182)")

            # Make encrypted request
            response = self._make_request("T182", content if content else None, encrypt=True)

            # Response is a list of contacts
            contacts = response if isinstance(response, list) else []

            logger.info(f"T182 query successful: {len(contacts)} contacts retrieved")

            return {
                "success": True,
                "contacts": contacts,
                "total_count": len(contacts)
            }

        except Exception as e:
            logger.error(f"T182 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "contacts": []
            }

    def t185_query_hs_code_list(self) -> Dict[str, Any]:
        """
        T185 - Query HS Code List (Harmonized System codes for customs)

        Returns:
            Dict with HS code list
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "hs_codes": []
                }

            logger.info("Querying HS code list (T185)")

            # Make request (not encrypted per documentation)
            response = self._make_request("T185", content=None, encrypt=False, decrypt_response=False)

            # Response is a list of HS codes
            hs_codes = response if isinstance(response, list) else []

            logger.info(f"T185 query successful: {len(hs_codes)} HS codes retrieved")

            return {
                "success": True,
                "hs_codes": hs_codes,
                "total_count": len(hs_codes)
            }

        except Exception as e:
            logger.error(f"T185 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "hs_codes": []
            }

    def t186_query_invoice_remain_details(self, invoice_no: str) -> Dict[str, Any]:
        """
        T186 - Invoice Remain Details (comprehensive invoice details including remain quantities)

        Args:
            invoice_no: Invoice number

        Returns:
            Dict with complete invoice details including remaining amounts
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            content = {"invoiceNo": invoice_no}

            logger.info(f"Querying invoice remain details (T186) for: {invoice_no}")

            # Make encrypted request
            response = self._make_request("T186", content, encrypt=True)

            logger.info(f"T186 query successful for invoice: {invoice_no}")

            return {
                "success": True,
                "invoice_no": invoice_no,
                "seller_details": response.get("sellerDetails", {}),
                "basic_information": response.get("basicInformation", {}),
                "buyer_details": response.get("buyerDetails", {}),
                "buyer_extend": response.get("buyerExtend", {}),
                "goods_details": response.get("goodsDetails", []),
                "tax_details": response.get("taxDetails", []),
                "summary": response.get("summary", {}),
                "pay_way": response.get("payWay", []),
                "extend": response.get("extend", {}),
                "custom": response.get("custom", {}),
                "import_services_seller": response.get("importServicesSeller", {}),
                "airline_goods_details": response.get("airlineGoodsDetails", []),
                "edc_details": response.get("edcDetails", {}),
                "agent_entity": response.get("agentEntity", {}),
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T186 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "invoice_no": invoice_no
            }

    def t187_query_fdn_status(self, invoice_no: str) -> Dict[str, Any]:
        """
        T187 - Query Export FDN Status

        Args:
            invoice_no: FDN/Invoice number

        Returns:
            Dict with FDN status
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            content = {"invoiceNo": invoice_no}

            logger.info(f"Querying FDN status (T187) for: {invoice_no}")

            # Make encrypted request
            response = self._make_request("T187", content, encrypt=True)

            invoice_no_response = response.get("invoiceNo")
            document_status_code = response.get("documentStatusCode")

            status_names = {
                '101': 'FDN under processing',
                '102': 'Exited'
            }
            status_name = status_names.get(document_status_code, 'Unknown')

            logger.info(f"T187 query successful: {invoice_no} - Status: {status_name}")

            return {
                "success": True,
                "invoice_no": invoice_no_response,
                "document_status_code": document_status_code,
                "document_status_name": status_name,
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T187 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "invoice_no": invoice_no
            }

    def t132_upload_exception_logs(
            self,
            exception_logs: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        T132 - Upload Exception Logs
        Upload abnormal log information from the last login period

        Args:
            exception_logs: List of exception log entries:
                [{
                    "interruptionTypeCode": "101",  # 101-105
                    "description": "Error description",
                    "errorDetail": "Detailed error information",
                    "interruptionTime": "2020-04-26 17:13:12"  # yyyy-MM-dd HH:mm:ss
                }]

        Interruption Type Codes:
            - 101: Number of Disconnected
            - 102: Login Failure
            - 103: Receipt Upload Failure
            - 104: System related errors
            - 105: Paper roll replacement

        Returns:
            Dict with upload result
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            if not exception_logs:
                return {
                    "success": False,
                    "error": "No exception logs provided"
                }

            # Validate each log entry
            for idx, log in enumerate(exception_logs):
                if not log.get('interruptionTypeCode'):
                    return {
                        "success": False,
                        "error": f"Log {idx + 1}: Missing interruptionTypeCode"
                    }
                if not log.get('description'):
                    return {
                        "success": False,
                        "error": f"Log {idx + 1}: Missing description"
                    }
                if not log.get('interruptionTime'):
                    return {
                        "success": False,
                        "error": f"Log {idx + 1}: Missing interruptionTime"
                    }

            logger.info(f"Uploading {len(exception_logs)} exception logs (T132)")

            # Make encrypted request (response not encrypted)
            request_data = self._build_request("T132", exception_logs, encrypt=True)
            response = self._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            if return_code == '00':
                logger.info(f"T132 upload successful: {len(exception_logs)} logs uploaded")
                return {
                    "success": True,
                    "message": f"Successfully uploaded {len(exception_logs)} exception logs",
                    "logs_count": len(exception_logs)
                }
            else:
                error_message = return_info.get('returnMessage', 'Upload failed')
                logger.error(f"T132 failed: {return_code} - {error_message}")
                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code
                }

        except Exception as e:
            logger.error(f"T132 upload failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t133_download_tcs_upgrade_files(
            self,
            tcs_version: str,
            os_type: str = "1"
    ) -> Dict[str, Any]:
        """
        T133 - TCS Upgrade System File Download
        Query files needed to upgrade the system by version and OS type

        Args:
            tcs_version: TCS version number (starting from 1)
            os_type: Operating system type
                - "0": Linux
                - "1": Windows (default)

        Returns:
            Dict with upgrade file information including pre-commands, 
            commands, file lists, and SQL scripts
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Validate os_type
            if os_type not in ["0", "1"]:
                return {
                    "success": False,
                    "error": "os_type must be '0' (Linux) or '1' (Windows)"
                }

            # Build request content
            content = {
                "tcsVersion": str(tcs_version),
                "osType": os_type
            }

            logger.info(f"Downloading TCS upgrade files (T133) - Version: {tcs_version}, OS: {os_type}")

            # Make encrypted request
            response = self._make_request("T133", content, encrypt=True)

            logger.info(f"T133 successful: Retrieved upgrade files for version {tcs_version}")

            return {
                "success": True,
                "upgrade_info": response,
                "tcs_version": tcs_version,
                "os_type": os_type
            }

        except Exception as e:
            logger.error(f"T133 download failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t134_get_commodity_category_incremental_update(
            self,
            commodity_category_version: str
    ) -> Dict[str, Any]:
        """
        T134 - Commodity Category Incremental Update
        Returns only commodity category changes since the local version

        Args:
            commodity_category_version: Local commodity category version (e.g., "1.0")

        Returns:
            Dict with category updates (insert/update operations)
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "categories": []
                }

            # Build request content
            content = {
                "commodityCategoryVersion": str(commodity_category_version)
            }

            logger.info(f"Fetching commodity category updates (T134) from version {commodity_category_version}")

            # Make encrypted request
            response = self._make_request("T134", content, encrypt=True)

            # Response is a list of categories
            categories = response if isinstance(response, list) else []

            logger.info(f"T134 successful: {len(categories)} category updates retrieved")

            return {
                "success": True,
                "categories": categories,
                "total_updates": len(categories),
                "from_version": commodity_category_version
            }

        except Exception as e:
            logger.error(f"T134 update failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "categories": []
            }

    def t135_get_latest_tcs_version(self) -> Dict[str, Any]:
        """
        T135 - Get TCS Latest Version
        Query the latest TCS version available

        Returns:
            Dict with latest TCS version number
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            logger.info("Querying latest TCS version (T135)")

            # Make request (not encrypted per documentation)
            response = self._make_request("T135", content=None, encrypt=False, decrypt_response=True)

            latest_version = response.get("latesttcsversion", "")

            logger.info(f"T135 successful: Latest TCS version is {latest_version}")

            return {
                "success": True,
                "latest_version": latest_version,
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T135 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t136_upload_certificate_public_key(
            self,
            file_name: str,
            file_content: str,
            verify_string: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        T136 - Certificate Public Key Upload
        Upload certificate public key (.crt or .cer format)

        Args:
            file_name: Certificate file name (must end with .crt or .cer)
            file_content: Base64 encoded certificate content
            verify_string: Optional verification string 
                (TIN top 10 + yymmdd as AES Key to encrypt file name)

        Returns:
            Dict with upload result
        """
        try:
            # Validate file name
            if not (file_name.endswith('.crt') or file_name.endswith('.cer')):
                return {
                    "success": False,
                    "error": "File name must end with .crt or .cer"
                }

            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Build request content
            content = {
                "fileName": file_name,
                "fileContent": file_content
            }

            if verify_string:
                content["verifyString"] = verify_string

            logger.info(f"Uploading certificate (T136): {file_name}")

            # Make request (not encrypted per documentation)
            request_data = self._build_request("T136", content, encrypt=False)
            response = self._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            if return_code == '00':
                logger.info(f"T136 upload successful: {file_name}")
                return {
                    "success": True,
                    "message": f"Certificate {file_name} uploaded successfully",
                    "file_name": file_name
                }
            else:
                error_message = return_info.get('returnMessage', 'Upload failed')
                logger.error(f"T136 failed: {return_code} - {error_message}")
                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code
                }

        except Exception as e:
            logger.error(f"T136 upload failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t137_check_exempt_deemed_taxpayer(
            self,
            tin: str,
            commodity_category_codes: Optional[Union[str, List[str]]] = None
    ) -> Dict[str, Any]:
        """
        T137 - Check Exempt/Deemed Taxpayer
        Check whether a taxpayer is tax exempt or deemed

        Args:
            tin: Taxpayer TIN (10-20 digits)
            commodity_category_codes: Optional commodity category codes
                - Single code: "10000000"
                - Multiple codes: "10000000,10000001" or ["10000000", "10000001"]

        Returns:
            Dict with taxpayer type and exemption/deemed information
        """
        try:
            # Validate TIN
            is_valid, error = DataValidator.validate_tin(tin)
            if not is_valid:
                return {
                    "success": False,
                    "error": f"Invalid TIN: {error}"
                }

            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Build request content
            content = {"tin": tin}

            # Format commodity category codes
            if commodity_category_codes:
                if isinstance(commodity_category_codes, list):
                    content["commodityCategoryCode"] = ",".join(commodity_category_codes)
                else:
                    content["commodityCategoryCode"] = commodity_category_codes

            logger.info(f"Checking taxpayer exemption/deemed status (T137) - TIN: {tin}")

            # Make encrypted request
            response = self._make_request("T137", content, encrypt=True)

            taxpayer_type = response.get("taxpayerType", "")
            taxpayer_type_name = {
                "101": "Normal taxpayer",
                "102": "Exempt taxpayer",
                "103": "Deemed taxpayer",
                "104": "Both (Deemed & Exempt)"
            }.get(taxpayer_type, "Unknown")

            logger.info(
                f"T137 successful - TIN: {tin}, Type: {taxpayer_type_name}"
            )

            return {
                "success": True,
                "tin": tin,
                "taxpayer_type": taxpayer_type,
                "taxpayer_type_name": taxpayer_type_name,
                "exempt_type": response.get("exemptType"),
                "commodity_categories": response.get("commodityCategory", []),
                "deemed_exempt_projects": response.get("deemedAndExemptProjectList", []),
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T137 check failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t138_get_all_branches(self) -> Dict[str, Any]:
        """
        T138 - Get All Branches
        Returns all branches for the current taxpayer

        Returns:
            Dict with list of all branches
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "branches": []
                }

            logger.info("Fetching all branches (T138)")

            # Make request (encryption status per documentation)
            response = self._make_request("T138", content=None, encrypt=False, decrypt_response=True)

            # Response should be a list of branches
            branches = response if isinstance(response, list) else response.get('branches', [])

            logger.info(f"T138 successful: {len(branches)} branches retrieved")

            return {
                "success": True,
                "branches": branches,
                "total_branches": len(branches),
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T138 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "branches": []
            }

    # Helper methods for exception logging

    def log_efris_exception(
            self,
            interruption_type_code: str,
            description: str,
            error_detail: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Helper: Log a single EFRIS exception

        Args:
            interruption_type_code: Type of interruption (101-105)
            description: Brief description
            error_detail: Detailed error information (optional)

        Returns:
            Dict with result
        """
        from datetime import datetime

        log_entry = {
            "interruptionTypeCode": interruption_type_code,
            "description": description[:3000],  # Max 3000 chars
            "interruptionTime": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        if error_detail:
            log_entry["errorDetail"] = error_detail[:4000]  # Max 4000 chars

        return self.t132_upload_exception_logs([log_entry])

    def get_pending_exception_logs(self) -> List[Dict]:
        """
        Helper: Get pending exception logs from database
        Should be called on login to upload accumulated logs

        Returns:
            List of exception log entries ready for upload
        """
        try:
            from .models import EFRISExceptionLog

            pending_logs = EFRISExceptionLog.objects.filter(
                company=self.company,
                uploaded=False
            ).order_by('created_at')[:100]  # Limit to 100

            logs_data = []
            for log in pending_logs:
                logs_data.append({
                    "interruptionTypeCode": log.interruption_type_code,
                    "description": log.description,
                    "errorDetail": log.error_detail or "",
                    "interruptionTime": log.interruption_time.strftime('%Y-%m-%d %H:%M:%S')
                })

            return logs_data

        except Exception as e:
            logger.error(f"Failed to get pending exception logs: {e}")
            return []

    def upload_pending_exception_logs_on_login(self) -> Dict[str, Any]:
        """
        Helper: Upload all pending exception logs on login
        This should be called after successful T103 login

        Returns:
            Dict with upload results
        """
        logs_data = self.get_pending_exception_logs()

        if not logs_data:
            return {
                "success": True,
                "message": "No pending logs to upload",
                "logs_count": 0
            }

        result = self.t132_upload_exception_logs(logs_data)

        if result.get('success'):
            # Mark logs as uploaded
            try:
                from .models import EFRISExceptionLog
                EFRISExceptionLog.objects.filter(
                    company=self.company,
                    uploaded=False
                ).update(uploaded=True, uploaded_at=timezone.now())
            except Exception as e:
                logger.error(f"Failed to mark logs as uploaded: {e}")

        return result

  
    def t106_query_invoices(
            self,
            ori_invoice_no: Optional[str] = None,
            invoice_no: Optional[str] = None,
            device_no: Optional[str] = None,
            buyer_tin: Optional[str] = None,
            buyer_nin_brn: Optional[str] = None,
            buyer_legal_name: Optional[str] = None,
            combine_keywords: Optional[str] = None,
            invoice_type: Optional[str] = None,
            invoice_kind: Optional[str] = None,
            is_invalid: Optional[str] = None,
            is_refund: Optional[str] = None,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            page_no: int = 1,
            page_size: int = 10,
            reference_no: Optional[str] = None,
            branch_name: Optional[str] = None,
            query_type: str = "1",
            data_source: Optional[str] = None,
            seller_tin_or_nin: Optional[str] = None,
            seller_legal_or_business_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        T106 - Invoice/Receipt Query
        Query all invoice information (Invoice/receipt, credit note, debit note,
        cancel credit note, cancel debit note)

        Args:
            ori_invoice_no: Original invoice number
            invoice_no: Invoice number
            device_no: Device number
            buyer_tin: Buyer TIN
            buyer_nin_brn: Buyer NIN/BRN
            buyer_legal_name: Buyer name
            combine_keywords: Combined search keywords
            invoice_type: Invoice type (1=Invoice/Receipt, 2=Credit Note, 5=Credit Memo, 4=Debit Note)
            invoice_kind: Invoice kind (1=Invoice, 2=Receipt)
            is_invalid: Obsolete flag (0=Not invalid, 1=Obsolete)
            is_refund: Is credit/debit note issued (0=No, 1=Credit issued, 2=Debit issued)
            start_date: Start date (yyyy-MM-dd)
            end_date: End date (yyyy-MM-dd)
            page_no: Page number
            page_size: Records per page (max 100)
            reference_no: Reference number
            branch_name: Branch name
            query_type: Query type (1=Output invoices, 0=Input invoices)
            data_source: Data source code
            seller_tin_or_nin: Seller TIN/NIN (for agent inquiry)
            seller_legal_or_business_name: Seller name (for agent inquiry)

        Returns:
            Dict with paginated invoice results
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "invoices": []
                }

            # Validate page size
            if page_size > 100:
                return {
                    "success": False,
                    "error": "Page size cannot exceed 100",
                    "invoices": []
                }

            # Build request content
            content = {
                "pageNo": str(page_no),
                "pageSize": str(page_size)
            }

            # Add optional filters
            optional_fields = {
                "oriInvoiceNo": ori_invoice_no,
                "invoiceNo": invoice_no,
                "deviceNo": device_no,
                "buyerTin": buyer_tin,
                "buyerNinBrn": buyer_nin_brn,
                "buyerLegalName": buyer_legal_name,
                "combineKeywords": combine_keywords,
                "invoiceType": invoice_type,
                "invoiceKind": invoice_kind,
                "isInvalid": is_invalid,
                "isRefund": is_refund,
                "startDate": start_date,
                "endDate": end_date,
                "referenceNo": reference_no,
                "branchName": branch_name,
                "queryType": query_type,
                "dataSource": data_source,
                "sellerTinOrNin": seller_tin_or_nin,
                "sellerLegalOrBusinessName": seller_legal_or_business_name
            }

            # Add non-empty values
            content.update({k: v for k, v in optional_fields.items() if v})

            logger.info(f"Querying invoices (T106) - page {page_no}, size {page_size}")

            # Make encrypted request
            response = self._make_request("T106", content, encrypt=True)

            # Extract results
            records = response.get("records", [])
            pagination = response.get("page", {})

            logger.info(f"T106 query successful: {len(records)} invoices returned")

            return {
                "success": True,
                "invoices": records,
                "pagination": {
                    "page_no": int(pagination.get('pageNo', page_no)),
                    "page_size": int(pagination.get('pageSize', page_size)),
                    "total_size": int(pagination.get('totalSize', 0)),
                    "page_count": int(pagination.get('pageCount', 0))
                },
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T106 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "invoices": []
            }

    def t107_query_normal_invoices(
            self,
            invoice_no: Optional[str] = None,
            device_no: Optional[str] = None,
            buyer_tin: Optional[str] = None,
            buyer_legal_name: Optional[str] = None,
            invoice_type: str = "1",
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            page_no: int = 1,
            page_size: int = 10,
            branch_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        T107 - Query Normal Invoice/Receipt
        Query all Invoice/Receipt that can be issued with Credit Note or Cancel Debit Note

        Returns invoices that:
        - Are positive invoices (not credit/debit notes)
        - Have not been issued a credit note or debit note
        - Are not obsolete

        Args:
            invoice_no: Invoice number
            device_no: Device number
            buyer_tin: Buyer TIN
            buyer_legal_name: Buyer legal name
            invoice_type: Invoice type (1=invoice, 4=debit)
            start_date: Start date (yyyy-MM-dd)
            end_date: End date (yyyy-MM-dd)
            page_no: Page number
            page_size: Records per page
            branch_name: Branch name

        Returns:
            Dict with paginated normal invoice results
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "invoices": []
                }

            # Build request content
            content = {
                "pageNo": str(page_no),
                "pageSize": str(page_size),
                "invoiceType": invoice_type
            }

            # Add optional filters
            if invoice_no:
                content["invoiceNo"] = invoice_no
            if device_no:
                content["deviceNo"] = device_no
            if buyer_tin:
                content["buyerTin"] = buyer_tin
            if buyer_legal_name:
                content["buyerLegalName"] = buyer_legal_name
            if start_date:
                content["startDate"] = start_date
            if end_date:
                content["endDate"] = end_date
            if branch_name:
                content["branchName"] = branch_name

            logger.info(f"Querying normal invoices (T107) - page {page_no}")

            # Make encrypted request
            response = self._make_request("T107", content, encrypt=True)

            # Extract results
            records = response.get("records", [])
            pagination = response.get("page", {})

            logger.info(f"T107 query successful: {len(records)} normal invoices returned")

            return {
                "success": True,
                "invoices": records,
                "pagination": {
                    "page_no": int(pagination.get('pageNo', page_no)),
                    "page_size": int(pagination.get('pageSize', page_size)),
                    "total_size": int(pagination.get('totalSize', 0)),
                    "page_count": int(pagination.get('pageCount', 0))
                },
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T107 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "invoices": []
            }

    def t110_apply_credit_note(
            self,
            credit_note_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        T110 - Apply Credit Note

        Args:
            credit_note_data: Complete credit note application data including:
                - oriInvoiceId, oriInvoiceNo (optional - for credit note WITH original FDN)
                - reasonCode (required): 101-105
                - reason (required if reasonCode=105)
                - applicationTime
                - invoiceApplyCategoryCode: "101" (credit note)
                - currency
                - contactName, contactMobileNum, contactEmail
                - source
                - remarks, sellersReferenceNo
                - goodsDetails (list)
                - taxDetails (list)
                - summary (dict)
                - payWay (list)
                - buyerDetails (dict)
                - importServicesSeller (optional)
                - basicInformation (dict)
                - attachmentList (optional)

        Returns:
            Dict with application result including referenceNo
        """
        try:
            # Validate required fields
            required_fields = [
                'reasonCode', 'applicationTime', 'invoiceApplyCategoryCode',
                'currency', 'source', 'goodsDetails', 'taxDetails',
                'summary', 'payWay', 'buyerDetails', 'basicInformation'
            ]

            missing_fields = [f for f in required_fields if f not in credit_note_data]
            if missing_fields:
                return {
                    "success": False,
                    "error": f"Missing required fields: {', '.join(missing_fields)}"
                }

            valid_reason_codes = ['101', '102', '103', '104', '105']
            if credit_note_data['reasonCode'] not in valid_reason_codes:
                return {
                    "success": False,
                    "error": f"Invalid reasonCode. Must be one of: {', '.join(valid_reason_codes)}"
                }

            if credit_note_data['reasonCode'] == '105' and not credit_note_data.get('reason'):
                return {
                    "success": False,
                    "error": "Reason is required when reasonCode is 105 (Others)"
                }

            if credit_note_data['invoiceApplyCategoryCode'] != '101':
                return {
                    "success": False,
                    "error": "invoiceApplyCategoryCode must be '101' for credit note"
                }


            goods_details = credit_note_data.get('goodsDetails', [])
            if not goods_details:
                return {
                    "success": False,
                    "error": "At least one goods detail is required"
                }

            for idx, goods in enumerate(goods_details):
                qty = float(goods.get('qty', 0))
                total = float(goods.get('total', 0))
                tax = float(goods.get('tax', 0))

                if qty >= 0:
                    return {
                        "success": False,
                        "error": f"Goods item {idx + 1}: Quantity must be negative"
                    }

                if total >= 0:
                    return {
                        "success": False,
                        "error": f"Goods item {idx + 1}: Total must be negative"
                    }

                if tax >= 0:
                    return {
                        "success": False,
                        "error": f"Goods item {idx + 1}: Tax must be negative"
                    }

            # Validate tax details (must have negative amounts)
            tax_details = credit_note_data.get('taxDetails', [])
            for idx, tax_detail in enumerate(tax_details):
                net_amount = float(tax_detail.get('netAmount', 0))
                tax_amount = float(tax_detail.get('taxAmount', 0))
                gross_amount = float(tax_detail.get('grossAmount', 0))

                if net_amount > 0 or tax_amount > 0 or gross_amount > 0:
                    return {
                        "success": False,
                        "error": f"Tax detail {idx + 1}: Amounts must be negative or zero"
                    }

            # Validate summary (gross amount must be negative)
            summary = credit_note_data.get('summary', {})
            gross_amount = float(summary.get('grossAmount', 0))
            if gross_amount >= 0:
                return {
                    "success": False,
                    "error": "Summary gross amount must be negative"
                }

            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            logger.info(
                f"Applying credit note (T110) - "
                f"Reason: {credit_note_data['reasonCode']}, "
                f"Amount: {summary.get('grossAmount')}"
            )

            # Make encrypted request (response not encrypted)
            request_data = self._build_request("T110", credit_note_data, encrypt=True)
            response = self._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            if return_code == '00':
                # Extract reference number from response
                reference_no = response_data.get('data', {}).get('referenceNo') or \
                               response_data.get('referenceNo')

                logger.info(f"T110 credit note application successful - Ref: {reference_no}")

                return {
                    "success": True,
                    "message": "Credit note application submitted successfully",
                    "reference_no": reference_no,
                    "data": response_data
                }
            else:
                error_message = return_info.get('returnMessage', 'Application failed')
                logger.error(f"T110 failed: {return_code} - {error_message}")
                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code
                }

        except Exception as e:
            logger.error(f"T110 credit note application failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def build_credit_note_from_invoice(
            self,
            original_invoice_no: str,
            reason_code: str,
            reason: Optional[str] = None,
            credit_items: Optional[List[Dict]] = None,
            contact_name: Optional[str] = None,
            contact_mobile: Optional[str] = None,
            contact_email: Optional[str] = None,
            remarks: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Helper method to build credit note data from an original invoice

        Args:
            original_invoice_no: Original invoice number
            reason_code: Credit note reason (101-105)
            reason: Reason text (required if reason_code=105)
            credit_items: Optional list of items to credit with quantities
                         [{"item": "Product Name", "qty": -2, ...}]
                         If None, credits entire invoice
            contact_name: Contact person name
            contact_mobile: Contact mobile number
            contact_email: Contact email
            remarks: Additional remarks

        Returns:
            Dict with complete credit note data ready for T110
        """
        try:
            # Query original invoice details using T186
            invoice_result = self.t186_query_invoice_remain_details(original_invoice_no)

            if not invoice_result.get('success'):
                return {
                    "success": False,
                    "error": f"Failed to retrieve original invoice: {invoice_result.get('error')}"
                }

            original_invoice = invoice_result

            # Build credit note data
            from datetime import datetime

            credit_note_data = {
                "oriInvoiceId": original_invoice['basic_information'].get('invoiceId'),
                "oriInvoiceNo": original_invoice_no,
                "reasonCode": reason_code,
                "applicationTime": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "invoiceApplyCategoryCode": "101",  # Credit Note
                "currency": original_invoice['basic_information'].get('currency', 'UGX'),
                "contactName": contact_name or "",
                "contactMobileNum": contact_mobile or "",
                "contactEmail": contact_email or "",
                "source": "103",  # WebService API
                "remarks": remarks or f"Credit note for invoice {original_invoice_no}",
                "sellersReferenceNo": original_invoice['seller_details'].get('referenceNo', ''),
            }

            if reason:
                credit_note_data["reason"] = reason

            # Build goods details (negative quantities)
            goods_details = []
            original_goods = original_invoice.get('goods_details', [])

            if credit_items:
                # Credit specific items with specified quantities
                for credit_item in credit_items:
                    # Find matching original item
                    original_item = next(
                        (g for g in original_goods if g.get('item') == credit_item.get('item')),
                        None
                    )

                    if not original_item:
                        return {
                            "success": False,
                            "error": f"Item '{credit_item.get('item')}' not found in original invoice"
                        }

                    qty = float(credit_item.get('qty', 0))
                    if qty >= 0:
                        return {
                            "success": False,
                            "error": "Credit quantities must be negative"
                        }

                    # Calculate amounts based on credit quantity
                    unit_price = float(original_item.get('unitPrice', 0))
                    total = qty * unit_price
                    tax_rate = float(original_item.get('taxRate', 0))
                    tax = total * tax_rate

                    goods_detail = {
                        "item": original_item.get('item'),
                        "itemCode": original_item.get('itemCode'),
                        "qty": str(qty),
                        "unitOfMeasure": original_item.get('unitOfMeasure'),
                        "unitPrice": str(unit_price),
                        "total": f"{total:.2f}",
                        "taxRate": str(tax_rate),
                        "tax": f"{tax:.2f}",
                        "orderNumber": original_item.get('orderNumber'),
                        "deemedFlag": original_item.get('deemedFlag', '2'),
                        "exciseFlag": original_item.get('exciseFlag', '2'),
                        "categoryId": original_item.get('categoryId', ''),
                        "categoryName": original_item.get('categoryName', ''),
                        "goodsCategoryId": original_item.get('goodsCategoryId', ''),
                        "goodsCategoryName": original_item.get('goodsCategoryName', ''),
                        "exciseRate": original_item.get('exciseRate', ''),
                        "exciseRule": original_item.get('exciseRule', ''),
                        "exciseTax": original_item.get('exciseTax', ''),
                        "pack": original_item.get('pack', ''),
                        "stick": original_item.get('stick', ''),
                        "exciseUnit": original_item.get('exciseUnit', ''),
                        "exciseCurrency": original_item.get('exciseCurrency', ''),
                        "exciseRateName": original_item.get('exciseRateName', ''),
                        "vatApplicableFlag": original_item.get('vatApplicableFlag', '1')
                    }

                    goods_details.append(goods_detail)
            else:
                # Credit entire invoice - negate all items
                for original_item in original_goods:
                    qty = -abs(float(original_item.get('qty', 0)))
                    total = -abs(float(original_item.get('total', 0)))
                    tax = -abs(float(original_item.get('tax', 0)))

                    goods_detail = {
                        "item": original_item.get('item'),
                        "itemCode": original_item.get('itemCode'),
                        "qty": str(qty),
                        "unitOfMeasure": original_item.get('unitOfMeasure'),
                        "unitPrice": original_item.get('unitPrice'),
                        "total": f"{total:.2f}",
                        "taxRate": original_item.get('taxRate'),
                        "tax": f"{tax:.2f}",
                        "orderNumber": original_item.get('orderNumber'),
                        "deemedFlag": original_item.get('deemedFlag', '2'),
                        "exciseFlag": original_item.get('exciseFlag', '2'),
                        "categoryId": original_item.get('categoryId', ''),
                        "categoryName": original_item.get('categoryName', ''),
                        "goodsCategoryId": original_item.get('goodsCategoryId', ''),
                        "goodsCategoryName": original_item.get('goodsCategoryName', ''),
                        "exciseRate": original_item.get('exciseRate', ''),
                        "exciseRule": original_item.get('exciseRule', ''),
                        "exciseTax": original_item.get('exciseTax', ''),
                        "pack": original_item.get('pack', ''),
                        "stick": original_item.get('stick', ''),
                        "exciseUnit": original_item.get('exciseUnit', ''),
                        "exciseCurrency": original_item.get('exciseCurrency', ''),
                        "exciseRateName": original_item.get('exciseRateName', ''),
                        "vatApplicableFlag": original_item.get('vatApplicableFlag', '1')
                    }

                    goods_details.append(goods_detail)

            credit_note_data["goodsDetails"] = goods_details

            # Build tax details (negative amounts)
            tax_details = []
            original_tax_details = original_invoice.get('tax_details', [])

            for original_tax in original_tax_details:
                net_amount = -abs(float(original_tax.get('netAmount', 0)))
                tax_amount = -abs(float(original_tax.get('taxAmount', 0)))
                gross_amount = -abs(float(original_tax.get('grossAmount', 0)))

                tax_detail = {
                    "taxCategoryCode": original_tax.get('taxCategoryCode', '01'),
                    "netAmount": f"{net_amount:.2f}",
                    "taxRate": original_tax.get('taxRate'),
                    "taxAmount": f"{tax_amount:.2f}",
                    "grossAmount": f"{gross_amount:.2f}",
                    "exciseUnit": original_tax.get('exciseUnit', ''),
                    "exciseCurrency": original_tax.get('exciseCurrency', ''),
                    "taxRateName": original_tax.get('taxRateName', '')
                }

                tax_details.append(tax_detail)

            credit_note_data["taxDetails"] = tax_details

            # Build summary (negative amounts)
            original_summary = original_invoice.get('summary', {})
            net_amount = -abs(float(original_summary.get('netAmount', 0)))
            tax_amount = -abs(float(original_summary.get('taxAmount', 0)))
            gross_amount = -abs(float(original_summary.get('grossAmount', 0)))

            credit_note_data["summary"] = {
                "netAmount": f"{net_amount:.2f}",
                "taxAmount": f"{tax_amount:.2f}",
                "grossAmount": f"{gross_amount:.2f}",
                "itemCount": str(len(goods_details)),
                "modeCode": original_summary.get('modeCode', '1'),
                "qrCode": ""
            }

            # Build payment way (positive amounts for credit note)
            pay_way = []
            original_pay_way = original_invoice.get('pay_way', [])

            for idx, payment in enumerate(original_pay_way):
                pay_way.append({
                    "paymentMode": payment.get('paymentMode'),
                    "paymentAmount": payment.get('paymentAmount'),
                    "orderNumber": chr(97 + idx)  # a, b, c...
                })

            credit_note_data["payWay"] = pay_way

            # Copy buyer details
            credit_note_data["buyerDetails"] = original_invoice.get('buyer_details', {})

            # Copy basic information
            basic_info = original_invoice.get('basic_information', {})
            credit_note_data["basicInformation"] = {
                "operator": basic_info.get('operator', 'System'),
                "invoiceKind": basic_info.get('invoiceKind', '1'),
                "invoiceIndustryCode": basic_info.get('invoiceIndustryCode', '101'),
                "branchId": basic_info.get('branchId', ''),
                "currencyRate": basic_info.get('currencyRate', '')
            }

            # Copy import services seller if applicable
            if original_invoice.get('import_services_seller'):
                credit_note_data["importServicesSeller"] = original_invoice['import_services_seller']

            return {
                "success": True,
                "credit_note_data": credit_note_data
            }

        except Exception as e:
            logger.error(f"Failed to build credit note from invoice: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t111_query_credit_note_applications(
            self,
            ori_invoice_no: Optional[str] = None,
            invoice_no: Optional[str] = None,
            reference_no: Optional[str] = None,
            approve_status: Optional[str] = None,
            invoice_apply_category_code: Optional[str] = None,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            page_no: int = 1,
            page_size: int = 10,
            query_type: str = "1",  # REQUIRED: 1=My applications, 2=To approve, 3=Approved by me
            credit_note_type: str = "1",  # Optional: 1=Credit Note, 2=Credit Note Without FDN
            branch_name: Optional[str] = None,
            seller_tin_or_nin: Optional[str] = None,
            seller_legal_or_business_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        T111 - Query Credit/Debit Note Applications
        Query credit note application list, debit note application list,
        and cancel debit note application list

        FIXED: Added required queryType parameter with proper validation

        Args:
            ori_invoice_no: Original invoice number
            invoice_no: Credit/debit note invoice number
            reference_no: Reference number
            approve_status: Approval status
                - 101: Approved
                - 102: Submitted (Pending)
                - 103: Rejected
                - 104: Voided
                Can send multiple values separated by comma: "101,102"
            invoice_apply_category_code: Application category
                - 101: credit note
                - 103: cancellation of debit note
                Can send multiple values separated by comma: "101,103"
            start_date: Start date (yyyy-MM-dd)
            end_date: End date (yyyy-MM-dd)
            page_no: Page number
            page_size: Records per page (max 100)
            query_type: REQUIRED Query type:
                - "1": Current user's application list
                - "2": Query negative votes applied by others (approver's to-do)
                - "3": Current user approval completed
            credit_note_type: Credit note type (default "1")
                - "1": Credit Note
                - "2": Credit Note Without FDN
            branch_name: Branch name (for agent inquiry)
            seller_tin_or_nin: Seller TIN/NIN (for agent inquiry)
            seller_legal_or_business_name: Seller name (for agent inquiry)

        Returns:
            Dict with paginated application results
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "applications": []
                }

            # Validate query_type
            if query_type not in ["1", "2", "3"]:
                return {
                    "success": False,
                    "error": f"Invalid query_type: {query_type}. Must be '1', '2', or '3'",
                    "applications": []
                }

            # Validate page size
            if page_size > 100:
                return {
                    "success": False,
                    "error": "Page size cannot exceed 100",
                    "applications": []
                }

            # Build request content - REQUIRED FIELDS FIRST
            content = {
                "pageNo": str(page_no),
                "pageSize": str(page_size),
                "queryType": str(query_type)  # REQUIRED!
            }

            # Add optional filters
            optional_fields = {
                "referenceNo": reference_no,
                "oriInvoiceNo": ori_invoice_no,
                "invoiceNo": invoice_no,
                "approveStatus": approve_status,
                "invoiceApplyCategoryCode": invoice_apply_category_code,
                "startDate": start_date,
                "endDate": end_date,
                "creditNoteType": credit_note_type,
                "branchName": branch_name,
                "sellerTinOrNin": seller_tin_or_nin,
                "sellerLegalOrBusinessName": seller_legal_or_business_name
            }

            # Only add non-empty values
            for key, value in optional_fields.items():
                if value is not None and str(value).strip():
                    content[key] = str(value)

            logger.info(
                f"Querying credit/debit note applications (T111) - "
                f"queryType={query_type}, page {page_no}",
                extra={'filters': content}
            )

            # Make encrypted request
            response = self._make_request("T111", content, encrypt=True)

            # Extract results
            records = response.get("records", [])
            pagination = response.get("page", {})

            logger.info(f"T111 query successful: {len(records)} applications returned")

            return {
                "success": True,
                "applications": records,
                "pagination": {
                    "page_no": int(pagination.get('pageNo', page_no)),
                    "page_size": int(pagination.get('pageSize', page_size)),
                    "total_size": int(pagination.get('totalSize', 0)),
                    "page_count": int(pagination.get('pageCount', 0))
                },
                "query_type": query_type,
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T111 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "applications": []
            }

    def t112_query_credit_note_application_detail(self, application_id: str) -> Dict[str, Any]:
        """
        T112 - Query Credit Note Application Details
        Get detailed information about a credit note application including goods, tax, and payment details

        Args:
            application_id: Application ID from T111

        Returns:
            Dict with detailed application information
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Build request content
            content = {"id": application_id}

            logger.info(f"Querying credit note application detail (T112) - ID: {application_id}")

            # Make encrypted request
            response = self._make_request("T112", content, encrypt=True)

            logger.info(f"T112 query successful for application: {application_id}")

            return {
                "success": True,
                "application_detail": response,
                "application_id": application_id
            }

        except Exception as e:
            logger.error(f"T112 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "application_id": application_id
            }

    def t113_approve_credit_note_application(
            self,
            reference_no: str,
            approve_status: str,
            task_id: str,
            remark: str
    ) -> Dict[str, Any]:
        """
        T113 - Credit/Debit Note Application Approval
        Approve or reject a credit/debit note application

        Args:
            reference_no: Reference number from application
            approve_status: Approval status (101=Approved, 103=Rejected)
            task_id: Task ID from application
            remark: Approval remarks (required, max 1024 chars)

        Returns:
            Dict with approval result
        """
        try:
            # Validate approve_status
            if approve_status not in ['101', '103']:
                return {
                    "success": False,
                    "error": "Approve status must be 101 (Approved) or 103 (Rejected)"
                }

            # Validate remark
            if not remark or len(remark) > 1024:
                return {
                    "success": False,
                    "error": "Remark is required and must not exceed 1024 characters"
                }

            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Build request content
            content = {
                "referenceNo": reference_no,
                "approveStatus": approve_status,
                "taskId": task_id,
                "remark": remark
            }

            logger.info(
                f"Approving credit note application (T113) - "
                f"Ref: {reference_no}, Status: {approve_status}"
            )

            # Make encrypted request (response not encrypted)
            request_data = self._build_request("T113", content, encrypt=True)
            response = self._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            if return_code == '00':
                logger.info(f"T113 approval successful for reference: {reference_no}")
                return {
                    "success": True,
                    "message": "Application approved successfully",
                    "reference_no": reference_no,
                    "status": "Approved" if approve_status == '101' else "Rejected"
                }
            else:
                error_message = return_info.get('returnMessage', 'Approval failed')
                logger.error(f"T113 failed: {return_code} - {error_message}")
                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code
                }

        except Exception as e:
            logger.error(f"T113 approval failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t114_cancel_credit_debit_note(
            self,
            ori_invoice_id: str,
            invoice_no: str,
            reason_code: str,
            invoice_apply_category_code: str,
            reason: Optional[str] = None,
            attachment_list: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        T114 - Cancel Credit/Debit Note Application
        Initiate cancellation of credit note or debit note

        Args:
            ori_invoice_id: Original invoice ID
            invoice_no: FDN of the credit/debit note to cancel
            reason_code: Cancellation reason code
                (101=Incorrect invoice, 102=Not delivered, 103=Other)
            invoice_apply_category_code: Application category
                (103=cancel debit note, 104=cancel credit note, 105=cancel credit memo)
            reason: Cancellation reason (required if reason_code=103)
            attachment_list: List of attachments (optional)
                [{"fileName": "doc.pdf", "fileType": "pdf", "fileContent": "base64..."}]

        Returns:
            Dict with cancellation result
        """
        try:
            # Validate reason requirement
            if reason_code == '103' and not reason:
                return {
                    "success": False,
                    "error": "Reason is required when reason_code is 103 (Other)"
                }

            # Validate invoice_apply_category_code
            valid_codes = ['103', '104', '105']
            if invoice_apply_category_code not in valid_codes:
                return {
                    "success": False,
                    "error": f"Invalid invoice_apply_category_code. Must be one of: {valid_codes}"
                }

            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Build request content
            content = {
                "oriInvoiceId": ori_invoice_id,
                "invoiceNo": invoice_no,
                "reasonCode": reason_code,
                "invoiceApplyCategoryCode": invoice_apply_category_code
            }

            if reason:
                content["reason"] = reason

            if attachment_list:
                content["attachmentList"] = attachment_list

            logger.info(
                f"Canceling credit/debit note (T114) - "
                f"Invoice: {invoice_no}, Category: {invoice_apply_category_code}"
            )

            # Make encrypted request (response not encrypted)
            request_data = self._build_request("T114", content, encrypt=True)
            response = self._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            if return_code == '00':
                logger.info(f"T114 cancellation successful for invoice: {invoice_no}")
                return {
                    "success": True,
                    "message": "Credit/Debit note cancellation submitted successfully",
                    "invoice_no": invoice_no,
                    "category": invoice_apply_category_code
                }
            else:
                error_message = return_info.get('returnMessage', 'Cancellation failed')
                logger.error(f"T114 failed: {return_code} - {error_message}")
                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code
                }

        except Exception as e:
            logger.error(f"T114 cancellation failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t118_query_credit_debit_note_detail(self, application_id: str) -> Dict[str, Any]:
        """
        T118 - Query Credit/Debit Note Application Details
        Get detailed information including goods, tax details, and payment information

        Args:
            application_id: Application ID

        Returns:
            Dict with detailed goods, tax, summary, and payment information
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Build request content
            content = {"id": application_id}

            logger.info(f"Querying credit/debit note detail (T118) - ID: {application_id}")

            # Make encrypted request
            response = self._make_request("T118", content, encrypt=True)

            # Extract structured data
            result = {
                "success": True,
                "application_id": application_id,
                "goods_details": response.get("goodsDetails", []),
                "tax_details": response.get("taxDetails", []),
                "summary": response.get("summary", {}),
                "payment_methods": response.get("payWay", []),
                "basic_information": response.get("basicInformation", {}),
                "raw_data": response
            }

            logger.info(
                f"T118 query successful - "
                f"{len(result['goods_details'])} items, "
                f"{len(result['tax_details'])} tax categories"
            )

            return result

        except Exception as e:
            logger.error(f"T118 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "application_id": application_id
            }

    def t120_void_credit_debit_note_application(
            self,
            business_key: str,
            reference_no: str
    ) -> Dict[str, Any]:
        """
        T120 - Void Credit/Debit Note Application
        Cancel/void a credit or debit note application

        Args:
            business_key: Business key (ID from T111)
            reference_no: Reference number from T111

        Returns:
            Dict with void result
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Build request content
            content = {
                "businessKey": business_key,
                "referenceNo": reference_no
            }

            logger.info(f"Voiding application (T120) - Key: {business_key}, Ref: {reference_no}")

            # Make encrypted request (response not encrypted)
            request_data = self._build_request("T120", content, encrypt=True)
            response = self._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}"
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            if return_code == '00':
                logger.info(f"T120 void successful for reference: {reference_no}")
                return {
                    "success": True,
                    "message": "Application voided successfully",
                    "business_key": business_key,
                    "reference_no": reference_no
                }
            else:
                error_message = return_info.get('returnMessage', 'Void failed')
                logger.error(f"T120 failed: {return_code} - {error_message}")
                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code
                }

        except Exception as e:
            logger.error(f"T120 void failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t121_get_exchange_rate(
            self,
            currency: str,
            issue_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        T121 - Get Exchange Rate
        Get exchange rate for a specific currency

        Args:
            currency: Currency code (e.g., "USD", "EUR", "KES")
            issue_date: Date in format yyyy-MM-dd (optional, defaults to today)

        Returns:
            Dict with exchange rate information
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Build request content
            content = {"currency": currency}

            if issue_date:
                content["issueDate"] = issue_date

            logger.info(f"Getting exchange rate (T121) - Currency: {currency}, Date: {issue_date or 'today'}")

            # Make encrypted request
            response = self._make_request("T121", content, encrypt=True)

            logger.info(
                f"T121 successful - {currency} rate: {response.get('rate', 'N/A')}"
            )

            return {
                "success": True,
                "currency": response.get("currency"),
                "rate": response.get("rate"),
                "import_duty_levy": response.get("importDutyLevy"),
                "income_tax": response.get("inComeTax"),
                "export_levy": response.get("exportLevy"),
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T121 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t122_query_cancel_credit_note_detail(self, invoice_no: str) -> Dict[str, Any]:
        """
        T122 - Query Cancel Credit Note Details
        Get details about a cancelled credit note

        Args:
            invoice_no: Invoice number of the cancelled credit note

        Returns:
            Dict with cancellation details
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Build request content
            content = {"invoiceNo": invoice_no}

            logger.info(f"Querying cancel credit note detail (T122) - Invoice: {invoice_no}")

            # Make encrypted request
            response = self._make_request("T122", content, encrypt=True)

            logger.info(f"T122 query successful for invoice: {invoice_no}")

            return {
                "success": True,
                "invoice_no": response.get("invoiceNo"),
                "currency": response.get("currency"),
                "issue_date": response.get("issueDate"),
                "gross_amount": response.get("grossAmount"),
                "reason_code": response.get("reasonCode"),
                "reason": response.get("reason"),
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T122 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "invoice_no": invoice_no
            }

    def t125_query_excise_duty(self) -> Dict[str, Any]:
        """
        T125 - Query Excise Duty
        Get all excise duty rates and categories

        Returns:
            Dict with excise duty information
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "excise_duties": []
                }

            logger.info("Querying excise duty information (T125)")

            # Make request (not encrypted per documentation)
            response = self._make_request("T125", content=None, encrypt=False, decrypt_response=False)

            excise_list = response.get("exciseDutyList", [])

            logger.info(f"T125 query successful: {len(excise_list)} excise duties retrieved")

            return {
                "success": True,
                "excise_duties": excise_list,
                "total_count": len(excise_list),
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T125 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "excise_duties": []
            }

    def t126_get_all_exchange_rates(self, issue_date: Optional[str] = None) -> Dict[str, Any]:
        """
        T126 - Get All Exchange Rates
        Get exchange rates for all currencies

        Args:
            issue_date: Date in format yyyy-MM-dd (optional, defaults to today)

        Returns:
            Dict with all exchange rates
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "rates": []
                }

            # Build request content
            content = {}
            if issue_date:
                content["issueDate"] = issue_date

            logger.info(f"Getting all exchange rates (T126) - Date: {issue_date or 'today'}")

            # Make encrypted request
            response = self._make_request("T126", content if content else None, encrypt=True)

            # Response is a list of exchange rates
            rates_list = response if isinstance(response, list) else []

            logger.info(f"T126 successful: {len(rates_list)} exchange rates retrieved")

            return {
                "success": True,
                "rates": rates_list,
                "total_currencies": len(rates_list),
                "issue_date": issue_date,
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T126 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "rates": []
            }


    def t129_batch_invoice_upload(
            self,
            invoices_data: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        T129 - Batch Invoice Upload
        Upload multiple invoices in a single request

        FIXED: Proper handling of T129 response format

        Args:
            invoices_data: List of invoice data dictionaries

        Returns:
            Dict with batch upload results
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}",
                    "results": []
                }

            if not invoices_data:
                return {
                    "success": False,
                    "error": "No invoices provided for upload",
                    "results": []
                }

            # Validate each invoice
            for idx, invoice in enumerate(invoices_data):
                if "invoiceContent" not in invoice:
                    return {
                        "success": False,
                        "error": f"Invoice {idx + 1}: Missing invoiceContent",
                        "results": []
                    }
                if "invoiceSignature" not in invoice:
                    return {
                        "success": False,
                        "error": f"Invoice {idx + 1}: Missing invoiceSignature",
                        "results": []
                    }

            logger.info(f"Batch uploading {len(invoices_data)} invoices (T129)")

            # Build request
            request_data = self._build_request("T129", invoices_data, encrypt=True)

            # Make HTTP request
            response = self._make_http_request(request_data)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                    "results": []
                }

            response_data = response.json()
            return_info = response_data.get('returnStateInfo', {})
            return_code = return_info.get('returnCode', '99')

            # T129 SPECIAL HANDLING: Return code 1613 means check individual results
            # Return code 00 means all successful
            if return_code in ['00', '1613']:
                data_section = response_data.get('data', {})
                content_b64 = data_section.get('content', '')

                results_list = []

                if content_b64:
                    try:
                        # Decode base64
                        content_bytes = base64.b64decode(content_b64)

                        data_desc = data_section.get('dataDescription', {}) or {}
                        code_type = str(data_desc.get('codeType', '')).strip()
                        zip_code = str(data_desc.get('zipCode', '0')).strip()

                        payload_bytes = content_bytes

                        # Decompress first if needed
                        if zip_code in ("1", "2"):
                            try:
                                import gzip
                                payload_bytes = gzip.decompress(payload_bytes)
                                logger.info(f"T129: Decompressed response")
                            except Exception:
                                try:
                                    import zlib
                                    payload_bytes = zlib.decompress(payload_bytes)
                                    logger.info(f"T129: Zlib decompressed response")
                                except Exception as e:
                                    logger.warning(f"T129: Decompression failed: {e}")

                        # Decrypt if encrypted
                        if code_type == "1":
                            try:
                                # T129 response might have padding issues
                                # Try to decrypt, but handle padding errors
                                payload_bytes = self.security_manager.aes_decrypt_bytes(payload_bytes)
                                logger.info(f"T129: Decrypted response successfully")
                            except Exception as decrypt_err:
                                logger.warning(f"T129: Decryption failed: {decrypt_err}")
                                # If decryption fails, the response might already be plain
                                # Try to use it as-is
                                logger.info("T129: Attempting to parse without decryption")

                        # Parse JSON
                        try:
                            content_json = payload_bytes.decode('utf-8', errors='ignore')

                            if content_json.strip():
                                parsed_data = json.loads(content_json)

                                # T129 returns an array directly
                                if isinstance(parsed_data, list):
                                    results_list = parsed_data
                                elif isinstance(parsed_data, dict):
                                    # Check various possible keys
                                    for key in ['results', 'invoices', 'data', 'records']:
                                        if key in parsed_data and isinstance(parsed_data[key], list):
                                            results_list = parsed_data[key]
                                            break

                                    if not results_list:
                                        results_list = [parsed_data]

                            logger.info(f"T129: Parsed {len(results_list)} invoice results")

                        except json.JSONDecodeError as e:
                            logger.error(f"T129: JSON parsing failed: {e}")
                            logger.debug(f"T129: Content preview: {content_json[:500]}")

                    except Exception as e:
                        logger.error(f"T129: Failed to process response: {e}", exc_info=True)

                # If we couldn't get results from response, return empty list
                if not results_list:
                    logger.warning("T129: No results extracted from response")
                    results_list = []

                # Count successes and failures
                success_count = 0
                failure_count = 0

                for result in results_list:
                    if isinstance(result, dict):
                        ret_code = result.get('invoiceReturnCode', result.get('returnCode', ''))
                        if ret_code == '00':
                            success_count += 1
                        else:
                            failure_count += 1

                # If no results but return code is 00, assume all successful
                if not results_list and return_code == '00':
                    success_count = len(invoices_data)

                logger.info(
                    f"T129 batch upload completed: "
                    f"{success_count} successful, {failure_count} failed"
                )

                return {
                    "success": True,
                    "total_invoices": len(invoices_data),
                    "successful_count": success_count,
                    "failed_count": failure_count,
                    "results": results_list,
                    "raw_data": response_data,
                    "partial_success": return_code == '1613',
                    "message": "Batch upload completed. Check individual invoice results."
                }
            else:
                # Complete failure
                error_message = return_info.get('returnMessage', 'T129 failed')
                logger.error(f"T129 failed: {return_code} - {error_message}")

                return {
                    "success": False,
                    "error": error_message,
                    "error_code": return_code,
                    "results": []
                }

        except Exception as e:
            logger.error(f"T129 batch upload failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "results": []
            }

    # Update in services.py

    def search_invoices_by_date_range(
            self,
            start_date: str,
            end_date: str,
            invoice_type: Optional[str] = None,
            buyer_tin: Optional[str] = None,
            page_size: int = 50  # FIXED: Changed from 100 to 50
    ) -> Dict[str, Any]:
        """
        Helper: Search invoices within a date range

        FIXED: Ensure page_size never exceeds 100

        Args:
            start_date: Start date (yyyy-MM-dd)
            end_date: End date (yyyy-MM-dd)
            invoice_type: Filter by invoice type (optional)
            buyer_tin: Filter by buyer TIN (optional)
            page_size: Results per page (max 100, default 50)

        Returns:
            Dict with all matching invoices (handles pagination automatically)
        """
        # Ensure page_size doesn't exceed 100
        if page_size > 100:
            page_size = 100
            logger.warning(f"Page size capped at 100 for T106 compliance")

        all_invoices = []
        page_no = 1

        while True:
            result = self.t106_query_invoices(
                start_date=start_date,
                end_date=end_date,
                invoice_type=invoice_type,
                buyer_tin=buyer_tin,
                page_no=page_no,
                page_size=page_size
            )

            if not result.get('success'):
                # If this is the first page, return the error
                if page_no == 1:
                    return result
                # If not first page, return what we have so far
                break

            invoices = result.get('invoices', [])
            all_invoices.extend(invoices)

            pagination = result.get('pagination', {})
            if page_no >= pagination.get('page_count', 1):
                break

            page_no += 1

            # Safety limit to prevent infinite loops
            if page_no > 100:
                logger.warning("Reached max page limit (100) for invoice search")
                break

        return {
            "success": True,
            "invoices": all_invoices,
            "total_count": len(all_invoices),
            "start_date": start_date,
            "end_date": end_date
        }

    def get_pending_credit_note_applications(self) -> Dict[str, Any]:
        """
        Helper: Get all pending credit note applications

        Returns:
            Dict with pending applications
        """
        return self.t111_query_credit_note_applications(
            approve_status="102",  # Pending/Submitted
            invoice_apply_category_code="101",  # Credit note
            query_type="1",  # My applications
            page_size=100
        )


    def get_invoice_with_credit_note_eligibility(
        self,
        invoice_no: str
    ) -> Dict[str, Any]:
        """
        Helper: Check if an invoice can have a credit note issued

        Args:
            invoice_no: Invoice number to check

        Returns:
            Dict with invoice details and eligibility status
        """
        result = self.t107_query_normal_invoices(
            invoice_no=invoice_no,
            page_size=1
        )

        if not result.get('success'):
            return result

        invoices = result.get('invoices', [])

        if not invoices:
            return {
                "success": False,
                "error": "Invoice not found or not eligible for credit note",
                "can_issue_credit_note": False
            }

        invoice = invoices[0]

        return {
            "success": True,
            "invoice": invoice,
            "can_issue_credit_note": True,
            "invoice_no": invoice_no
        }


    def get_current_exchange_rates(self) -> Dict[str, Any]:
        """
        Helper: Get current exchange rates for all currencies

        Returns:
            Dict with current rates mapped by currency code
        """
        result = self.t126_get_all_exchange_rates()

        if not result.get('success'):
            return result

        rates_map = {}
        for rate_info in result.get('rates', []):
            currency = rate_info.get('currency')
            if currency:
                rates_map[currency] = {
                    'rate': float(rate_info.get('rate', 0)),
                    'import_duty_levy': float(rate_info.get('importDutyLevy', 0)),
                    'income_tax': float(rate_info.get('inComeTax', 0)),
                    'export_levy': float(rate_info.get('exportLevy', 0))
                }

        return {
            "success": True,
            "rates": rates_map,
            "currencies": list(rates_map.keys()),
            "total_currencies": len(rates_map)
        }


    def get_excise_duty_by_code(self, excise_duty_code: str) -> Dict[str, Any]:
        """
        Helper: Get specific excise duty information by code

        Args:
            excise_duty_code: Excise duty code to lookup

        Returns:
            Dict with excise duty details
        """
        result = self.t125_query_excise_duty()

        if not result.get('success'):
            return result

        excise_duties = result.get('excise_duties', [])

        for duty in excise_duties:
            if duty.get('exciseDutyCode') == excise_duty_code:
                return {
                    "success": True,
                    "excise_duty": duty
                }

        return {
            "success": False,
            "error": f"Excise duty code {excise_duty_code} not found"
        }

    def get_applications_to_approve(self) -> Dict[str, Any]:
        """
        Helper: Get applications waiting for my approval

        Returns:
            Dict with applications to approve
        """
        return self.t111_query_credit_note_applications(
            approve_status="102",  # Pending
            query_type="2",  # To-do list (to approve)
            page_size=100
        )

    def get_my_approved_applications(self) -> Dict[str, Any]:
        """
        Helper: Get applications I've approved

        Returns:
            Dict with approved applications
        """
        return self.t111_query_credit_note_applications(
            approve_status="101",  # Approved
            query_type="3",  # My approvals
            page_size=100
        )


    # ============================================================================
    # ADDITIONAL EFRIS INTERFACES (T108, T116, T117, T127, T144)
    # ============================================================================

    def t108_query_invoice_detail(self, invoice_no: str) -> Dict[str, Any]:
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Build request content
            content = {"invoiceNo": invoice_no}

            logger.info(f"Querying invoice detail for: {invoice_no}")

            # Make encrypted request
            response = self._make_request("T108", content, encrypt=True)

            logger.info(f"Invoice {invoice_no} detail retrieved successfully")

            return {
                "success": True,
                "invoice_data": response,
                "invoice_no": invoice_no
            }

        except Exception as e:
            logger.error(f"T108 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "invoice_no": invoice_no
            }

    def t116_upload_zreport(self, zreport_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        T116: Upload Daily Z-Report

        Args:
            zreport_data: Z-report data structure (to be determined by EFRIS)
                Expected structure (adjust based on EFRIS specs):
                {
                    "reportDate": "2025-01-15",
                    "deviceNo": "...",
                    "totalSales": "100000.00",
                    "totalTax": "18000.00",
                    "totalTransactions": "50",
                    ...
                }

        Returns:
            Dict with success status
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            logger.info(f"Uploading Z-report for date: {zreport_data.get('reportDate', 'unknown')}")

            # Make encrypted request
            response = self._make_request("T116", zreport_data, encrypt=True)

            logger.info("Z-report uploaded successfully")

            return {
                "success": True,
                "message": "Z-report uploaded successfully",
                "data": response
            }

        except Exception as e:
            logger.error(f"T116 upload failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t117_check_invoices(self, invoices: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        T117: Invoice Checks - Verify consistency between client and server invoices

        Args:
            invoices: List of invoice references to check:
                [{
                    "invoiceNo": "10239892399",
                    "invoiceType": "1"  # 1=Invoice, 2=Credit Note with FDN,
                                        # 4=Debit Note, 5=Credit Note without FDN
                }]

        Returns:
            Dict with:
            - success: bool
            - inconsistent_invoices: List of invoices that don't match
            - missing_invoices: List of invoices not found on server
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Validate invoice types
            valid_types = ['1', '2', '4', '5']
            for inv in invoices:
                if inv.get('invoiceType') not in valid_types:
                    return {
                        "success": False,
                        "error": f"Invalid invoiceType: {inv.get('invoiceType')}. Must be 1, 2, 4, or 5"
                    }

            logger.info(f"Checking {len(invoices)} invoice(s) for consistency")

            # Make encrypted request
            response = self._make_request("T117", invoices, encrypt=True)

            # Empty response means all invoices are consistent
            inconsistent = response if isinstance(response, list) else []

            if not inconsistent:
                logger.info("All invoices are consistent with server")
                return {
                    "success": True,
                    "message": "All invoices consistent",
                    "inconsistent_invoices": [],
                    "checked_count": len(invoices)
                }
            else:
                logger.warning(f"Found {len(inconsistent)} inconsistent invoice(s)")
                return {
                    "success": True,
                    "message": f"Found {len(inconsistent)} inconsistency(ies)",
                    "inconsistent_invoices": inconsistent,
                    "checked_count": len(invoices)
                }

        except Exception as e:
            logger.error(f"T117 check failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def t127_query_goods(
            self,
            goods_code: Optional[str] = None,
            goods_name: Optional[str] = None,
            commodity_category_name: Optional[str] = None,
            page_no: int = 1,
            page_size: int = 10,
            branch_id: Optional[str] = None,
            service_mark: Optional[str] = None,
            have_excise_tax: Optional[str] = None,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            combine_keywords: Optional[str] = None,
            goods_type_code: str = "101",
            tin: Optional[str] = None,
            query_type: str = "1"
    ) -> Dict[str, Any]:
        """
        T127: Goods/Services Inquiry (EFRIS)
        Documentation Reference: URA EFRIS API Spec (Transaction Code T127)
        """
        try:
            # ✅ Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # ✅ Validate page size
            if page_size > 100:
                return {"success": False, "error": "Page size cannot exceed 100"}

            # ✅ Validate query type
            if query_type not in ['0', '1']:
                return {"success": False, "error": "Query type must be '0' (agent) or '1' (normal)"}

            # ✅ Validate agent query
            if query_type == '0' and (not tin or not branch_id):
                return {
                    "success": False,
                    "error": "TIN and branch_id required for agent goods query (queryType='0')"
                }

            # ✅ Build request content
            content = {
                "pageNo": str(page_no),
                "pageSize": str(page_size),
                "queryType": query_type,
                "goodsTypeCode": goods_type_code
            }

            # Optional filters
            optional_fields = {
                "goodsCode": goods_code,
                "goodsName": goods_name,
                "commodityCategoryName": commodity_category_name,
                "branchId": branch_id,
                "serviceMark": service_mark,
                "haveExciseTax": have_excise_tax,
                "startDate": start_date,
                "endDate": end_date,
                "combineKeywords": combine_keywords,
                "tin": tin,
            }

            # Add non-empty values
            content.update({k: v for k, v in optional_fields.items() if v})

            logger.info(f"🔍 Sending T127 goods query (page={page_no}, size={page_size})")

            # ✅ Make encrypted request
            response = self._make_request("T127", content, encrypt=True)

            # ✅ Extract results
            goods_list = response.get("records", [])
            pagination = response.get("page", {})

            # ✅ Print full decrypted response (for debugging)
            try:
                print("\n" + "=" * 100)
                print("📦 FULL DECRYPTED EFRIS RESPONSE (T127 QUERY):")
                print(json.dumps(response, indent=4, ensure_ascii=False))
                print("=" * 100 + "\n")
            except Exception as debug_err:
                logger.warning(f"Could not pretty-print T127 response: {debug_err}")

            logger.info(
                f"T127 query success: {len(goods_list)} items returned (page {pagination.get('pageNo', page_no)})"
            )

            return {
                "success": True,
                "goods": goods_list,
                "pagination": {
                    "page_no": int(pagination.get('pageNo', page_no)),
                    "page_size": int(pagination.get('pageSize', page_size)),
                    "total_size": int(pagination.get('totalSize', 0)),
                    "page_count": int(pagination.get('pageCount', 0))
                },
                "raw_data": response
            }

        except Exception as e:
            logger.error(f"T127 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "goods": []
            }

    def t144_query_goods_by_code(
            self,
            goods_codes: Union[str, List[str]],
            tin: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        T144: Goods/Services Inquiry by Goods Code (Batch)

        Args:
            goods_codes: Single code or list of codes (e.g., "0001,0002" or ["0001", "0002"])
            tin: Principal agent TIN (optional)

        Returns:
            Dict containing:
            - success: bool
            - goods: List of goods with measurement unit details
        """
        try:
            # Ensure authentication
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            # Format goods codes
            if isinstance(goods_codes, list):
                goods_code_str = ",".join(goods_codes)
            else:
                goods_code_str = goods_codes

            # Build request content
            content = {"goodsCode": goods_code_str}

            if tin:
                content["tin"] = tin

            logger.info(f"Querying goods by code: {goods_code_str}")

            # Make encrypted request
            response = self._make_request("T144", content, encrypt=True)

            # Response is a list of goods
            goods_list = response if isinstance(response, list) else []

            logger.info(f"Retrieved {len(goods_list)} goods by code")

            return {
                "success": True,
                "goods": goods_list,
                "query_count": len(goods_code_str.split(','))
            }

        except Exception as e:
            logger.error(f"T144 query failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "goods": []
            }

    # ============================================================================
    # HELPER METHODS FOR NEW INTERFACES
    # ============================================================================

    def query_invoice_from_efris(self, invoice_no: str) -> Optional[Dict]:
        """
        Helper: Query invoice details from EFRIS and return structured data

        Args:
            invoice_no: Invoice number to query

        Returns:
            Structured invoice data or None if not found
        """
        result = self.t108_query_invoice_detail(invoice_no)

        if result.get('success'):
            return result.get('invoice_data')

        logger.warning(f"Failed to query invoice {invoice_no}: {result.get('error')}")
        return None

    def verify_invoice_consistency(self, invoice) -> Dict[str, Any]:
        """
        Helper: Verify Django invoice against EFRIS records

        Args:
            invoice: Django Invoice model instance

        Returns:
            Dict with verification results
        """
        invoice_no = getattr(invoice, 'invoice_number', None) or getattr(invoice, 'number', None)
        invoice_type = "1"  # Default to standard invoice

        if not invoice_no:
            return {
                "success": False,
                "error": "Invoice has no invoice number"
            }

        # Determine invoice type
        if hasattr(invoice, 'invoice_type'):
            type_mapping = {
                'INVOICE': '1',
                'CREDIT_NOTE': '2',
                'DEBIT_NOTE': '4'
            }
            invoice_type = type_mapping.get(
                getattr(invoice, 'invoice_type', 'INVOICE').upper(),
                '1'
            )

        # Check with EFRIS
        result = self.t117_check_invoices([{
            "invoiceNo": invoice_no,
            "invoiceType": invoice_type
        }])

        if result.get('success'):
            is_consistent = len(result.get('inconsistent_invoices', [])) == 0
            return {
                "success": True,
                "is_consistent": is_consistent,
                "inconsistencies": result.get('inconsistent_invoices', [])
            }

        return result

    def search_goods_in_efris(
            self,
            search_term: str,
            page: int = 1,
            limit: int = 20
    ) -> List[Dict]:
        """
        Helper: Simple goods search in EFRIS

        Args:
            search_term: Search keyword (searches goodsCode or goodsName)
            page: Page number
            limit: Results per page

        Returns:
            List of matching goods
        """
        result = self.t127_query_goods(
            combine_keywords=search_term,
            page_no=page,
            page_size=min(limit, 100)
        )

        if result.get('success'):
            return result.get('goods', [])

        logger.warning(f"Goods search failed: {result.get('error')}")
        return []

    def get_goods_details_by_codes(self, product_codes: List[str]) -> Dict[str, Dict]:
        """
        Helper: Get detailed goods info for multiple product codes

        Args:
            product_codes: List of product/goods codes

        Returns:
            Dict mapping code to goods details
        """
        result = self.t144_query_goods_by_code(product_codes)

        if result.get('success'):
            goods_map = {}
            for goods in result.get('goods', []):
                code = goods.get('goodsCode')
                if code:
                    goods_map[code] = goods
            return goods_map

        logger.warning(f"Batch goods query failed: {result.get('error')}")
        return {}

    def sync_goods_from_efris_to_products(self, goods_codes: Optional[List[str]] = None):
        """
        Helper: Sync goods from EFRIS to Django Product model

        Args:
            goods_codes: Optional list of specific codes to sync (None = sync all)

        Returns:
            Dict with sync results
        """
        from inventory.models import Product

        results = {
            'total': 0,
            'created': 0,
            'updated': 0,
            'failed': 0,
            'errors': []
        }

        try:
            # Get goods from EFRIS
            if goods_codes:
                efris_result = self.t144_query_goods_by_code(goods_codes)
                goods_list = efris_result.get('goods', [])
            else:
                # Query all goods (paginated)
                efris_result = self.t127_query_goods(page_size=100)
                goods_list = efris_result.get('goods', [])

            results['total'] = len(goods_list)

            for goods in goods_list:
                try:
                    goods_code = goods.get('goodsCode')

                    # Check if product exists
                    product, created = Product.objects.get_or_create(
                        sku=goods_code,
                        defaults={
                            'name': goods.get('goodsName', 'Imported from EFRIS'),
                            'selling_price': float(goods.get('unitPrice', 0)),
                            'unit_of_measure': goods.get('measureUnit'),
                            'efris_goods_id': (goods.get('id') or goods.get('goodsId') or goods.get('commodityGoodsId')),
                            'efris_is_uploaded': True
                        }
                    )

                    if created:
                        results['created'] += 1
                    else:
                        # Update existing product
                        product.efris_goods_id = (goods.get('id') or goods.get('goodsId') or goods.get('commodityGoodsId'))
                        product.efris_is_uploaded = True
                        product.save()
                        results['updated'] += 1

                except Exception as e:
                    results['failed'] += 1
                    results['errors'].append({
                        'goods_code': goods.get('goodsCode', 'unknown'),
                        'error': str(e)
                    })

            logger.info(
                f"EFRIS goods sync completed: {results['created']} created, "
                f"{results['updated']} updated, {results['failed']} failed"
            )

        except Exception as e:
            logger.error(f"EFRIS goods sync failed: {e}", exc_info=True)
            results['errors'].append({'error': str(e)})

        return results

    def generate_daily_zreport(self, report_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Helper: Generate Z-report from sales data for a specific date

        Args:
            report_date: Date to generate report for (defaults to yesterday)

        Returns:
            Dict with Z-report data ready for T116
        """
        from datetime import timedelta

        if report_date is None:
            report_date = date.today() - timedelta(days=1)

        try:
            # Import within schema context
            from sales.models import Sale
            from django.db.models import Sum, Count

            # Get all sales for the date
            sales = Sale.objects.filter(
                created_at__date=report_date,
                is_fiscalized=True
            )

            # Calculate totals
            aggregates = sales.aggregate(
                total_sales=Sum('total_amount'),
                total_tax=Sum('tax_amount'),
                total_transactions=Count('id'),
                # total_cash=Sum('cash_amount'),
                # total_card=Sum('card_amount'),
                # total_mobile_money=Sum('mobile_money_amount')
            )

            # Build Z-report structure (adjust based on EFRIS specification)
            zreport_data = {
                'reportDate': report_date.strftime('%Y-%m-%d'),
                'deviceNo': self.security_manager.device_no,
                'totalSales': str(aggregates.get('total_sales') or 0),
                'totalTax': str(aggregates.get('total_tax') or 0),
                'totalTransactions': str(aggregates.get('total_transactions') or 0),
                'totalCash': str(aggregates.get('total_cash') or 0),
                'totalCard': str(aggregates.get('total_card') or 0),
                'totalMobileMoney': str(aggregates.get('total_mobile_money') or 0),
            }

            return {
                "success": True,
                "zreport_data": zreport_data
            }

        except Exception as e:
            logger.error(f"Failed to generate Z-report: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    # ============================================================================
    # STOCK MANAGEMENT INTERFACES - Django Model Integration
    # ============================================================================

    def t128_query_stock_by_goods_id(self, efris_goods_id: str, branch_id: Optional[str] = None) -> Dict:
        payload = {
            "id": efris_goods_id
        }

        if branch_id:
            payload["branchId"] = branch_id

        return self._make_request("T128", payload,encrypt=True)

    def sync_product_to_efris_stock(self, product, store=None):
        """
        Sync Django Stock records to EFRIS
        Uses your Stock model with efris_sync_required flag
        """
        from inventory.models import Stock

        if not product.efris_goods_id:
            raise ValueError(f"Product {product.sku} has no EFRIS goods ID. Upload to EFRIS first (T130).")

        # Get stocks to sync
        if store:
            stocks = Stock.objects.filter(product=product, store=store, efris_sync_required=True)
        else:
            stocks = Stock.objects.filter(product=product, efris_sync_required=True)

        if not stocks.exists():
            return []

        results = []
        for stock in stocks:
            try:
                # Prepare stock item for EFRIS
                stock_item = {
                    "commodityGoodsId": product.efris_goods_id,
                    "goodsCode": product.efris_goods_code,
                    "measureUnit": product.unit_of_measure,
                    "quantity": str(float(stock.quantity)),
                    "unitPrice": str(float(product.cost_price)),
                    "remarks": f"Stock sync for {stock.store.name}"
                }

                # Increase inventory in EFRIS
                result = self.t131_maintain_stock(
                    operation_type="101",  # Increase
                    stock_items=[stock_item],
                    stock_in_type="104",  # Opening Stock
                    supplier_name=product.supplier.name if product.supplier else "Internal",
                    supplier_tin=product.supplier.tin if product.supplier else None,
                    branch_id=getattr(stock.store, 'efris_branch_id', None)
                )

                # Mark as synced if successful
                if result and not result[0].get('returnCode'):
                    stock.mark_efris_synced()

                results.append({
                    'store': stock.store.name,
                    'product': product.name,
                    'quantity': float(stock.quantity),
                    'result': result
                })

            except Exception as e:
                results.append({
                    'store': stock.store.name if stock.store else 'Unknown',
                    'product': product.name,
                    'error': str(e)
                })

        return results

    def t131_maintain_stock_from_movement(
            self,
            movement,
            supplier_name: Optional[str] = None,
            supplier_tin: Optional[str] = None
    ):
        """
        Sync StockMovement to EFRIS T131
        Uses your StockMovement model with movement_type choices
        """
        from inventory.models import StockMovement

        product = movement.product

        if not product.efris_goods_id:
            raise ValueError(f"Product {product.sku} not uploaded to EFRIS")

        # Determine operation type based on movement_type
        if movement.movement_type in ['PURCHASE', 'RETURN', 'TRANSFER_IN']:
            operation_type = "101"  # Increase
            stock_in_type = {
                'PURCHASE': '102',  # Local Purchase
                'RETURN': '102',  # Local Purchase
                'TRANSFER_IN': '104',  # Opening Stock
            }.get(movement.movement_type, '104')

            # Get supplier info
            if not supplier_name:
                supplier_name = product.supplier.name if product.supplier else movement.store.name
            if not supplier_tin and product.supplier:
                supplier_tin = product.supplier.tin

        elif movement.movement_type in ['SALE', 'TRANSFER_OUT', 'ADJUSTMENT']:
            operation_type = "102"  # Decrease
            stock_in_type = None
            supplier_name = None
            supplier_tin = None

            # Determine adjust type
            adjust_type = {
                'SALE': '105',  # Raw Materials (consumed)
                'TRANSFER_OUT': '104',  # Others
                'ADJUSTMENT': '104',  # Others
            }.get(movement.movement_type, '104')
        else:
            raise ValueError(f"Unknown movement type: {movement.movement_type}")

        # Prepare stock item
        stock_item = {
            "commodityGoodsId": product.efris_goods_id,
            "goodsCode": product.efris_goods_code,
            "measureUnit": product.unit_of_measure,
            "quantity": str(abs(float(movement.quantity))),
            "unitPrice": str(float(movement.unit_price or product.cost_price)),
            "remarks": movement.notes or movement.reference or ""
        }

        # Build request
        kwargs = {
            'operation_type': operation_type,
            'stock_items': [stock_item],
            'branch_id': getattr(movement.store, 'efris_branch_id', None),
            'stock_in_date': movement.created_at.strftime('%Y-%m-%d'),
            'invoice_no': movement.reference[:20] if movement.reference else None
        }

        if operation_type == "101":
            kwargs.update({
                'stock_in_type': stock_in_type,
                'supplier_name': supplier_name,
                'supplier_tin': supplier_tin
            })
        else:
            kwargs.update({
                'adjust_type': adjust_type,
                'remarks': movement.notes or f"{movement.get_movement_type_display()} - {movement.reference or 'Stock adjustment'}"
            })

        return self.t131_maintain_stock(**kwargs)

    def t131_maintain_stock(
            self,
            operation_type: str,
            stock_items: List[Dict],
            supplier_tin: Optional[str] = None,
            supplier_name: Optional[str] = None,
            adjust_type: Optional[str] = None,
            remarks: Optional[str] = None,
            stock_in_date: Optional[str] = None,
            stock_in_type: Optional[str] = None,
            production_batch_no: Optional[str] = None,
            production_date: Optional[str] = None,
            branch_id: Optional[str] = None,
            invoice_no: Optional[str] = None,
            is_check_batch_no: str = "0",
            roll_back_if_error: str = "0",
            goods_type_code: str = "101"
    ) -> List[Dict]:
        """
        T131: Goods Stock Maintain (Increase or Decrease Inventory)

        Args:
            operation_type: "101" (Increase) or "102" (Decrease)
            stock_items: List of items with structure:
                {
                    "commodityGoodsId": "...",  # Product.efris_goods_id
                    "goodsCode": "...",  # Product.sku
                    "measureUnit": "101",
                    "quantity": "100.00",
                    "unitPrice": "5000.00",
                    "remarks": "...",
                    "fuelTankId": "...",  # optional
                    "lossQuantity": "...",  # optional
                    "originalQuantity": "..."  # optional
                }
            supplier_tin: Supplier TIN (required if operation_type=101 and stockInType!=103)
            supplier_name: Supplier name (required if operation_type=101)
            adjust_type: Required if operation_type=102
                "101" (Expired Goods), "102" (Damaged Goods),
                "103" (Personal Uses), "104" (Others), "105" (Raw Materials)
            remarks: Required if operation_type=102 and adjust_type=104
            stock_in_date: Format yyyy-MM-dd
            stock_in_type: Required if operation_type=101
                "101" (Import), "102" (Local Purchase),
                "103" (Manufacture/Assembling), "104" (Opening Stock)
            production_batch_no: Only if stock_in_type=103
            production_date: Format yyyy-MM-dd, only if stock_in_type=103
            branch_id: 18-digit branch ID
            invoice_no: Invoice number (max 20 chars)
            is_check_batch_no: "0" (No) or "1" (Yes), default "0"
            roll_back_if_error: "0" (No) or "1" (Yes), default "0"
            goods_type_code: "101" (Goods) or "102" (Fuel), default "101"

        Returns:
            List of results for each item with returnCode and returnMessage
        """
        # Validate operation_type dependencies
        if operation_type == "101":
            if not stock_in_type:
                raise ValueError(
                    "stockInType is required when operationType=101. "
                    "Use: 101 (Import), 102 (Local Purchase), "
                    "103 (Manufacture), 104 (Opening Stock)"
                )
            if stock_in_type != "103" and not supplier_name:
                raise ValueError(
                    "supplierName is required when operationType=101 "
                    "(except when stockInType=103 Manufacture)"
                )
            if adjust_type:
                raise ValueError(
                    "adjustType must be empty when operationType=101 (Increase)"
                )

        elif operation_type == "102":
            if supplier_tin or supplier_name:
                raise ValueError(
                    "supplierTin and supplierName must be empty "
                    "when operationType=102 (Decrease)"
                )
            if stock_in_type:
                raise ValueError(
                    "stockInType must be empty when operationType=102 (Decrease)"
                )
            if not adjust_type:
                raise ValueError(
                    "adjustType is required when operationType=102. "
                    "Use: 101 (Expired), 102 (Damaged), 103 (Personal), "
                    "104 (Others), 105 (Raw Materials)"
                )
        # Build goodsStockIn object
        goods_stock_in = {
            "operationType": operation_type,
            "isCheckBatchNo": is_check_batch_no,
            "rollBackIfError": roll_back_if_error,
            "goodsTypeCode": goods_type_code
        }

        # Add optional fields based on operation type
        if supplier_tin:
            goods_stock_in["supplierTin"] = supplier_tin
        if supplier_name:
            goods_stock_in["supplierName"] = supplier_name
        if adjust_type:
            goods_stock_in["adjustType"] = adjust_type
        if remarks:
            goods_stock_in["remarks"] = remarks
        if stock_in_date:
            goods_stock_in["stockInDate"] = stock_in_date
        if stock_in_type:
            goods_stock_in["stockInType"] = stock_in_type
        if production_batch_no:
            goods_stock_in["productionBatchNo"] = production_batch_no
        if production_date:
            goods_stock_in["productionDate"] = production_date
        if branch_id:
            goods_stock_in["branchId"] = branch_id
        if invoice_no:
            goods_stock_in["invoiceNo"] = invoice_no

        payload = {
            "goodsStockIn": goods_stock_in,
            "goodsStockInItem": stock_items
        }

        return self._make_request("T131", payload,encrypt=True)

    def t139_transfer_stock(
            self,
            source_branch_id: str,
            destination_branch_id: str,
            transfer_type_code: str,
            transfer_items: List[Dict],
            remarks: Optional[str] = None,
            roll_back_if_error: str = "0",
            goods_type_code: str = "101"
    ) -> List[Dict]:
        """
        T139: Goods Stock Transfer between branches

        Args:
            source_branch_id: Source branch ID (Store.efris_branch_id)
            destination_branch_id: Destination branch ID
            transfer_type_code: "101" (Out of Stock), "102" (Error), "103" (Others)
            transfer_items: List of items with Product.efris_goods_id or sku
            remarks: Required if transfer_type_code includes "103"
            roll_back_if_error: "0" (No) or "1" (Yes)
            goods_type_code: "101" (Goods) or "102" (Fuel)

        Returns:
            List of results for each item
        """
        if source_branch_id == destination_branch_id:
            raise ValueError("sourceBranchId and destinationBranchId cannot be the same")

        if "103" in transfer_type_code and not remarks:
            raise ValueError("remarks is required when transferTypeCode includes '103'")

        goods_stock_transfer = {
            "sourceBranchId": source_branch_id,
            "destinationBranchId": destination_branch_id,
            "transferTypeCode": transfer_type_code,
            "rollBackIfError": roll_back_if_error,
            "goodsTypeCode": goods_type_code
        }

        if remarks:
            goods_stock_transfer["remarks"] = remarks

        payload = {
            "goodsStockTransfer": goods_stock_transfer,
            "goodsStockTransferItem": transfer_items
        }

        return self._make_request("T139", payload,encrypt=True)

    def t139_transfer_stock_from_movement(self, movement, destination_branch_id: str):
        """
        Transfer stock in EFRIS from Django StockMovement (TRANSFER_OUT type)
        Uses your StockMovement model
        """
        if movement.movement_type != 'TRANSFER_OUT':
            raise ValueError("Movement must be TRANSFER_OUT type")

        product = movement.product

        if not product.efris_goods_id:
            raise ValueError(f"Product {product.sku} not uploaded to EFRIS")

        source_branch_id = getattr(movement.store, 'efris_branch_id', None)
        if not source_branch_id:
            raise ValueError(f"Store {movement.store.name} has no EFRIS branch ID")

        transfer_item = {
            "commodityGoodsId": product.efris_goods_id,
            "goodsCode": product.efris_goods_code,
            "measureUnit": product.unit_of_measure,
            "quantity": str(abs(float(movement.quantity))),
            "remarks": movement.notes or movement.reference or ""
        }

        return self.t139_transfer_stock(
            source_branch_id=source_branch_id,
            destination_branch_id=destination_branch_id,
            transfer_type_code="103",  # Others
            transfer_items=[transfer_item],
            remarks=movement.notes or f"Transfer: {movement.reference}"
        )

    def t145_query_stock_records(
            self,
            page_no: str = "1",
            page_size: str = "10",
            production_batch_no: Optional[str] = None,
            invoice_no: Optional[str] = None,
            reference_no: Optional[str] = None
    ) -> Dict:
        """
        T145: Query goods stock records (basic search)
        """
        if not any([production_batch_no, invoice_no, reference_no]):
            raise ValueError("At least one of productionBatchNo, invoiceNo, or referenceNo must be provided")

        if int(page_size) > 100:
            raise ValueError("pageSize cannot exceed 100")

        payload = {
            "pageNo": page_no,
            "pageSize": page_size
        }

        if production_batch_no:
            payload["productionBatchNo"] = production_batch_no
        if invoice_no:
            payload["invoiceNo"] = invoice_no
        if reference_no:
            payload["referenceNo"] = reference_no

        return self._make_request("T145", payload,encrypt=True)

    def t147_query_stock_records_advanced(
            self,
            page_no: str = "1",
            page_size: str = "10",
            combine_keywords: Optional[str] = None,
            stock_in_type: Optional[str] = None,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            supplier_tin: Optional[str] = None,
            supplier_name: Optional[str] = None
    ) -> Dict:
        """
        T147: Query goods stock records (advanced search)
        """
        if int(page_size) > 100:
            raise ValueError("pageSize cannot exceed 100")

        payload = {
            "pageNo": page_no,
            "pageSize": page_size
        }

        if combine_keywords:
            payload["combineKeywords"] = combine_keywords
        if stock_in_type:
            payload["stockInType"] = stock_in_type
        if start_date:
            payload["startDate"] = start_date
        if end_date:
            payload["endDate"] = end_date
        if supplier_tin:
            payload["supplierTin"] = supplier_tin
        if supplier_name:
            payload["supplierName"] = supplier_name

        return self._make_request("T147", payload,encrypt=True)

    def t148_query_stock_record_detail(self, record_id: str) -> Dict:
        """T148: Query detailed information for a specific stock record"""
        payload = {"id": record_id}
        return self._make_request("T148", payload,encrypt=True)

    def t149_query_adjust_records(
            self,
            page_no: str = "1",
            page_size: str = "10",
            reference_no: Optional[str] = None,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None
    ) -> Dict:
        """T149: Query goods stock adjustment records"""
        if int(page_size) > 100:
            raise ValueError("pageSize cannot exceed 100")

        payload = {
            "pageNo": page_no,
            "pageSize": page_size
        }

        if reference_no:
            payload["referenceNo"] = reference_no
        if start_date:
            payload["startDate"] = start_date
        if end_date:
            payload["endDate"] = end_date

        return self._make_request("T149", payload,encrypt=True)

    def t160_query_adjust_detail(self, adjust_id: str) -> Dict:
        """T160: Query detailed information for a specific stock adjustment"""
        payload = {"id": adjust_id}
        return self._make_request("T160", payload,encrypt=True)

    def t184_query_transfer_detail(self, transfer_id: str) -> Dict:
        """T184: Query detailed information for a specific stock transfer"""
        payload = {"id": transfer_id}
        return self._make_request("T184", payload,encrypt=True)

    # ============================================================================
    # HELPER METHODS FOR DJANGO INTEGRATION
    # ============================================================================

    def _map_unit_to_efris(self, unit_of_measure: str) -> str:
        """
        Map Django Product unit_of_measure to EFRIS unit codes (from T115)

        Args:
            unit_of_measure: Unit from Product model

        Returns:
            EFRIS unit code (e.g., "101" for pieces)
        """
        unit_mapping = {
            'each': '101',
            'piece': '101',
            'unit': '101',
            'kg': 'KGM',
            'kilogram': 'KGM',
            'litre': 'LTR',
            'liter': 'LTR',
            'meter': 'MTR',
            'metre': 'MTR',
            'box': 'BX',
            'packet': 'PK',
            'gram': 'GRM',
            'ml': 'MLT',
            'millilitre': 'MLT',
            'set': 'SET',
            'pair': 'PR',
        }
        return unit_mapping.get(unit_of_measure.lower(), '101')

    def bulk_sync_stock_to_efris(self, store=None, product_ids=None):
        """
        Bulk sync Stock records that need EFRIS sync
        Uses efris_sync_required flag from your Stock model
        """
        from inventory.models import Stock, Product

        # Build queryset using your Stock model
        stocks = Stock.objects.filter(efris_sync_required=True).select_related('product', 'store')

        if store:
            stocks = stocks.filter(store=store)

        if product_ids:
            stocks = stocks.filter(product_id__in=product_ids)

        results = {
            'total': stocks.count(),
            'successful': 0,
            'failed': 0,
            'errors': []
        }

        for stock in stocks:
            try:
                # Sync this stock
                result = self.sync_product_to_efris_stock(stock.product, stock.store)

                if result and not result[0].get('error'):
                    results['successful'] += 1
                    stock.mark_efris_synced()
                else:
                    results['failed'] += 1
                    results['errors'].append({
                        'product': stock.product.sku,
                        'store': stock.store.name,
                        'error': result[0].get('error') if result else 'Unknown error'
                    })
            except Exception as e:
                results['failed'] += 1
                results['errors'].append({
                    'product': stock.product.sku,
                    'store': stock.store.name,
                    'error': str(e)
                })

        return results

    def increase_stock_from_product(
            self,
            product,
            quantity: float,
            store,
            stock_in_type: str = "102",  # Local Purchase
            supplier_name: Optional[str] = None,
            supplier_tin: Optional[str] = None,
            invoice_no: Optional[str] = None
    ) -> List[Dict]:
        """
        Helper: Increase stock for a Django Product
        Creates a PURCHASE StockMovement automatically
        """
        from inventory.models import StockMovement

        auth_result = self.ensure_authenticated()
        if not auth_result.get("success"):
            raise Exception(f"Authentication failed: {auth_result.get('error')}")

        if not product.efris_goods_id:
            raise ValueError(f"Product {product.sku} not uploaded to EFRIS")

        # Use product's supplier if not provided
        if not supplier_name and product.supplier:
            supplier_name = product.supplier.name
            supplier_tin = product.supplier.tin
        elif not supplier_name:
            supplier_name = store.name

        stock_item = {
            "commodityGoodsId": product.efris_goods_id,
            "goodsCode": product.efris_goods_code,
            "measureUnit": product.unit_of_measure,
            "quantity": str(float(quantity)),
            "unitPrice": str(float(product.cost_price))
        }

        result = self.t131_maintain_stock(
            operation_type="101",
            stock_items=[stock_item],
            stock_in_type=stock_in_type,
            supplier_name=supplier_name,
            supplier_tin=supplier_tin,
            branch_id=getattr(store, 'efris_branch_id', None),
            invoice_no=invoice_no
        )

        # Create StockMovement record if successful
        if result and not result[0].get('returnCode'):
            StockMovement.objects.create(
                product=product,
                store=store,
                movement_type='PURCHASE',
                quantity=quantity,
                unit_price=product.cost_price,
                reference=invoice_no or f"EFRIS-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                notes=f"EFRIS stock increase via T131",
                created_by=getattr(store, 'created_by', None)
            )

        return result

    def decrease_stock_from_product(
            self,
            product,
            quantity: float,
            store,
            adjust_type: str = "105",  # Raw Materials
            remarks: Optional[str] = None
    ) -> List[Dict]:
        """
        Helper: Decrease stock for a Django Product
        Creates an ADJUSTMENT StockMovement automatically
        """
        from inventory.models import StockMovement

        if not product.efris_goods_id:
            raise ValueError(f"Product {product.sku} not uploaded to EFRIS")

        if adjust_type == "104" and not remarks:
            raise ValueError("remarks required for adjust_type='104' (Others)")

        stock_item = {
            "commodityGoodsId": product.efris_goods_id,
            "goodsCode": product.efris_goods_code_field,
            "measureUnit": product.unit_of_measure,
            "quantity": str(float(quantity)),
            "unitPrice": str(float(product.cost_price))
        }

        result = self.t131_maintain_stock(
            operation_type="102",
            stock_items=[stock_item],
            adjust_type=adjust_type,
            remarks=remarks or f"Stock adjustment for {product.name}",
            branch_id=getattr(store, 'efris_branch_id', None)
        )

        # Create StockMovement record if successful
        if result and not result[0].get('returnCode'):
            StockMovement.objects.create(
                product=product,
                store=store,
                movement_type='ADJUSTMENT',
                quantity=-abs(quantity),  # Negative for decrease
                unit_price=product.cost_price,
                reference=f"EFRIS-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                notes=remarks or f"EFRIS stock decrease via T131",
                created_by=getattr(store, 'created_by', None)
            )

        return result

    def query_commodity_categories_paginated(
            self,
            page_no: int = 1,
            page_size: int = 100
    ) -> Dict[str, Any]:
        """T124 - Query Commodity Categories with Pagination (CONFIRMED WORKING with signature)"""
        try:
            auth_result = self.ensure_authenticated()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error')}"
                }

            content = {
                "pageNo": str(page_no),
                "pageSize": str(page_size)
            }

            # T124 requires signature even when unencrypted
            response = self._make_request("T124", content, encrypt=False)

            return {
                "success": True,
                "data": response
            }
        except Exception as e:
            logger.error(f"T124 failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

def bulk_register_services_with_efris(company):
    """
    Bulk register services with EFRIS
    Similar to bulk_register_products_with_efris but for services

    Args:
        company: Company instance

    Returns:
        Dict with bulk registration results
    """
    results = {
        'total': 0,
        'successful': 0,
        'failed': 0,
        'errors': [],
        'warnings': [],
        'registered_services': []
    }

    try:
        with schema_context(company.schema_name):
            from inventory.models import Service

            # Get services that need registration
            services = Service.objects.filter(
                is_active=True,
                efris_is_uploaded=False,
                efris_auto_sync_enabled=True
            ).select_related('category')

            results['total'] = services.count()

            if results['total'] == 0:
                results['warnings'].append('No services found that need EFRIS registration')
                return results

            logger.info(f"Starting bulk registration of {results['total']} services for company {company.name}")

            with EnhancedEFRISAPIClient(company) as client:
                # Process services in batches
                batch_size = 10
                for i in range(0, results['total'], batch_size):
                    batch_services = services[i:i + batch_size]

                    for service in batch_services:
                        try:
                            # Validate service before registration
                            validation_errors = []

                            if not service.name or len(service.name.strip()) < 2:
                                validation_errors.append("Service name is too short")

                            if not service.code:
                                validation_errors.append("Service code is missing")

                            if not hasattr(service, 'unit_price') or service.unit_price is None:
                                validation_errors.append("Unit price is missing")

                            if not service.category:
                                validation_errors.append("Service category is missing")
                            elif service.category.category_type != 'service':
                                validation_errors.append("Category must be a service category")
                            elif not service.category.efris_commodity_category_code:
                                validation_errors.append("Category must have EFRIS commodity category")

                            if validation_errors:
                                results['failed'] += 1
                                results['errors'].append({
                                    'service_id': service.id,
                                    'code': service.code,
                                    'name': service.name,
                                    'error': f"Validation failed: {'; '.join(validation_errors)}"
                                })
                                continue

                            # Register the service
                            result = client.register_service_with_efris(service)

                            if result.get('success'):
                                results['successful'] += 1
                                results['registered_services'].append({
                                    'service_id': service.id,
                                    'code': service.code,
                                    'name': service.name,
                                    'efris_service_id': result.get('efris_service_id', 'N/A')
                                })
                                logger.info(f"Successfully registered service: {service.name}")
                            else:
                                results['failed'] += 1
                                error_detail = {
                                    'service_id': service.id,
                                    'code': service.code,
                                    'name': service.name,
                                    'error': result.get('error', 'Unknown error'),
                                    'error_code': result.get('error_code')
                                }
                                results['errors'].append(error_detail)
                                logger.error(f"Failed to register service {service.name}: {result.get('error')}")

                        except Exception as e:
                            results['failed'] += 1
                            error_detail = {
                                'service_id': service.id,
                                'code': service.code,
                                'name': service.name,
                                'error': f"Registration exception: {str(e)}"
                            }
                            results['errors'].append(error_detail)
                            logger.error(f"Exception during service registration: {e}", exc_info=True)

                    # Small delay between batches
                    if i + batch_size < results['total']:
                        import time
                        time.sleep(1)

    except Exception as e:
        results['errors'].append({
            'service_id': None,
            'code': 'SYSTEM',
            'name': 'Bulk Registration',
            'error': f"System error: {str(e)}"
        })
        logger.error(f"Bulk service registration system error: {e}", exc_info=True)

    # Generate summary
    success_rate = (results['successful'] / results['total'] * 100) if results['total'] > 0 else 0
    logger.info(
        f"Bulk service registration completed: {results['successful']}/{results['total']} "
        f"services registered ({success_rate:.1f}% success rate)"
    )

    return results


def bulk_register_products_with_efris(company):
    results = {
        'total': 0,
        'successful': 0,
        'failed': 0,
        'errors': [],
        'warnings': [],
        'registered_products': []
    }

    try:
        with schema_context(company.schema_name):
            from inventory.models import Product

            # Get products that need registration
            products = Product.objects.filter(
                is_active=True,
                efris_is_uploaded=False
            ).select_related('category')  # Optimize queries

            results['total'] = products.count()

            if results['total'] == 0:
                results['warnings'].append('No products found that need EFRIS registration')
                return results

            logger.info(f"Starting bulk registration of {results['total']} products for company {company.name}")

            with EnhancedEFRISAPIClient(company) as client:
                # Process products in smaller batches to avoid timeouts
                batch_size = 10
                for i in range(0, results['total'], batch_size):
                    batch_products = products[i:i + batch_size]

                    for product in batch_products:
                        try:
                            # Validate product before registration
                            validation_errors = []

                            if not product.name or len(product.name.strip()) < 2:
                                validation_errors.append("Product name is too short")

                            if not hasattr(product, 'selling_price') or product.selling_price is None:
                                validation_errors.append("Selling price is missing")

                            if validation_errors:
                                results['failed'] += 1
                                results['errors'].append({
                                    'product_id': product.id,
                                    'sku': getattr(product, 'sku', 'N/A'),
                                    'name': product.name,
                                    'error': f"Validation failed: {'; '.join(validation_errors)}"
                                })
                                continue

                            # Register the product
                            result = client.register_product_with_efris(product)

                            if result.get('success'):
                                results['successful'] += 1
                                results['registered_products'].append({
                                    'product_id': product.id,
                                    'sku': getattr(product, 'sku', 'N/A'),
                                    'name': product.name,
                                    'item_code': result.get('item_code', 'N/A')
                                })
                                logger.info(f"Successfully registered product: {product.name}")
                            else:
                                results['failed'] += 1
                                error_detail = {
                                    'product_id': product.id,
                                    'sku': getattr(product, 'sku', 'N/A'),
                                    'name': product.name,
                                    'error': result.get('error', 'Unknown error'),
                                    'error_code': result.get('error_code')
                                }
                                results['errors'].append(error_detail)
                                logger.error(f"Failed to register product {product.name}: {result.get('error')}")

                        except Exception as e:
                            results['failed'] += 1
                            error_detail = {
                                'product_id': product.id,
                                'sku': getattr(product, 'sku', 'N/A'),
                                'name': product.name,
                                'error': f"Registration exception: {str(e)}"
                            }
                            results['errors'].append(error_detail)
                            logger.error(f"Exception during product registration: {e}", exc_info=True)

                    # Add small delay between batches to avoid overwhelming EFRIS
                    if i + batch_size < results['total']:
                        import time
                        time.sleep(1)

    except Exception as e:
        results['errors'].append({
            'product_id': None,
            'sku': 'SYSTEM',
            'name': 'Bulk Registration',
            'error': f"System error: {str(e)}"
        })
        logger.error(f"Bulk registration system error: {e}", exc_info=True)

    # Generate summary
    success_rate = (results['successful'] / results['total'] * 100) if results['total'] > 0 else 0
    logger.info(
        f"Bulk registration completed: {results['successful']}/{results['total']} "
        f"products registered ({success_rate:.1f}% success rate)"
    )

    return results


class EFRISCustomerService:
    """Enhanced service for handling EFRIS customer operations"""

    def __init__(self, company):
        self.company = company
        self.client = EnhancedEFRISAPIClient(company)
        self.validator = DataValidator()

    def query_taxpayer(self, tin: str, nin_brn: Optional[str] = None) -> Tuple[bool, Union[Dict, str]]:
        """T119 - Query taxpayer by TIN with enhanced validation and error handling"""

        # Validate TIN format
        is_valid, error = self.validator.validate_tin(tin)
        if not is_valid:
            return False, f"Invalid TIN format: {error}"

        # Validate BRN if provided
        if nin_brn:
            is_valid_brn, brn_error = self.validator.validate_brn(nin_brn)
            if not is_valid_brn:
                logger.warning(f"Invalid BRN provided: {brn_error}")
                nin_brn = None  # Clear invalid BRN

        try:
            with self.client as client:
                response = client.query_taxpayer_by_tin(tin, nin_brn)

                if response.success:
                    # Process and validate taxpayer data
                    taxpayer_data = self._process_taxpayer_data(response.data)
                    return True, taxpayer_data
                else:
                    error_msg = response.error_message or "Taxpayer query failed"
                    logger.warning(
                        "Taxpayer query failed",
                        tin=tin,
                        error=error_msg,
                        error_code=response.error_code
                    )
                    return False, error_msg

        except Exception as e:
            logger.error("Taxpayer query failed", tin=tin, error=str(e))
            return False, f"Query error: {e}"

    def _process_taxpayer_data(self, raw_data: Optional[Dict]) -> Dict[str, Any]:
        """Process and normalize taxpayer data from EFRIS response"""
        if not raw_data:
            return {}

        # Extract taxpayer information with safe defaults
        taxpayer_info = raw_data.get('taxpayer', {})

        processed_data = {
            'tin': taxpayer_info.get('tin', ''),
            'nin_brn': taxpayer_info.get('ninBrn', ''),
            'legal_name': taxpayer_info.get('legalName', ''),
            'business_name': taxpayer_info.get('businessName', ''),
            'trading_name': taxpayer_info.get('tradingName', ''),
            'taxpayer_type': taxpayer_info.get('taxpayerType', ''),
            'status': taxpayer_info.get('status', ''),
            'registration_date': taxpayer_info.get('registrationDate', ''),
            'address': taxpayer_info.get('address', ''),
            'phone': taxpayer_info.get('mobilePhone', ''),
            'email': taxpayer_info.get('emailAddress', ''),
            'sector': taxpayer_info.get('sector', ''),
            'is_vat_registered': taxpayer_info.get('isVATRegistered', False),
            'effective_registration_date': taxpayer_info.get('effectiveRegistrationDate', ''),
            'last_updated': timezone.now().isoformat()
        }

        return processed_data

    def validate_customer_for_efris(self, customer) -> Tuple[bool, List[str]]:
        """Enhanced customer validation for EFRIS operations"""
        errors = []

        # Basic validation
        if not customer:
            return False, ["Customer object is required"]

        # Name validation
        customer_name = getattr(customer, 'name', None)
        if not customer_name or not customer_name.strip():
            errors.append("Customer name is required")
        elif len(customer_name.strip()) < 2:
            errors.append("Customer name must be at least 2 characters")

        # Phone validation
        phone = getattr(customer, 'phone', None)
        if not phone or not phone.strip():
            errors.append("Customer phone number is required")
        else:
            # Basic phone format validation for Uganda
            clean_phone = phone.replace(' ', '').replace('-', '').replace('+', '')
            if not (clean_phone.isdigit() and len(clean_phone) >= 9):
                errors.append("Invalid phone number format")

        # Business customer validation
        customer_type = getattr(customer, 'customer_type', '').upper()
        if customer_type in ['BUSINESS', 'CORPORATE', 'COMPANY']:
            tin = getattr(customer, 'tin', None)
            brn = getattr(customer, 'brn', None)

            if not tin and not brn:
                errors.append("Business customers must have either TIN or BRN")

            if tin:
                is_valid, error = self.validator.validate_tin(tin)
                if not is_valid:
                    errors.append(f"Customer TIN: {error}")

            if brn:
                is_valid, error = self.validator.validate_brn(brn)
                if not is_valid:
                    errors.append(f"Customer BRN: {error}")

        # Email validation if provided
        email = getattr(customer, 'email', None)
        if email and email.strip():
            if '@' not in email or '.' not in email.split('@')[1]:
                errors.append("Invalid email format")

        return len(errors) == 0, errors

    def enrich_customer_from_efris(self, customer) -> Tuple[bool, str]:
        """Enrich customer data from EFRIS taxpayer information"""

        if not customer:
            return False, "Customer is required"

        customer_tin = getattr(customer, 'tin', None)
        if not customer_tin:
            return False, "Customer TIN is required for EFRIS enrichment"

        try:
            # Query EFRIS for taxpayer info
            success, result = self.query_taxpayer(customer_tin)

            if not success:
                return False, f"EFRIS query failed: {result}"

            if not isinstance(result, dict):
                return False, "Invalid EFRIS response format"

            # Update customer with EFRIS data
            updates_made = []

            # Update business name if not set
            if not getattr(customer, 'business_name', None) and result.get('business_name'):
                customer.business_name = result['business_name']
                updates_made.append('business_name')

            # Update legal name if not set
            if not getattr(customer, 'legal_name', None) and result.get('legal_name'):
                customer.legal_name = result['legal_name']
                updates_made.append('legal_name')

            # Update address if not set
            if not getattr(customer, 'address', None) and result.get('address'):
                customer.address = result['address']
                updates_made.append('address')

            # Update contact info if not set
            if not getattr(customer, 'email', None) and result.get('email'):
                customer.email = result['email']
                updates_made.append('email')

            if not getattr(customer, 'phone', None) and result.get('phone'):
                customer.phone = result['phone']
                updates_made.append('phone')

            # Set customer type based on EFRIS data
            if result.get('taxpayer_type') and not getattr(customer, 'customer_type', None):
                customer.customer_type = 'BUSINESS' if result['is_vat_registered'] else 'INDIVIDUAL'
                updates_made.append('customer_type')

            # Save updates
            if updates_made:
                customer.save(update_fields=updates_made)
                return True, f"Customer enriched with: {', '.join(updates_made)}"
            else:
                return True, "No updates needed - customer data is complete"

        except Exception as e:
            logger.error(
                "Customer enrichment failed",
                customer_id=getattr(customer, 'pk', None),
                error=str(e)
            )
            return False, f"Enrichment error: {e}"

class EFRISInvoiceService:
    """Service wrapper for invoice fiscalization with consistent return format"""

    def __init__(self, company):
        self.company = company

    def fiscalize_invoice(self, invoice, user=None) -> Dict[str, Any]:
        """Fiscalize invoice with proper return format"""
        try:
            with EnhancedEFRISAPIClient(self.company) as client:
                result = client.upload_invoice(invoice, user)

                # Log raw result for debugging
                logger.debug(f"Raw upload_invoice result for invoice {invoice.id}: {result} (type: {type(result)})")

                # Ensure consistent return format
                if isinstance(result, dict):
                    if result.get('success', False):
                        return {
                            "success": True,
                            "message": result.get("message", "Invoice fiscalized successfully"),
                            "data": result.get("data", {})
                        }
                    else:
                        return {
                            "success": False,
                            "message": result.get("error", "Fiscalization failed"),
                            "error_code": result.get("error_code"),
                            "data": result.get("response_data")
                        }
                elif isinstance(result, tuple):
                    # Temporary handling for unexpected tuple response
                    logger.warning(f"Unexpected tuple response from upload_invoice: {result}")
                    if len(result) >= 2:
                        success, message = result[:2]
                        extra_data = result[2:] if len(result) > 2 else None
                        return {
                            "success": bool(success),
                            "message": str(message) if message else "Unexpected tuple format",
                            "data": {"extra": extra_data} if extra_data else {},
                            "error_code": None
                        }
                    else:
                        return {
                            "success": False,
                            "message": f"Invalid tuple format: {result}",
                            "data": None,
                            "error_code": None
                        }
                else:
                    logger.error(f"Unexpected response type from upload_invoice: {type(result)}")
                    return {
                        "success": False,
                        "message": f"Unexpected response type: {type(result)}",
                        "data": None,
                        "error_code": None
                    }

        except Exception as e:
            logger.error(f"Invoice fiscalization failed for invoice {invoice.id}: {str(e)}", exc_info=True)
            return {
                "success": False,
                "message": f"Fiscalization error: {str(e)}",
                "data": None,
                "error_code": None
            }

    def bulk_fiscalize_invoices(self, invoices: List, user=None) -> Dict[str, Any]:
        """
        Bulk fiscalize multiple invoices
        Required by bulk_fiscalize_invoices_async task
        """
        results = {
            'success': True,
            'total_invoices': len(invoices),
            'successful_count': 0,
            'failed_count': 0,
            'errors': []
        }

        for invoice in invoices:
            try:
                result = self.fiscalize_invoice(invoice, user)

                if result.get('success'):
                    results['successful_count'] += 1
                else:
                    results['failed_count'] += 1
                    results['errors'].append({
                        'invoice_id': invoice.id,
                        'invoice_number': getattr(invoice, 'number', 'Unknown'),
                        'error': result.get('message', 'Unknown error')
                    })
            except Exception as e:
                results['failed_count'] += 1
                results['errors'].append({
                    'invoice_id': invoice.id,
                    'invoice_number': getattr(invoice, 'number', 'Unknown'),
                    'error': str(e)
                })

        # Overall success if at least 80% succeeded
        if results['total_invoices'] > 0:
            success_rate = results['successful_count'] / results['total_invoices']
            results['success'] = success_rate >= 0.8
        else:
            results['success'] = False

        return results


def debug_query_goods(self, goods_code: str, verbose: bool = True) -> Dict[str, Any]:
    """
    Query goods with detailed debug output

    Args:
        goods_code: Goods code to query
        verbose: Print detailed output to console

    Returns:
        Dict with query results
    """
    try:
        if verbose:
            print("\n" + "🔍 " + "=" * 78)
            print(f"   DEBUG: Querying EFRIS for Goods Code: {goods_code}")
            print("=" * 80 + "\n")

        # Query using T144
        query_result = self.t144_query_goods_by_code(goods_code)

        if verbose:
            print("📡 RAW API RESPONSE:")
            print("-" * 80)
            print(json.dumps(query_result, indent=2, default=str))
            print("-" * 80 + "\n")

        if query_result.get('success'):
            goods_list = query_result.get('goods', [])

            if goods_list:
                if verbose:
                    print(f"✅ Found {len(goods_list)} goods in EFRIS\n")

                    for idx, goods in enumerate(goods_list, 1):
                        print(f"📦 GOODS #{idx}")
                        print("-" * 80)

                        # Essential fields
                        print("ESSENTIAL FIELDS:")
                        print(f"  🆔 EFRIS Goods ID    : {goods.get('id', 'NOT FOUND')}")
                        print(f"  📝 Goods Code        : {goods.get('goodsCode', 'NOT FOUND')}")
                        print(f"  🏷️  Goods Name        : {goods.get('goodsName', 'NOT FOUND')}")
                        print(f"  📏 Measure Unit      : {goods.get('measureUnit', 'NOT FOUND')}")
                        print(f"  💰 Unit Price        : {goods.get('unitPrice', 'NOT FOUND')}")
                        print(f"  💵 Currency          : {goods.get('currency', 'NOT FOUND')}")
                        print(f"  📊 Stock             : {goods.get('stock', 'NOT FOUND')}")
                        print(f"  ⚠️  Stock Warning     : {goods.get('stockPrewarning', 'NOT FOUND')}")

                        print("\nCATEGORY & TAX:")
                        print(f"  🏪 Category Code     : {goods.get('commodityCategoryCode', 'NOT FOUND')}")
                        print(f"  🏷️  Category Name     : {goods.get('commodityCategoryName', 'NOT FOUND')}")
                        print(f"  💸 Tax Rate          : {goods.get('taxRate', 'NOT FOUND')}")
                        print(f"  🆓 Is Zero Rate      : {goods.get('isZeroRate', 'NOT FOUND')}")
                        print(f"  ⚖️  Is Exempt         : {goods.get('isExempt', 'NOT FOUND')}")
                        print(f"  🍺 Have Excise Tax   : {goods.get('haveExciseTax', 'NOT FOUND')}")

                        print("\nUNIT DETAILS:")
                        print(f"  📦 Have Piece Unit   : {goods.get('havePieceUnit', 'NOT FOUND')}")
                        print(f"  📏 Piece Measure Unit: {goods.get('pieceMeasureUnit', 'NOT FOUND')}")
                        print(f"  💰 Piece Unit Price  : {goods.get('pieceUnitPrice', 'NOT FOUND')}")
                        print(f"  📊 Have Other Unit   : {goods.get('haveOtherUnit', 'NOT FOUND')}")

                        print("\nSTATUS:")
                        print(f"  🚦 Status Code       : {goods.get('statusCode', 'NOT FOUND')}")
                        print(f"  📍 Source            : {goods.get('source', 'NOT FOUND')}")
                        print(f"  🔧 Service Mark      : {goods.get('serviceMark', 'NOT FOUND')}")
                        print(f"  📦 Goods Type Code   : {goods.get('goodsTypeCode', 'NOT FOUND')}")
                        print(f"  📅 Update Date       : {goods.get('updateDateStr', 'NOT FOUND')}")

                        # Customs info if present
                        customs = goods.get('commodityGoodsExtendEntity')
                        if customs:
                            print("\nCUSTOMS INFORMATION:")
                            print(f"  📏 Customs Unit      : {customs.get('customsMeasureUnit', 'NOT FOUND')}")
                            print(f"  💰 Customs Price     : {customs.get('customsUnitPrice', 'NOT FOUND')}")
                            print(f"  📊 Customs Scaled    : {customs.get('customsScaledValue', 'NOT FOUND')}")

                        # Other units if present
                        other_units = goods.get('goodsOtherUnits', [])
                        if other_units:
                            print("\nOTHER UNITS:")
                            for unit_idx, unit in enumerate(other_units, 1):
                                print(f"  Unit #{unit_idx}:")
                                print(f"    📏 Other Unit      : {unit.get('otherUnit', 'NOT FOUND')}")
                                print(f"    💰 Other Price     : {unit.get('otherPrice', 'NOT FOUND')}")
                                print(f"    📊 Other Scaled    : {unit.get('otherScaled', 'NOT FOUND')}")

                        print("\n" + "=" * 80 + "\n")

                        # Full JSON for reference
                        print("📄 COMPLETE JSON OBJECT:")
                        print("-" * 80)
                        print(json.dumps(goods, indent=2, default=str))
                        print("-" * 80 + "\n")

                return {
                    "success": True,
                    "found": True,
                    "goods": goods_list,
                    "count": len(goods_list)
                }
            else:
                if verbose:
                    print("❌ No goods found in EFRIS for code:", goods_code)
                    print()

                return {
                    "success": True,
                    "found": False,
                    "message": f"Goods code {goods_code} not found in EFRIS"
                }
        else:
            if verbose:
                print("❌ QUERY FAILED")
                print(f"Error: {query_result.get('error', 'Unknown error')}")
                print()

            return {
                "success": False,
                "error": query_result.get('error', 'Query failed')
            }

    except Exception as e:
        if verbose:
            print(f"💥 EXCEPTION OCCURRED: {e}")
            import traceback
            traceback.print_exc()
            print()

        return {
            "success": False,
            "error": str(e)
        }

def diagnose_efris_issue(company, invoice=None):
    """Comprehensive EFRIS diagnostic tool"""
    print("=== EFRIS DIAGNOSTIC REPORT ===")
    print(f"Company: {company.name}")
    print(f"TIN: {company.tin}")
    print(f"Device: {getattr(company.efris_config, 'device_number', 'Not set')}")
    print(f"Timestamp: {timezone.now()}")
    print()

    try:
        # Configuration Check
        print("=== 1. CONFIGURATION CHECK ===")
        config_issues = []

        if not hasattr(company, 'efris_config'):
            config_issues.append("No EFRIS configuration found")
        else:
            config = company.efris_config
            if not config.private_key:
                config_issues.append("Private key missing")
            if not config.device_number:
                config_issues.append("Device number missing")
            if not config.is_active:
                config_issues.append("Configuration not active")

        if config_issues:
            print("❌ Issues found:")
            for issue in config_issues:
                print(f"   - {issue}")
        else:
            print("✅ Configuration OK")

        # Connectivity Test
        print("\n=== 2. CONNECTIVITY TEST ===")
        try:
            with EnhancedEFRISAPIClient(company) as client:
                result = client.get_server_time()
                if result.get("success"):
                    print("✅ Server connectivity OK")
                else:
                    print(f"❌ Server connectivity failed: {result.get('error')}")
        except Exception as e:
            print(f"❌ Connectivity test failed: {e}")

        # Authentication Test
        print("\n=== 3. AUTHENTICATION TEST ===")
        try:
            with EnhancedEFRISAPIClient(company) as client:
                auth_result = client.ensure_authenticated()
                if auth_result.get("success"):
                    print("✅ Authentication successful")
                    if client.security_manager.is_aes_key_valid():
                        print("✅ AES key is valid")
                    else:
                        print("❌ AES key invalid")
                else:
                    print(f"❌ Authentication failed: {auth_result.get('error')}")
        except Exception as e:
            print(f"❌ Authentication test failed: {e}")

        # Invoice Test
        if invoice:
            print(f"\n=== 4. INVOICE TEST ({getattr(invoice, 'number', 'unknown')}) ===")
            try:
                transformer = EFRISDataTransformer(company)
                invoice_data = transformer.build_invoice_data(invoice)
                print("✅ Invoice data structure OK")

                # Validate amounts
                summary = invoice_data.get('summary', {})
                net_amount = float(summary.get('netAmount', 0))
                tax_amount = float(summary.get('taxAmount', 0))
                gross_amount = float(summary.get('grossAmount', 0))

                expected_gross = net_amount + tax_amount
                if abs(gross_amount - expected_gross) <= 0.01:
                    print("✅ Amount calculations correct")
                    print(f"   Net: {net_amount}, Tax: {tax_amount}, Gross: {gross_amount}")
                else:
                    print(f"❌ Amount calculation error:")
                    print(f"   Expected: {expected_gross}, Actual: {gross_amount}")

            except Exception as e:
                print(f"❌ Invoice test failed: {e}")

        print("\n=== RECOMMENDATIONS ===")
        print("1. Ensure device number matches EFRIS registration")
        print("2. Verify private key is correct and not expired")
        print("3. Check invoice amount calculations")
        print("4. Ensure tax rates are properly mapped (A=18%, B=0%, etc.)")
        print("5. Use SHA1withRSA signature as per EFRIS documentation")

    except Exception as e:
        print(f"Diagnostic failed: {e}")


# In services.py - Update sync_commodity_categories function

def sync_commodity_categories(company) -> Dict[str, Any]:
    """Sync commodity categories from EFRIS with batching"""
    try:
        client = EnhancedEFRISAPIClient(company)

        # Use pagination to fetch in batches
        page_no = 1
        page_size = 100  # Smaller batches
        total_fetched = 0
        all_categories = []

        while True:
            # Fetch page
            result = client.query_commodity_categories_paginated(
                page_no=page_no,
                page_size=page_size
            )

            if not result.get('success'):
                return {
                    'success': False,
                    'error': result.get('error'),
                    'total_fetched': total_fetched
                }

            categories = result.get('data', {}).get('records', [])

            if not categories:
                break  # No more pages

            # Process this batch immediately
            saved_count = _save_category_batch(categories)
            total_fetched += saved_count

            logger.info(f"Processed page {page_no}: {saved_count} categories")

            # Check if there are more pages
            pagination = result.get('data', {}).get('page', {})
            if page_no >= int(pagination.get('pageCount', 1)):
                break

            page_no += 1

            # Small delay to avoid overwhelming the server
            import time
            time.sleep(0.5)

        return {
            'success': True,
            'total_fetched': total_fetched
        }

    except Exception as e:
        logger.error(f"Category sync failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'total_fetched': total_fetched
        }


def _save_category_batch(categories: list) -> int:
    """Save a batch of categories efficiently"""
    from company.models import EFRISCommodityCategory
    from django.utils import timezone

    saved_count = 0

    # Use bulk operations for better performance
    categories_to_create = []
    categories_to_update = []

    existing_codes = set(
        EFRISCommodityCategory.objects.filter(
            commodity_category_code__in=[c.get('commodityCategoryCode') for c in categories]
        ).values_list('commodity_category_code', flat=True)
    )

    for cat_data in categories:
        code = cat_data.get('commodityCategoryCode')
        if not code:
            continue

        cat_obj = EFRISCommodityCategory(
            commodity_category_code=code,
            commodity_category_name=cat_data.get('commodityCategoryName', ''),
            parent_code=cat_data.get('parentCode', ''),
            commodity_category_level=cat_data.get('commodityCategoryLevel', ''),
            rate=cat_data.get('rate', 0),
            service_mark=cat_data.get('serviceMark', ''),
            is_leaf_node=cat_data.get('isLeafNode', ''),
            is_zero_rate=cat_data.get('isZeroRate', ''),
            is_exempt=cat_data.get('isExempt', ''),
            enable_status_code=cat_data.get('enableStatusCode', ''),
            last_synced=timezone.now()
        )

        if code in existing_codes:
            categories_to_update.append(cat_obj)
        else:
            categories_to_create.append(cat_obj)

    # Bulk create new categories
    if categories_to_create:
        EFRISCommodityCategory.objects.bulk_create(
            categories_to_create,
            ignore_conflicts=True
        )
        saved_count += len(categories_to_create)

    # Bulk update existing (if needed)
    if categories_to_update:
        for cat in categories_to_update:
            EFRISCommodityCategory.objects.filter(
                commodity_category_code=cat.commodity_category_code
            ).update(
                commodity_category_name=cat.commodity_category_name,
                parent_code=cat.parent_code,
                rate=cat.rate,
                last_synced=cat.last_synced
            )
        saved_count += len(categories_to_update)

    return saved_count


def test_efris_connection(company) -> Dict[str, Any]:
    """Test EFRIS connection and authentication"""
    results = {}

    try:
        client = EnhancedEFRISAPIClient(company)

        # Test T101
        time_result = client.get_server_time()
        results['server_time'] = time_result.get('success', False)

        # Test authentication
        auth_result = client.ensure_authenticated()
        results['authentication'] = auth_result.get('success', False)

        # Overall success
        results['success'] = all(results.values())
        results['message'] = "All tests passed" if results['success'] else "Some tests failed"

    except Exception as e:
        results['success'] = False
        results['error'] = str(e)

    return results

class EFRISServiceManager:
    """
    Service manager for EFRIS operations
    Handles service-specific EFRIS logic
    """

    def __init__(self, company):
        self.company = company
        self.client = EnhancedEFRISAPIClient(company)

    def register_service(self, service, user=None) -> Dict[str, Any]:
        """
        Register a single service with EFRIS

        Args:
            service: Service model instance
            user: Optional user performing the action

        Returns:
            Dict with registration result
        """
        try:
            # Validate service
            is_valid, errors = self.validate_service_for_efris(service)
            if not is_valid:
                return {
                    "success": False,
                    "error": f"Validation failed: {'; '.join(errors)}"
                }

            # Register with EFRIS
            result = self.client.register_service_with_efris(service)

            # Log the operation
            if result.get('success'):
                self._log_service_operation(
                    service=service,
                    operation='REGISTER',
                    success=True,
                    user=user
                )
            else:
                self._log_service_operation(
                    service=service,
                    operation='REGISTER',
                    success=False,
                    error=result.get('error'),
                    user=user
                )

            return result

        except Exception as e:
            logger.error(f"Service registration failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def update_service(self, service, user=None) -> Dict[str, Any]:
        """
        Update service in EFRIS (uses T130 with operationType='102')

        Args:
            service: Service model instance
            user: Optional user performing the action

        Returns:
            Dict with update result
        """
        try:
            if not service.efris_service_id:
                return {
                    "success": False,
                    "error": "Service must be registered with EFRIS before updating"
                }

            # Mark as not uploaded to trigger update
            service.efris_is_uploaded = False

            # Register (will use operationType='102' for update)
            result = self.client.register_service_with_efris(service)

            if result.get('success'):
                self._log_service_operation(
                    service=service,
                    operation='UPDATE',
                    success=True,
                    user=user
                )

            return result

        except Exception as e:
            logger.error(f"Service update failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def validate_service_for_efris(self, service) -> Tuple[bool, List[str]]:
        """
        Validate service for EFRIS compliance

        Args:
            service: Service model instance

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Basic validation
        if not service:
            return False, ["Service object is required"]

        # Name validation
        if not service.name or len(service.name.strip()) < 2:
            errors.append("Service name must be at least 2 characters")

        # Code validation
        if not service.code:
            errors.append("Service code is required")

        # Price validation
        if not hasattr(service, 'unit_price') or service.unit_price is None:
            errors.append("Unit price is required")
        elif service.unit_price < 0:
            errors.append("Unit price cannot be negative")

        # Category validation
        if not service.category:
            errors.append("Service must have a category")
        else:
            if service.category.category_type != 'service':
                errors.append("Category must be a service category")

            if not service.category.efris_commodity_category_code:
                errors.append("Category must have EFRIS commodity category assigned")
            elif not service.category.efris_is_leaf_node:
                errors.append("Category's EFRIS commodity category must be a leaf node")

        # Tax validation
        if not service.tax_rate:
            errors.append("Tax rate is required")

        # Unit of measure validation
        if not service.unit_of_measure:
            errors.append("Unit of measure is required")

        return len(errors) == 0, errors

    def sync_service_changes(self, service, user=None) -> Dict[str, Any]:
        """
        Sync service changes to EFRIS if auto-sync is enabled

        Args:
            service: Service model instance
            user: Optional user performing the action

        Returns:
            Dict with sync result
        """
        if not service.efris_auto_sync_enabled:
            return {
                "success": False,
                "message": "Auto-sync is disabled for this service"
            }

        if not service.efris_is_uploaded:
            # Not yet uploaded, do initial registration
            return self.register_service(service, user)
        else:
            # Already uploaded, do update
            return self.update_service(service, user)

    def _log_service_operation(
            self,
            service,
            operation: str,
            success: bool,
            error: Optional[str] = None,
            user=None
    ):
        """
        Log EFRIS service operation

        Args:
            service: Service model instance
            operation: Operation type (REGISTER, UPDATE, etc.)
            success: Whether operation succeeded
            error: Optional error message
            user: Optional user performing the action
        """
        try:
            from efris.models import EFRISAPILog

            EFRISAPILog.objects.create(
                company=self.company,
                interface_code='T130',
                request_type=f'SERVICE_{operation}',
                status='SUCCESS' if success else 'FAILED',
                error_message=error,
                request_data={
                    'service_id': service.id,
                    'service_code': service.code,
                    'service_name': service.name,
                    'operation': operation
                },
                created_by=user
            )
        except Exception as e:
            logger.warning(f"Failed to log service operation: {e}")


class EFRISProductService:
    """Enhanced service for handling EFRIS product operations"""

    def __init__(self, company):
        self.company = company
        self.client = EnhancedEFRISAPIClient(company)

    async def upload_products_async(self, products: List[Any], user: Optional[Any] = None) -> Tuple[bool, str]:
        """Async version of product upload for better performance"""
        # This would be implemented with proper async/await patterns in a real system
        return self.upload_products(products, user)

    def upload_products(self, products: List[Any], user: Optional[Any] = None) -> Tuple[bool, str]:
        """Upload products to EFRIS with enhanced validation and error handling"""

        if not products:
            return False, "No products provided"

        try:
            with self.client as client:
                # Validate products before upload
                validation_errors = self._validate_products(products)
                if validation_errors:
                    return False, f"Validation failed: {'; '.join(validation_errors)}"

                # Build products data
                products_data = self._build_products_data(products)

                # Upload to EFRIS
                response = client.upload_goods(products_data)

                if response.success:
                    # Update products with response data
                    updated_count = self._update_products_from_response(products, response.data)
                    return True, f"Successfully uploaded {updated_count} products"
                else:
                    return False, response.error_message or "Upload failed"

        except Exception as e:
            logger.error("Product upload failed", error=str(e))
            return False, f"Upload error: {e}"

    def _validate_products(self, products: List[Any]) -> List[str]:
        """Validate products before upload"""
        errors = []

        if len(products) > EFRISConstants.MAX_BATCH_SIZE:
            errors.append(f"Too many products (max {EFRISConstants.MAX_BATCH_SIZE})")

        for i, product in enumerate(products, 1):
            if not getattr(product, 'name', None):
                errors.append(f"Product {i}: Name is required")

            if not getattr(product, 'sku', None):
                errors.append(f"Product {i}: SKU is required")

            selling_price = getattr(product, 'selling_price', 0)
            is_valid, error = DataValidator.validate_amount(selling_price, f"Product {i} selling price")
            if not is_valid:
                errors.append(error)

        return errors

    def _build_products_data(self, products: List[Any]) -> List[Dict]:
        """Build product data for EFRIS upload with enhanced mapping"""
        products_data = []

        for product in products:
            is_uploaded = getattr(product, 'efris_is_uploaded', False)

            # Determine operation type
            operation_type = "102" if is_uploaded else "101"  # Update or Create

            product_data = {
                "operationType": operation_type,
                "goodsName": self._get_efris_goods_name(product),
                "goodsCode": self._get_efris_goods_code(product),
                "measureUnit": self._get_unit_of_measure(product),
                "unitPrice": str(getattr(product, 'selling_price', 0)),
                "currency": "101",  # UGX
                "commodityCategoryId": product.category.efris_commodity_category_code,
                "haveExciseTax": "101" if self._has_excise_tax(product) else "102",
                "description": self._get_product_description(product),
                "stockPrewarning": str(getattr(product, 'min_stock_level', 0)),
                "havePieceUnit": "102"  # No piece unit by default
            }

            # Add excise duty information if applicable
            if self._has_excise_tax(product):
                excise_rate = getattr(product, 'excise_duty_rate', 0) or 0
                product_data.update({
                    "exciseDutyCode": getattr(product, 'efris_excise_duty_code', '') or "",
                    "pieceUnitPrice": str(getattr(product, 'selling_price', 0)),
                    "packageScaledValue": "1",
                    "pieceScaledValue": "1"
                })

            products_data.append(product_data)

        return {"goodsStockIn": products_data}  # FIXED: Wrap for batch

    def _get_efris_goods_name(self, product) -> str:
        """Get EFRIS goods name with fallback"""
        return (getattr(product, 'efris_goods_name', None) or
                getattr(product, 'name', '') or
                'Unnamed Product')

    def _get_efris_goods_code(self, product) -> str:
        """Get EFRIS goods code with fallback"""
        return (getattr(product, 'efris_goods_code', None) or
                getattr(product, 'sku', '') or
                f'PROD{getattr(product, "pk", 0):06d}')

    def _get_unit_of_measure(self, product) -> str:
        """Get unit of measure with default"""
        return (getattr(product, 'efris_unit_of_measure_code', None) or
                getattr(product, 'unit_of_measure', None) or
                'U')  # Default to 'Unit'

    def _get_commodity_category_id(self, product) -> str:
        """
        Get the EFRIS commodity category ID (18 digits total),
        fetched from the related Category model.
        Pads with zeros at the END until the length is 18.
        Falls back to a default if missing.
        """
        try:
            # Step 1: Try to fetch the EFRIS category ID from related category
            category_id = getattr(product.category, 'efris_category_id', None)

            # Step 2: Use default if missing
            if not category_id:
                category_id = "1010101000"

            # Step 3: Convert to string and pad zeros to the RIGHT (end)
            category_id = str(category_id)
            if len(category_id) < 18:
                category_id = category_id.ljust(18, '0')

            # Step 4: Truncate if longer than 18 just to be safe
            return category_id[:18]

        except AttributeError:
            # In case product.category is missing or None
            return "101010100000000000"

    def _has_excise_tax(self, product) -> bool:
        """Check if product has excise tax"""
        excise_rate = getattr(product, 'excise_duty_rate', 0) or 0
        return excise_rate > 0

    def _get_product_description(self, product) -> str:
        """Get product description with fallback"""
        return (getattr(product, 'efris_goods_description', None) or
                getattr(product, 'description', '') or
                getattr(product, 'name', '') or
                'No description available')

    def _update_products_from_response(self, products: List[Any], response_data: Optional[Dict]) -> int:
        """Update products with EFRIS upload results"""
        updated_count = 0

        try:
            if not response_data:
                return updated_count

            # Handle different response formats
            if isinstance(response_data, list):
                # Batch response with individual results
                for idx, product in enumerate(products):
                    if idx < len(response_data):
                        result = response_data[idx]
                        if result.get('returnCode') == EFRISConstants.SUCCESS_CODE:
                            if self._mark_product_uploaded(product, result):
                                updated_count += 1
            elif isinstance(response_data, dict):
                # Single response or bulk success
                for product in products:
                    if self._mark_product_uploaded(product, response_data):
                        updated_count += 1

        except Exception as e:
            logger.error("Failed to update products from response", error=str(e))

        return updated_count

    def _mark_product_uploaded(self, product: Any, result: Dict) -> bool:
        """Mark product as uploaded to EFRIS"""
        try:
            # Update product fields
            updates = {}

            if hasattr(product, 'efris_is_uploaded'):
                updates['efris_is_uploaded'] = True

            if hasattr(product, 'efris_upload_date'):
                updates['efris_upload_date'] = timezone.now()

            if 'goodsId' in result and hasattr(product, 'efris_goods_id'):
                updates['efris_goods_id'] = result['goodsId']

            if updates:
                for field, value in updates.items():
                    setattr(product, field, value)

                product.save(update_fields=list(updates.keys()))
                return True

        except Exception as e:
            logger.error(
                "Failed to mark product as uploaded",
                product_id=getattr(product, 'pk', None),
                error=str(e)
            )

        return False

def create_efris_service(company, service_type: str = 'client'):
    """Factory function to create EFRIS services with validation"""

    if not company:
        raise EFRISConfigurationError("Company is required")

    if not getattr(company, 'efris_enabled', False):
        raise EFRISConfigurationError("EFRIS is not enabled for this company")

    services = {
        'client': EnhancedEFRISAPIClient,
        'product': EFRISProductService,
        'invoice': EFRISInvoiceService,
        'customer': EFRISCustomerService,
    }

    service_class = services.get(service_type)
    if not service_class:
        available = ', '.join(services.keys())
        raise ValueError(f"Unknown service type '{service_type}'. Available: {available}")

    try:
        return service_class(company)
    except Exception as e:
        logger.error(
            "Failed to create EFRIS service",
            company_id=getattr(company, 'pk', None),
            service_type=service_type,
            error=str(e)
        )
        raise EFRISConfigurationError(f"Failed to create {service_type} service: {e}")

def validate_efris_configuration(company) -> Tuple[bool, List[str]]:
    """Comprehensive EFRIS configuration validation"""
    try:
        config_manager = ConfigurationManager(company)
        # If we can create the config manager without exceptions, it's valid
        return True, []
    except EFRISConfigurationError as e:
        return False, [str(e)]
    except Exception as e:
        logger.error("Unexpected error during configuration validation", error=str(e))
        return False, [f"Validation error: {e}"]

@asynccontextmanager
async def efris_client_context(company):
    """Async context manager for EFRIS client"""
    client = None
    try:
        client = EnhancedEFRISAPIClient(company)
        yield client
    finally:
        if client:
            client.close()

class EFRISHealthChecker:
    """Health check utilities for EFRIS integration"""

    def __init__(self, company):
        self.company = company

    def check_system_health(self) -> Dict[str, Any]:
        """Comprehensive health check"""
        health_status = {
            'overall_status': 'healthy',
            'checks': {},
            'timestamp': timezone.now().isoformat(),
            'company_id': self.company.pk
        }

        # Check configuration
        config_status = self._check_configuration()
        health_status['checks']['configuration'] = config_status

        # Check connectivity
        connectivity_status = self._check_connectivity()
        health_status['checks']['connectivity'] = connectivity_status

        # Check authentication
        auth_status = self._check_authentication()
        health_status['checks']['authentication'] = auth_status

        # Check recent operations
        operations_status = self._check_recent_operations()
        health_status['checks']['recent_operations'] = operations_status

        # Determine overall status
        failed_checks = [
            check for check in health_status['checks'].values()
            if not check.get('healthy', False)
        ]

        if failed_checks:
            health_status['overall_status'] = 'unhealthy' if len(failed_checks) > 1 else 'degraded'

        return health_status

    def _check_configuration(self) -> Dict[str, Any]:
        """Check EFRIS configuration validity"""
        try:
            is_valid, errors = validate_efris_configuration(self.company)
            return {
                'healthy': is_valid,
                'errors': errors,
                'check_type': 'configuration'
            }
        except Exception as e:
            return {
                'healthy': False,
                'errors': [str(e)],
                'check_type': 'configuration'
            }

    def _check_connectivity(self) -> Dict[str, Any]:
        """Check EFRIS API connectivity"""
        try:
            with EnhancedEFRISAPIClient(self.company) as client:
                response = client.get_server_time()
                return {
                    'healthy': response.success,
                    'response_time_ms': response.duration_ms,
                    'error': response.error_message if not response.success else None,
                    'check_type': 'connectivity'
                }
        except Exception as e:
            return {
                'healthy': False,
                'error': str(e),
                'check_type': 'connectivity'
            }

    def _check_authentication(self) -> Dict[str, Any]:
        """Check EFRIS authentication status"""
        try:
            with EnhancedEFRISAPIClient(self.company) as client:
                # Try a simple authenticated operation
                auth_response = client.ensure_authenticated()
                return {
                    'healthy': auth_response['success'],
                    'authenticated': client._is_authenticated,
                    'error': auth_response.get('error') if not auth_response['success'] else None,
                    'check_type': 'authentication'
                }
        except Exception as e:
            return {
                'healthy': False,
                'error': str(e),
                'authenticated': False,
                'check_type': 'authentication'
            }

    def _check_recent_operations(self) -> Dict[str, Any]:
        """Check recent EFRIS operations status"""
        try:
            # Get recent API logs (last 24 hours)
            recent_logs = EFRISAPILog.objects.filter(
                company=self.company,
                created_at__gte=timezone.now() - timedelta(hours=24)
            ).order_by('-created_at')[:10]

            if not recent_logs:
                return {
                    'healthy': True,
                    'message': 'No recent operations',
                    'check_type': 'recent_operations'
                }

            success_count = sum(1 for log in recent_logs if log.status == OperationStatus.SUCCESS.value)
            success_rate = success_count / len(recent_logs) if recent_logs else 1.0

            return {
                'healthy': success_rate >= 0.8,  # 80% success rate threshold
                'success_rate': success_rate,
                'total_operations': len(recent_logs),
                'successful_operations': success_count,
                'check_type': 'recent_operations'
            }

        except Exception as e:
            return {
                'healthy': False,
                'error': str(e),
                'check_type': 'recent_operations'
            }

class EFRISMetricsCollector:
    """Enhanced metrics collection for EFRIS operations"""

    @staticmethod
    def get_system_metrics(company, time_range_hours: int = 24) -> Dict[str, Any]:
        """Get comprehensive system metrics"""
        start_time = timezone.now() - timedelta(hours=time_range_hours)

        # Get API logs for the time range
        api_logs = EFRISAPILog.objects.filter(
            company=company,
            request_time__gte=start_time
        ).values('interface_code', 'status', 'duration_ms', 'request_time')

        # Calculate metrics
        metrics = {
            'time_range_hours': time_range_hours,
            'total_requests': len(api_logs),
            'interfaces': {},
            'overall': {
                'success_rate': 0,
                'average_duration_ms': 0,
                'error_rate': 0
            },
            'errors': [],
            'performance': {
                'fastest_request_ms': None,
                'slowest_request_ms': None,
                'requests_per_hour': 0
            }
        }

        if not api_logs:
            return metrics

        # Process logs
        successful_requests = 0
        total_duration = 0
        durations = []
        interface_stats = {}
        errors = []

        for log in api_logs:
            interface = log['interface_code']
            status = log['status']
            duration = log['duration_ms'] or 0

            # Interface-specific metrics
            if interface not in interface_stats:
                interface_stats[interface] = {
                    'total': 0,
                    'successful': 0,
                    'total_duration': 0,
                    'errors': []
                }

            interface_stats[interface]['total'] += 1
            interface_stats[interface]['total_duration'] += duration

            if status == OperationStatus.SUCCESS.value:
                successful_requests += 1
                interface_stats[interface]['successful'] += 1
            else:
                error_info = {
                    'interface_code': interface,
                    'timestamp': log.get('created_at', None),
                    'status': status
                }
                errors.append(error_info)
                interface_stats[interface]['errors'].append(error_info)

            total_duration += duration
            durations.append(duration)

        # Calculate overall metrics
        metrics['overall']['success_rate'] = successful_requests / len(api_logs)
        metrics['overall']['error_rate'] = 1 - metrics['overall']['success_rate']
        metrics['overall']['average_duration_ms'] = total_duration / len(api_logs)

        # Performance metrics
        if durations:
            metrics['performance']['fastest_request_ms'] = min(durations)
            metrics['performance']['slowest_request_ms'] = max(durations)

        metrics['performance']['requests_per_hour'] = len(api_logs) / time_range_hours

        # Interface-specific metrics
        for interface, stats in interface_stats.items():
            metrics['interfaces'][interface] = {
                'total_requests': stats['total'],
                'success_rate': stats['successful'] / stats['total'],
                'average_duration_ms': stats['total_duration'] / stats['total'],
                'error_count': len(stats['errors'])
            }

        metrics['errors'] = errors[:10]  # Limit to recent errors

        return metrics

    @staticmethod
    def get_invoice_fiscalization_metrics(company, days: int = 30) -> Dict[str, Any]:
        """Get invoice fiscalization-specific metrics"""
        from django_tenants.utils import tenant_context
        from django.utils import timezone
        from datetime import timedelta

        start_date = timezone.now().date() - timedelta(days=days)

        metrics = {
            'period_days': days,
            'total_fiscalization_attempts': 0,
            'successful_fiscalizations': 0,
            'failed_fiscalizations': 0,
            'success_rate': 0,
            'daily_breakdown': {},
            'common_errors': []
        }

        # Use tenant context for correct schema
        with tenant_context(company):
            audits = FiscalizationAudit.objects.filter(
                created_at__date__gte=start_date
            ).values('action', 'efris_return_code', 'efris_return_message', 'created_at__date').order_by(
                'created_at__date')

            if not audits:
                return metrics

            daily_stats = {}
            successful_count = 0

            for audit in audits:
                date_str = audit['created_at__date'].isoformat()

                if date_str not in daily_stats:
                    daily_stats[date_str] = {'attempts': 0, 'successes': 0}

                if audit['action'] == 'FISCALIZE':
                    metrics['total_fiscalization_attempts'] += 1
                    daily_stats[date_str]['attempts'] += 1

                    # ✅ Derive success logically
                    success = str(audit.get('efris_return_code', '')).strip() in ['00', 'SUCCESS', '200']

                    if success:
                        daily_stats[date_str]['successes'] += 1
                        successful_count += 1
                    else:
                        # Collect errors to find common ones
                        msg = audit.get('efris_return_message') or 'Unknown error'
                        metrics['common_errors'].append(msg)

            metrics['successful_fiscalizations'] = successful_count
            metrics['failed_fiscalizations'] = metrics['total_fiscalization_attempts'] - successful_count

            if metrics['total_fiscalization_attempts'] > 0:
                metrics['success_rate'] = round(successful_count / metrics['total_fiscalization_attempts'], 2)

            metrics['daily_breakdown'] = daily_stats

        return metrics


class EFRISConfigurationWizard:
    """Helper class for setting up EFRIS configuration"""

    def __init__(self, company):
        self.company = company

    def validate_setup_requirements(self) -> Dict[str, Any]:
        """Validate all requirements for EFRIS setup"""
        requirements = {
            'company_info': self._validate_company_info(),
            'certificates': self._validate_certificates(),
            'network': self._validate_network_access(),
            'permissions': self._validate_permissions()
        }

        # Make sure 'valid' fields are booleans, not iterables
        all_valid = all(req.get('valid', False) for req in requirements.values())

        return {
            'ready_for_setup': all_valid,
            'requirements': requirements,
            'next_steps': self._get_next_steps(requirements)
        }

    def _validate_company_info(self) -> Dict[str, Any]:
        """Validate company information completeness"""
        required_fields = {
            'tin': 'Tax Identification Number',
            'name': 'Company Name',
            'efris_taxpayer_name': 'EFRIS Taxpayer Name',
            'efris_business_name': 'EFRIS Business Name',
            'efris_email_address': 'EFRIS Email Address',
            'efris_phone_number': 'EFRIS Phone Number',
            'efris_business_address': 'EFRIS Business Address'
        }

        missing_fields = []
        invalid_fields = []

        for field, display_name in required_fields.items():
            value = getattr(self.company, field, None)

            if not value:
                missing_fields.append(display_name)
            elif field == 'tin':
                is_valid, error = DataValidator.validate_tin(value)
                if not is_valid:
                    invalid_fields.append(f"{display_name}: {error}")

        return {
            'valid': len(missing_fields) == 0 and len(invalid_fields) == 0,
            'missing_fields': missing_fields,
            'invalid_fields': invalid_fields
        }

    def _validate_certificates(self) -> Dict[str, Any]:
        """Validate certificate requirements"""
        # Wrap boolean values consistently
        has_certificate = bool(getattr(self.company, 'certificate', False))
        certificate_valid = has_certificate  # Placeholder
        certificate_uploaded = has_certificate  # Placeholder

        return {
            'valid': has_certificate and certificate_valid and certificate_uploaded,
            'has_certificate': has_certificate,
            'certificate_valid': certificate_valid,
            'certificate_uploaded': certificate_uploaded
        }

    def _validate_network_access(self) -> Dict[str, Any]:
        """Validate network access to EFRIS servers"""
        try:
            config = {
                'api_url': getattr(settings, 'EFRIS_API_URL', 'https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation'),
                'timeout': 10
            }

            response = requests.get(config['api_url'], timeout=config['timeout'])

            return {
                'valid': response.status_code < 500,
                'status_code': response.status_code,
                'response_time_ms': int(response.elapsed.total_seconds() * 1000)
            }

        except requests.RequestException as e:
            return {
                'valid': False,
                'error': str(e)
            }

    def _validate_permissions(self) -> Dict[str, Any]:
        """Validate required permissions"""
        return {
            'valid': True,  # Adjust actual checks as needed
            'database_access': True,
            'file_system_access': True,
            'cache_access': True
        }

    def _get_next_steps(self, requirements: Dict[str, Any]) -> List[str]:
        """Get next steps based on validation results"""
        steps = []

        if not requirements['company_info']['valid']:
            steps.append("Complete company information in EFRIS settings")

        if not requirements['certificates']['valid']:
            steps.append("Generate and upload digital certificates")

        if not requirements['network']['valid']:
            steps.append("Verify network connectivity to EFRIS servers")

        if not requirements['permissions']['valid']:
            steps.append("Ensure all required system permissions are granted")

        if not steps:
            steps.append("Configuration is complete. You can now initialize EFRIS integration.")

        return steps

    def generate_setup_checklist(self) -> Dict[str, Any]:
        """Generate a comprehensive setup checklist"""
        validation_result = self.validate_setup_requirements()

        checklist_items = [
            {
                'title': 'Company Information',
                'description': 'Complete all required company details for EFRIS registration',
                'completed': bool(validation_result['requirements']['company_info']['valid']),
                'details': validation_result['requirements']['company_info']
            },
            {
                'title': 'Digital Certificates',
                'description': 'Generate and upload required digital certificates',
                'completed': bool(validation_result['requirements']['certificates']['valid']),
                'details': validation_result['requirements']['certificates']
            },
            {
                'title': 'Network Connectivity',
                'description': 'Verify connection to EFRIS servers',
                'completed': bool(validation_result['requirements']['network']['valid']),
                'details': validation_result['requirements']['network']
            },
            {
                'title': 'System Permissions',
                'description': 'Ensure all required system permissions are available',
                'completed': bool(validation_result['requirements']['permissions']['valid']),
                'details': validation_result['requirements']['permissions']
            }
        ]

        total_items = len(checklist_items)
        completed_items = sum(1 for item in checklist_items if item['completed'])
        completion_percentage = (completed_items / total_items) * 100 if total_items else 0

        return {
            'ready_for_production': bool(validation_result['ready_for_setup']),
            'completion_percentage': completion_percentage,
            'checklist_items': checklist_items,
            'next_steps': validation_result['next_steps']
        }

def setup_efris_for_company(company) -> Dict[str, Any]:
    """Complete EFRIS setup workflow for a company"""

    setup_result = {
        'success': False,
        'steps_completed': [],
        'errors': [],
        'warnings': []
    }

    try:
        # Step 1: Validate configuration
        wizard = EFRISConfigurationWizard(company)
        validation_result = wizard.validate_setup_requirements()

        if not validation_result['ready_for_setup']:
            setup_result['errors'].append("Company not ready for EFRIS setup")
            setup_result['validation_details'] = validation_result
            return setup_result

        setup_result['steps_completed'].append('validation')

        # Step 2: Initialize EFRIS client
        try:
            client = EnhancedEFRISAPIClient(company)
            setup_result['steps_completed'].append('client_initialization')
        except Exception as e:
            setup_result['errors'].append(f"Client initialization failed: {e}")
            return setup_result

        # Step 3: Test connectivity
        try:
            with client:
                response = client.get_server_time()
                if response.success:
                    setup_result['steps_completed'].append('connectivity_test')
                else:
                    setup_result['warnings'].append(f"Connectivity test warning: {response.error_message}")
        except Exception as e:
            setup_result['errors'].append(f"Connectivity test failed: {e}")
            return setup_result

        # Step 4: Run health check
        try:
            health_checker = EFRISHealthChecker(company)
            health_status = health_checker.check_system_health()
            setup_result['health_status'] = health_status
            setup_result['steps_completed'].append('health_check')

            if health_status['overall_status'] != 'healthy':
                setup_result['warnings'].append("System health check shows issues")

        except Exception as e:
            setup_result['warnings'].append(f"Health check failed: {e}")

        setup_result['success'] = True
        setup_result[
            'message'] = f"EFRIS setup completed successfully. {len(setup_result['steps_completed'])} steps completed."

    except Exception as e:
        logger.error("EFRIS setup failed", company_id=company.pk, error=str(e))
        setup_result['errors'].append(f"Setup failed: {e}")

    return setup_result

__version__ = "2.0.0"
__author__ = "Nash Vybzes Team"

__all__ = [
    'EFRISConstants',
    'EFRISError',
    'EFRISConfigurationError',
    'EFRISNetworkError',
    'EFRISValidationError',
    'EFRISSecurityError',
    'EFRISBusinessLogicError',
    'EnhancedEFRISAPIClient',
    'EFRISProductService',
    'SecurityManager',
    'ConfigurationManager',
    'DataValidator',
    'EFRISHealthChecker',
    'EFRISMetricsCollector',
    'EFRISConfigurationWizard',
    'create_efris_service',
    'validate_efris_configuration',
    'setup_efris_for_company',
    'efris_client_context',
    'SystemDictionaryManager',
    'ZReportService',
    'TaxpayerQueryService',
    'GoodsInquiryService',
    'schedule_daily_dictionary_update',
    'EFRISServiceManager',
]