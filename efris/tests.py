# import json
# import base64
# import uuid
# import secrets
# import string
# import os
# import pytz
# from datetime import datetime, timedelta
# from decimal import Decimal, InvalidOperation
# from typing import Dict, List, Optional, Tuple, Any, Union
# from dataclasses import dataclass, field
# from enum import Enum
# from contextlib import asynccontextmanager
# 
# import requests
# import structlog
# from requests.adapters import HTTPAdapter
# from urllib3.util.retry import Retry
# from cryptography.hazmat.primitives import serialization, hashes
# from cryptography.hazmat.primitives.asymmetric import rsa, padding
# from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
# from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
# from cryptography.fernet import Fernet
# from typing import Dict, Optional, Union, Tuple
# from cryptography.hazmat.primitives import hashes, padding
# from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
# from cryptography.hazmat.primitives.asymmetric import rsa, padding as rsa_padding
# from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
# from cryptography.fernet import Fernet
# import logging
# from django.utils import timezone
# from django.utils import timezone
# from django.core.cache import cache
# from django.conf import settings
# from pydantic import BaseModel, field_validator, Field, ConfigDict
# 
# from .models import (
#     EFRISConfiguration, EFRISAPILog, FiscalizationAudit,
#     EFRISSystemDictionary
# )
# 
# logger = structlog.get_logger(__name__)
# 
# 
# class EFRISConstants:
#     class InterfaceCodes:
#         GET_SERVER_TIME = 'T101'
#         CLIENT_INITIALIZATION = 'T102'
#         LOGIN = 'T103'
#         GET_SYMMETRIC_KEY = 'T104'
#         UPLOAD_INVOICE = 'T109'
#         APPLY_CREDIT_NOTE = 'T110'
#         GET_SYSTEM_DICTIONARY = 'T115'
#         QUERY_TAXPAYER = 'T119'
#         GOODS_INQUIRY = 'T127'
#         BATCH_INVOICE_UPLOAD = 'T129'
#         UPLOAD_GOODS = 'T130'
#         GOODS_STOCK_MAINTAIN = 'T131'
#         UPLOAD_CERTIFICATE = 'T136'
# 
#     class DocumentTypes:
#         INVOICE = "1"
#         CREDIT_NOTE = "2"
#         DEBIT_NOTE = "3"
# 
#     PAYMENT_MODES = {
#         'CASH': '102',
#         'CARD': '106',
#         'MOBILE_MONEY': '105',
#         'BANK_TRANSFER': '107',
#         'VOUCHER': '101',
#         'CREDIT': '101'
#     }
# 
#     STANDARD_VAT_RATE = Decimal("0.18")
#     ZERO_VAT_RATE = Decimal("0")
#     EXEMPT_VAT = "-"
# 
#     SUCCESS_CODE = "00"
#     TIMEOUT_CODE = "99"
# 
#     class BuyerTypes:
#         B2B = "0"
#         B2C = "1"
#         B2G = "3"
# 
#     DEFAULT_TIMEOUT = 30
#     DEFAULT_RETRY_COUNT = 3
#     MAX_BATCH_SIZE = 100
# 
# 
# class OperationStatus(Enum):
#     SUCCESS = "success"
#     FAILED = "failed"
#     TIMEOUT = "timeout"
#     PENDING = "pending"
#     RETRYING = "retrying"
#     CANCELLED = "cancelled"
# 
# 
# class EFRISErrorSeverity(Enum):
#     LOW = "low"
#     MEDIUM = "medium"
#     HIGH = "high"
#     CRITICAL = "critical"
# 
# 
# class EFRISError(Exception):
#     def __init__(
#             self,
#             message: str,
#             error_code: Optional[str] = None,
#             details: Optional[Dict] = None,
#             severity: EFRISErrorSeverity = EFRISErrorSeverity.MEDIUM,
#             retryable: bool = False
#     ):
#         self.message = message
#         self.error_code = error_code
#         self.details = details or {}
#         self.severity = severity
#         self.retryable = retryable
#         super().__init__(self.message)
# 
#     def to_dict(self) -> Dict[str, Any]:
#         return {
#             "message": self.message,
#             "error_code": self.error_code,
#             "details": self.details,
#             "severity": self.severity.value,
#             "retryable": self.retryable,
#             "exception_type": self.__class__.__name__
#         }
# 
# 
# class EFRISConfigurationError(EFRISError):
#     def __init__(self, message: str, **kwargs):
#         super().__init__(message, severity=EFRISErrorSeverity.HIGH, **kwargs)
# 
# 
# class EFRISNetworkError(EFRISError):
#     def __init__(self, message: str, **kwargs):
#         super().__init__(message, severity=EFRISErrorSeverity.MEDIUM, retryable=True, **kwargs)
# 
# 
# class EFRISValidationError(EFRISError):
#     def __init__(self, message: str, **kwargs):
#         super().__init__(message, severity=EFRISErrorSeverity.HIGH, **kwargs)
# 
# 
# class EFRISSecurityError(EFRISError):
#     """Security related errors"""
# 
#     def __init__(self, message: str, **kwargs):
#         super().__init__(message, severity=EFRISErrorSeverity.CRITICAL, **kwargs)
# 
# 
# class EFRISBusinessLogicError(EFRISError):
#     def __init__(self, message: str, **kwargs):
#         super().__init__(message, severity=EFRISErrorSeverity.MEDIUM, **kwargs)
# 
# 
# class InvoiceData(BaseModel):
#     model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)
# 
#     invoice_number: str = Field(..., min_length=1, max_length=50)
#     issue_date: datetime
#     total_amount: Decimal = Field(..., ge=0)
#     tax_amount: Decimal = Field(..., ge=0)
#     subtotal: Decimal = Field(..., ge=0)
#     discount_amount: Decimal = Field(default=Decimal('0'), ge=0)
#     currency_code: str = Field(default="UGX", pattern="^[A-Z]{3}$")
#     document_type: str = Field(..., pattern="^[1-3]$")
# 
#     @field_validator('total_amount', 'tax_amount', 'subtotal', 'discount_amount')
#     @classmethod
#     def validate_decimal_precision(cls, v: Decimal) -> Decimal:
#         if v.as_tuple().exponent < -2:
#             raise ValueError('Amount precision cannot exceed 2 decimal places')
#         return v.quantize(Decimal('0.01'))
# 
#     @field_validator('currency_code')
#     @classmethod
#     def validate_currency(cls, v: str) -> str:
#         if v not in ["UGX", "USD", "EUR","KES", "GBP"]:
#             raise ValueError(f'Unsupported currency: {v}')
#         return v
# 
#     def validate_amounts_consistency(self) -> bool:
#         expected_total = self.subtotal + self.tax_amount - self.discount_amount
#         return abs(self.total_amount - expected_total) <= Decimal('0.01')
# 
# 
# @dataclass
# class EFRISResponse:
#     success: bool
#     data: Optional[Dict] = None
#     error_message: Optional[str] = None
#     error_code: Optional[str] = None
#     duration_ms: Optional[int] = None
#     retryable: bool = False
#     timestamp: datetime = field(default_factory=timezone.now)
#     metadata: Dict[str, Any] = field(default_factory=dict)
# 
#     def is_retry_candidate(self) -> bool:
#         if self.success:
#             return False
# 
#         retryable_codes = ['99', 'TIMEOUT', 'CONNECTION_ERROR']
#         return self.error_code in retryable_codes or self.retryable
# 
# 
# class SecurityManager:
#     """EFRIS Security Manager - Handles encryption, decryption, and signing"""
# 
#     def __init__(self, device_no: str, tin: str):
#         self.device_no = device_no
#         self.tin = tin
#         self.app_id = "AP04"
#         self._current_aes_key = None
#         self._aes_key_expiry = None
# 
#     # ============ TIME & UTILITY METHODS ============
# 
#     def get_utc_plus_3_time(self) -> str:
#         """Get current time in UTC+3 format for EFRIS requestTime"""
#         try:
#             utc_time = datetime.now(pytz.UTC)
#             utc_plus_3 = utc_time + timedelta(hours=3)
#             return utc_plus_3.strftime('%Y-%m-%d %H:%M:%S')
#         except Exception as e:
#             logger.warning(f"Failed to get UTC+3 time: {e}")
#             return timezone.now().strftime('%Y-%m-%d %H:%M:%S')
# 
#     # ============ AES KEY MANAGEMENT ============
# 
#     def generate_aes_key(self, key_length: int = 16) -> bytes:
#         """Generate AES key (16 bytes for AES-128)"""
#         if key_length not in [8, 16, 32]:
#             raise ValueError(f"Unsupported key length: {key_length}")
#         return os.urandom(key_length)
# 
#     def get_current_aes_key(self) -> Optional[bytes]:
#         """Get current valid AES key"""
#         # Check instance cache first
#         if self.is_aes_key_valid():
#             logger.debug("Using valid instance AES key")
#             return self._current_aes_key
# 
#         # Check Django cache
#         cache_key = f"efris_aes_key_{self.tin}_{self.device_no}"
#         cached_data = cache.get(cache_key)
#         if cached_data:
#             try:
#                 key_data, expiry_str = cached_data
#                 expiry = datetime.fromisoformat(expiry_str)
#                 if timezone.now() < expiry:
#                     self._current_aes_key = key_data
#                     self._aes_key_expiry = expiry
#                     logger.debug("Retrieved valid AES key from cache")
#                     return key_data
#             except (ValueError, TypeError) as e:
#                 logger.debug(f"Error parsing cached AES key: {e}")
# 
#         return None
# 
#     def set_current_aes_key(self, aes_key: bytes, expiry_hours: int = 24):
#         """Store AES key with caching"""
#         self._current_aes_key = aes_key
#         self._aes_key_expiry = timezone.now() + timedelta(hours=expiry_hours)
# 
#         # Cache for multi-process access
#         cache_key = f"efris_aes_key_{self.tin}_{self.device_no}"
#         cache_value = (aes_key, self._aes_key_expiry.isoformat())
#         cache.set(cache_key, cache_value, timeout=expiry_hours * 3600)
#         logger.info(f"AES key cached for {expiry_hours} hours")
# 
#     def is_aes_key_valid(self) -> bool:
#         """Check if current AES key is still valid"""
#         if not self._current_aes_key or not self._aes_key_expiry:
#             return False
#         return timezone.now() < self._aes_key_expiry
# 
#     # ============ ENCRYPTION & DECRYPTION ============
# 
#     def _prepare_aes_key(self, aes_key: bytes) -> bytes:
#         """Prepare AES key for use"""
#         key_length = len(aes_key)
#         if key_length == 8:
#             return aes_key + aes_key  # Duplicate for 16 bytes
#         elif key_length in [16, 32]:
#             return aes_key
#         else:
#             raise Exception(f"Unsupported AES key length: {key_length}")
# 
#     def encrypt_with_aes(self, content: str, aes_key: bytes) -> str:
#         """Encrypt content using AES ECB mode with PKCS7 padding"""
#         if not content:
#             return ""
# 
#         try:
#             key_to_use = self._prepare_aes_key(aes_key)
#             content_bytes = content.encode('utf-8')
# 
#             # Use ECB mode (EFRIS standard)
#             cipher = Cipher(algorithms.AES(key_to_use), modes.ECB())
#             encryptor = cipher.encryptor()
# 
#             # Add PKCS7 padding
#             padder = padding.PKCS7(128).padder()
#             padded_data = padder.update(content_bytes) + padder.finalize()
# 
#             # Encrypt
#             encrypted_data = encryptor.update(padded_data) + encryptor.finalize()
#             encrypted_b64 = base64.b64encode(encrypted_data).decode('utf-8')
# 
#             logger.debug(f"AES encryption: {len(content)} chars -> {len(encrypted_b64)} base64")
#             return encrypted_b64
# 
#         except Exception as e:
#             logger.error(f"AES encryption failed: {e}")
#             raise Exception(f"AES encryption failed: {e}")
# 
#     def decrypt_with_aes(self, encrypted_content: str, aes_key: bytes) -> str:
#         """Decrypt AES encrypted content"""
#         try:
#             key_to_use = self._prepare_aes_key(aes_key)
#             encrypted_data = base64.b64decode(encrypted_content)
# 
#             cipher = Cipher(algorithms.AES(key_to_use), modes.ECB())
#             decryptor = cipher.decryptor()
#             decrypted_padded = decryptor.update(encrypted_data) + decryptor.finalize()
# 
#             # Remove PKCS7 padding
#             try:
#                 unpadder = padding.PKCS7(128).unpadder()
#                 decrypted = unpadder.update(decrypted_padded) + unpadder.finalize()
#             except ValueError:
#                 # Fallback padding removal
#                 pad_length = decrypted_padded[-1] if decrypted_padded else 0
#                 if 0 < pad_length <= 16:
#                     decrypted = decrypted_padded[:-pad_length]
#                 else:
#                     decrypted = decrypted_padded
# 
#             result = decrypted.decode('utf-8')
#             logger.debug(f"AES decryption successful: {len(result)} chars")
#             return result
# 
#         except Exception as e:
#             logger.error(f"AES decryption failed: {e}")
#             raise Exception(f"AES decryption failed: {e}")
# 
#     # ============ SIGNATURE GENERATION ============
# 
#     def sign_content(self, content: str, private_key: rsa.RSAPrivateKey) -> str:
#         """
#         Sign content using SHA1withRSA (EFRIS requirement from documentation)
#         """
#         if not content:
#             return ""
# 
#         try:
#             content_bytes = content.encode('utf-8')
# 
#             # Use SHA1 as required by EFRIS documentation
#             signature = private_key.sign(
#                 content_bytes,
#                 rsa_padding.PKCS1v15(),
#                 hashes.SHA1()  # EFRIS requires SHA1withRSA
#             )
# 
#             signature_b64 = base64.b64encode(signature).decode('utf-8')
#             logger.info(f"Signature generated with SHA1: {len(signature_b64)} chars")
#             return signature_b64
# 
#         except Exception as e:
#             logger.error(f"Signature generation failed: {e}")
#             raise Exception(f"Signature generation failed: {e}")
# 
#     def create_signed_encrypted_request(self, interface_code: str, content: Dict,
#                                         private_key: rsa.RSAPrivateKey) -> Dict:
#         """
#         Create EFRIS request following official documentation:
#         1. Serialize content
#         2. Encrypt with AES (step 5-6)
#         3. Sign encrypted content with RSA SHA1 (step 7)
#         """
#         try:
#             aes_key = self.get_current_aes_key()
#             if not aes_key:
#                 raise Exception("No valid AES key available")
#
#             # 1. Serialize content with canonical format
#             content_json = json.dumps(content, separators=(',', ':'), ensure_ascii=False, sort_keys=True)
#             logger.debug(f"Content JSON length: {len(content_json)}")
#
#             # 2. Encrypt content first (EFRIS step 5-6)
#             encrypted_content = self.encrypt_with_aes(content_json, aes_key)
#             logger.debug(f"Encrypted content length: {len(encrypted_content)}")
#
#             # 3. Sign the encrypted content (EFRIS step 7)
#             signature = self.sign_content(encrypted_content, private_key)
#             logger.debug(f"Generated signature length: {len(signature)}")
#
#             # 4. Build request envelope
#             request = {
#                 "data": {
#                     "content": encrypted_content,
#                     "signature": signature,
#                     "dataDescription": {
#                         "codeType": "1",
#                         "encryptCode": "1",
#                         "zipCode": "0"
#                     }
#                 },
#                 "globalInfo": self.create_global_info(interface_code),
#                 "returnStateInfo": {
#                     "returnCode": "",
#                     "returnMessage": ""
#                 }
#             }
#
#             return request
#
#         except Exception as e:
#             logger.error(f"Request creation failed: {e}")
#             raise Exception(f"Request creation failed: {e}")

#     # ============ RSA OPERATIONS ============
# 
#     def decrypt_aes_key(self, encrypted_key: str, private_key: rsa.RSAPrivateKey) -> bytes:
#         """Decrypt AES key from T104 response using RSA private key"""
#         try:
#             encrypted_bytes = base64.b64decode(encrypted_key)
#             logger.debug(f"RSA decrypting AES key: {len(encrypted_bytes)} bytes")
# 
#             decrypted = private_key.decrypt(
#                 encrypted_bytes,
#                 rsa_padding.PKCS1v15()
#             )
#             logger.debug(f"RSA decryption successful: {len(decrypted)} bytes")
#             return decrypted
# 
#         except Exception as e:
#             logger.error(f"RSA decryption failed: {e}")
#             raise Exception(f"AES key decryption failed: {e}")
# 
#     def process_t104_response(self, response_data: Dict, private_key) -> Dict:
#         """Process T104 response to extract and cache AES key"""
#         try:
#             content = response_data.get("content", "")
#             if not content:
#                 logger.warning("No content in T104 response")
#                 return {"aes_key": None, "success": False, "error": "No content"}
# 
#             # Decode content
#             try:
#                 decoded_content = base64.b64decode(content).decode("utf-8")
#                 content_data = json.loads(decoded_content)
#             except Exception as e:
#                 logger.error(f"Failed to decode T104 content: {e}")
#                 return {"aes_key": None, "success": False, "error": f"Decode failed: {e}"}
# 
#             # Look for encrypted AES key (multiple field names possible)
#             encrypted_aes_key = (content_data.get("passowrdDes") or
#                                 content_data.get("passwordDes") or
#                                 content_data.get("passWordDes") or
#                                 content_data.get("password"))
# 
#             if not encrypted_aes_key:
#                 available_fields = list(content_data.keys())
#                 logger.warning(f"No encrypted AES key found. Available: {available_fields}")
#                 return {"aes_key": None, "success": False, "error": "No encrypted key found"}
# 
#             # Decrypt with RSA
#             rsa_decrypted_bytes = self.decrypt_aes_key(encrypted_aes_key, private_key)
# 
#             # Handle potential Base64 encoding
#             try:
#                 actual_aes_key = base64.b64decode(rsa_decrypted_bytes)
#                 logger.debug(f"Base64 decoded AES key: {len(actual_aes_key)} bytes")
#             except Exception:
#                 actual_aes_key = rsa_decrypted_bytes
# 
#             # Validate key length and cache
#             if actual_aes_key and len(actual_aes_key) in [8, 16, 32]:
#                 self.set_current_aes_key(actual_aes_key)
#                 logger.info(f"T104 AES key processed and cached: {len(actual_aes_key)} bytes")
#                 return {
#                     "aes_key": actual_aes_key,
#                     "signature": response_data.get("signature", ""),
#                     "success": True
#                 }
#             else:
#                 error = f"Invalid AES key length: {len(actual_aes_key) if actual_aes_key else 0}"
#                 logger.error(error)
#                 return {"aes_key": None, "success": False, "error": error}
# 
#         except Exception as e:
#             logger.error(f"T104 processing failed: {e}")
#             return {"aes_key": None, "success": False, "error": str(e)}
# 
#     # ============ EFRIS REQUEST HELPERS ============
# 
#     def create_global_info(self, interface_code: str) -> Dict:
#         """Create globalInfo section for EFRIS requests"""
#         return {
#             "appId": self.app_id,
#             "version": "1.1.20191201",
#             "dataExchangeId": str(uuid.uuid4()).replace('-', '')[:32],
#             "interfaceCode": interface_code,
#             "requestCode": "TP",
#             "requestTime": self.get_utc_plus_3_time(),
#             "responseCode": "TA",
#             "userName": "admin",
#             "deviceMAC": "FFFFFFFFFFFF",
#             "deviceNo": self.device_no,
#             "tin": self.tin,
#             "brn": "",
#             "taxpayerID": "1",
#             "longitude": "32.5825",
#             "latitude": "0.3476",
#             "agentType": "0"
#         }
# 
# 
# class ConfigurationManager:
#     """Enhanced configuration management"""
# 
#     def __init__(self, company):
#         self.company = company
#         self._config_cache = {}
#         self._last_validation = None
#         self.config = self._load_and_validate_config()
# 
#     def _load_and_validate_config(self) -> EFRISConfiguration:
#         """Load and validate EFRIS configuration with caching"""
#         cache_key = f"efris_config_{self.company.pk}"
# 
#         # Check cache first
#         if cache_key in self._config_cache and self._is_cache_valid():
#             return self._config_cache[cache_key]
# 
#         try:
#             config = EFRISConfiguration.objects.select_related('company').get(
#                 company=self.company
#             )
# 
#             # Validate configuration
#             validation_errors = self._validate_config(config)
#             if validation_errors:
#                 raise EFRISConfigurationError(
#                     f"Configuration validation failed: {validation_errors}"
#                 )
# 
#             # Cache the config
#             self._config_cache[cache_key] = config
#             self._last_validation = timezone.now()
# 
#             return config
# 
#         except EFRISConfiguration.DoesNotExist:
#             raise EFRISConfigurationError(
#                 f"EFRIS configuration not found for company {self.company}"
#             )
# 
#     def _is_cache_valid(self) -> bool:
#         """Check if cached config is still valid"""
#         if not self._last_validation:
#             return False
# 
#         # Cache valid for 5 minutes
#         return (timezone.now() - self._last_validation) < timedelta(minutes=5)
# 
#     def _validate_config(self, config: EFRISConfiguration) -> List[str]:
#         """Comprehensive configuration validation"""
#         errors = []
# 
#         # Required fields validation
#         required_fields = {
#             'app_id': 'Application ID',
#             'version': 'Version',
#             'device_mac': 'Device MAC address',
#             'api_url': 'API URL'
#         }
# 
#         for field, display_name in required_fields.items():
#             if not getattr(config, field, None):
#                 errors.append(f"Missing {display_name}")
# 
#         # API URL validation
#         if config.api_url:
#             if not config.api_url.startswith('https://'):
#                 errors.append("API URL must use HTTPS")
# 
#             # Basic URL format validation
#             try:
#                 from urllib.parse import urlparse
#                 parsed = urlparse(config.api_url)
#                 if not parsed.netloc:
#                     errors.append("Invalid API URL format")
#             except Exception:
#                 errors.append("Invalid API URL format")
# 
#         # Company-specific validation
#         company_errors = self._validate_company_efris_settings()
#         errors.extend(company_errors)
# 
#         return errors
# 
#     def _validate_company_efris_settings(self) -> List[str]:
#         """Validate company EFRIS settings"""
#         errors = []
# 
#         if not self.company.efris_enabled:
#             return ["EFRIS is not enabled for this company"]
# 
#         required_company_fields = {
#             'tin': 'TIN',
#             'efris_taxpayer_name': 'Taxpayer name',
#             'efris_business_name': 'Business name',
#             'efris_email_address': 'Email address',
#             'efris_phone_number': 'Phone number',
#             'efris_business_address': 'Business address'
#         }
# 
#         for field, display_name in required_company_fields.items():
#             if not getattr(self.company, field, None):
#                 errors.append(f"Missing {display_name}")
# 
#         # Check EFRIS configuration fields separately
#         try:
#             efris_config = self.company.efris_config
#             if not efris_config.private_key:
#                 errors.append("Missing Private key")
#             if not efris_config.public_certificate:
#                 errors.append("Missing Public key")
#             if not efris_config.certificate_fingerprint:
#                 errors.append("Missing Thumbprint")
#         except AttributeError:
#             errors.append("Missing EFRIS configuration")
# 
#         # TIN format validation
#         if self.company.tin and not self._validate_tin_format(self.company.tin):
#             errors.append("Invalid TIN format")
# 
#         return errors
# 
#     def _validate_tin_format(self, tin: str) -> bool:
#         """Validate Uganda TIN format"""
#         if not tin or not isinstance(tin, str):
#             return False
# 
#         clean_tin = tin.replace(' ', '').replace('-', '')
#         return len(clean_tin) == 10 and clean_tin.isdigit()
# 
#     def get_api_config(self) -> Dict[str, Any]:
#         """Get API configuration with defaults"""
#         return {
#             'api_url': self.config.api_url,
#             'app_id': self.config.app_id,
#             'version': self.config.version,
#             'timeout': getattr(self.config, 'timeout_seconds', None) or EFRISConstants.DEFAULT_TIMEOUT,
#             'device_mac': self.config.device_mac,
#             'device_number': getattr(self.config, 'device_number', None) or '00000000000',
#             'mode': getattr(self.config, 'mode', 'online')
#         }
# 
#     def refresh_config(self) -> EFRISConfiguration:
#         """Force refresh configuration from database"""
#         cache_key = f"efris_config_{self.company.pk}"
#         if cache_key in self._config_cache:
#             del self._config_cache[cache_key]
# 
#         self._last_validation = None
#         return self._load_and_validate_config()
# 
# 
# class EnhancedHTTPClient:
#     """Enhanced HTTP client with better error handling and monitoring"""
# 
#     def __init__(self, config: Dict[str, Any]):
#         self.config = config
#         self.session = self._create_session()
#         self._request_count = 0
#         self._total_duration = 0
# 
#     def _create_session(self) -> requests.Session:
#         """Create optimized HTTP session"""
#         session = requests.Session()
# 
#         # Enhanced retry strategy
#         retry_strategy = Retry(
#             total=EFRISConstants.DEFAULT_RETRY_COUNT,
#             backoff_factor=2,  # Exponential backoff
#             status_forcelist=[408, 429, 500, 502, 503, 504, 520, 522, 524],
#             allowed_methods=["POST"],
#             raise_on_status=False
#         )
# 
#         # Connection pooling optimization
#         adapter = HTTPAdapter(
#             max_retries=retry_strategy,
#             pool_connections=20,
#             pool_maxsize=50,
#             pool_block=True
#         )
# 
#         session.mount("https://", adapter)
#         session.mount("http://", adapter)
# 
#         # Enhanced headers
#         session.headers.update({
#             'Content-Type': 'application/json; charset=utf-8',
#             'Accept': 'application/json',
#             'User-Agent': f'EFRIS-Client/{self.config["version"]}',
#             'Accept-Encoding': 'gzip, deflate',
#             'Connection': 'keep-alive'
#         })
# 
#         return session
# 
#     async def make_request_async(self, data: Dict[str, Any]) -> requests.Response:
#         """Async version of make_request for concurrent operations"""
#         return self.make_request(data)
# 
#     def make_request(self, data: Dict[str, Any]) -> requests.Response:
#         """Enhanced HTTP request with comprehensive monitoring"""
#         start_time = timezone.now()
#         request_id = str(uuid.uuid4())[:8]
# 
#         logger.info(
#             "EFRIS HTTP request starting",
#             request_id=request_id,
#             url=self.config['api_url'],
#             timeout=self.config['timeout']
#         )
# 
#         try:
#             # Pre-request validation
#             if not data:
#                 raise ValueError("Request data cannot be empty")
# 
#             response = self.session.post(
#                 self.config['api_url'],
#                 json=data,
#                 timeout=self.config['timeout']
#             )
# 
#             duration = (timezone.now() - start_time).total_seconds() * 1000
#             self._update_metrics(duration, response.status_code >= 400)
# 
#             logger.info(
#                 "EFRIS HTTP request completed",
#                 request_id=request_id,
#                 status_code=response.status_code,
#                 duration_ms=int(duration),
#                 content_length=len(response.content) if response.content else 0
#             )
# 
#             return response
# 
#         except requests.Timeout as e:
#             duration = (timezone.now() - start_time).total_seconds() * 1000
#             self._update_metrics(duration, True)
# 
#             logger.error(
#                 "EFRIS HTTP request timeout",
#                 request_id=request_id,
#                 duration_ms=int(duration),
#                 timeout=self.config['timeout']
#             )
#             raise EFRISNetworkError(
#                 f"Request timeout after {self.config['timeout']}s",
#                 error_code="TIMEOUT"
#             )
# 
#         except requests.ConnectionError as e:
#             duration = (timezone.now() - start_time).total_seconds() * 1000
#             self._update_metrics(duration, True)
# 
#             logger.error(
#                 "EFRIS HTTP connection error",
#                 request_id=request_id,
#                 error=str(e),
#                 duration_ms=int(duration)
#             )
#             raise EFRISNetworkError(
#                 f"Connection error: {e}",
#                 error_code="CONNECTION_ERROR",
#                 retryable=True
#             )
# 
#         except requests.RequestException as e:
#             duration = (timezone.now() - start_time).total_seconds() * 1000
#             self._update_metrics(duration, True)
# 
#             logger.error(
#                 "EFRIS HTTP request failed",
#                 request_id=request_id,
#                 error=str(e),
#                 duration_ms=int(duration)
#             )
#             raise EFRISNetworkError(f"HTTP request failed: {e}")
# 
#     def _update_metrics(self, duration: float, is_error: bool):
#         """Update client metrics"""
#         self._request_count += 1
#         self._total_duration += duration
# 
#         # Store metrics in cache for monitoring
#         cache_key = f"efris_http_metrics_{self.config.get('device_mac', 'unknown')}"
#         metrics = cache.get(cache_key, {
#             'request_count': 0,
#             'total_duration': 0,
#             'error_count': 0,
#             'last_updated': timezone.now().isoformat()
#         })
# 
#         metrics['request_count'] += 1
#         metrics['total_duration'] += duration
#         if is_error:
#             metrics['error_count'] += 1
#         metrics['last_updated'] = timezone.now().isoformat()
# 
#         cache.set(cache_key, metrics, 3600)  # Cache for 1 hour
# 
# 
#     def get_metrics(self) -> Dict[str, float]:
#         """Get client performance metrics"""
#         if self._request_count == 0:
#             return {"avg_duration_ms": 0, "request_count": 0}
# 
#         return {
#             "avg_duration_ms": self._total_duration / self._request_count,
#             "request_count": self._request_count,
#             "total_duration_ms": self._total_duration
#         }
# 
#     def close(self):
#         """Clean up resources"""
#         if self.session:
#             self.session.close()
#             logger.debug("HTTP client session closed")
# 
# 
# class DataValidator:
#     """Enhanced data validation with specific EFRIS rules"""
# 
#     @staticmethod
#     def validate_tin(tin: str) -> Tuple[bool, Optional[str]]:
#         """Enhanced TIN validation with specific error messages"""
#         if not tin:
#             return False, "TIN is required"
# 
#         if not isinstance(tin, str):
#             return False, "TIN must be a string"
# 
#         # Clean TIN
#         clean_tin = tin.replace(' ', '').replace('-', '')
# 
#         if len(clean_tin) != 10:
#             return False, f"TIN must be exactly 10 digits, got {len(clean_tin)}"
# 
#         if not clean_tin.isdigit():
#             return False, "TIN must contain only digits"
# 
#         return True, None
# 
#     @staticmethod
#     def validate_brn(brn: str) -> Tuple[bool, Optional[str]]:
#         """Enhanced BRN validation"""
#         if not brn:
#             return False, "BRN is required"
# 
#         if not isinstance(brn, str):
#             return False, "BRN must be a string"
# 
#         clean_brn = brn.replace(' ', '').replace('-', '')
# 
#         if not (5 <= len(clean_brn) <= 15):
#             return False, f"BRN must be between 5-15 characters, got {len(clean_brn)}"
# 
#         if not clean_brn.isalnum():
#             return False, "BRN must contain only alphanumeric characters"
# 
#         return True, None
# 
#     @staticmethod
#     def validate_amount(amount: Union[str, int, float, Decimal], field_name: str = "Amount") -> Tuple[
#         bool, Optional[str]]:
#         """Validate monetary amounts"""
#         try:
#             if isinstance(amount, str):
#                 amount = Decimal(amount)
#             elif isinstance(amount, (int, float)):
#                 amount = Decimal(str(amount))
#             elif not isinstance(amount, Decimal):
#                 return False, f"{field_name} must be a valid number"
# 
#             if amount < 0:
#                 return False, f"{field_name} cannot be negative"
# 
#             # Check precision (max 2 decimal places for currency)
#             if amount.as_tuple().exponent < -2:
#                 return False, f"{field_name} cannot have more than 2 decimal places"
# 
#             return True, None
# 
#         except (InvalidOperation, ValueError):
#             return False, f"{field_name} must be a valid decimal number"
# 
#     @staticmethod
#     def validate_invoice_data(data: Dict[str, Any]) -> List[str]:
#         """Comprehensive invoice data validation"""
#         errors = []
# 
#         # Structure validation
#         required_sections = [
#             'sellerDetails', 'basicInformation', 'buyerDetails',
#             'goodsDetails', 'taxDetails', 'summary'
#         ]
# 
#         for section in required_sections:
#             if section not in data:
#                 errors.append(f"Missing required section: {section}")
#                 continue
# 
#             if not isinstance(data[section], (dict, list)):
#                 errors.append(f"Section {section} must be a dict or list")
# 
#         # Seller details validation
#         if 'sellerDetails' in data and isinstance(data['sellerDetails'], dict):
#             seller = data['sellerDetails']
# 
#             is_valid, error = DataValidator.validate_tin(seller.get('tin', ''))
#             if not is_valid:
#                 errors.append(f"Seller TIN: {error}")
# 
#             if not seller.get('legalName'):
#                 errors.append("Seller legal name is required")
# 
#         # Amounts validation
#         if 'summary' in data and isinstance(data['summary'], dict):
#             summary = data['summary']
# 
#             amount_fields = ['netAmount', 'taxAmount', 'grossAmount']
#             amounts = {}
# 
#             for field in amount_fields:
#                 value = summary.get(field, 0)
#                 is_valid, error = DataValidator.validate_amount(value, field)
#                 if not is_valid:
#                     errors.append(f"Summary {error}")
#                 else:
#                     amounts[field] = Decimal(str(value))
# 
#             # Cross-validation of amounts
#             if len(amounts) == 3:
#                 expected_gross = amounts['netAmount'] + amounts['taxAmount']
#                 if abs(amounts['grossAmount'] - expected_gross) > Decimal('0.01'):
#                     errors.append("Amount calculation mismatch: netAmount + taxAmount ≠ grossAmount")
# 
#         # Goods details validation
#         if 'goodsDetails' in data:
#             goods = data['goodsDetails']
#             if not isinstance(goods, list):
#                 errors.append("goodsDetails must be a list")
#             elif len(goods) == 0:
#                 errors.append("At least one item is required in goodsDetails")
#             else:
#                 for i, item in enumerate(goods):
#                     if not isinstance(item, dict):
#                         errors.append(f"Item {i + 1} must be a dictionary")
#                         continue
# 
#                     # Validate required item fields
#                     required_item_fields = ['item', 'qty', 'unitPrice', 'total']
#                     for field in required_item_fields:
#                         if field not in item:
#                             errors.append(f"Item {i + 1}: Missing required field '{field}'")
# 
#                     # Validate item amounts
#                     for field in ['qty', 'unitPrice', 'total', 'tax']:
#                         if field in item:
#                             is_valid, error = DataValidator.validate_amount(
#                                 item[field], f"Item {i + 1} {field}"
#                             )
#                             if not is_valid:
#                                 errors.append(error)
# 
#         return errors
# 
# 
# class EFRISDataTransformer:
#     """Transform invoice data into EFRIS T109 format"""
# 
#     def __init__(self, company):
#         self.company = company
#         # Handle missing efris_config gracefully
#         efris_config = getattr(company, 'efris_config', None)
#         if efris_config:
#             self.device_no = getattr(efris_config, 'device_number', None) or '1026925503_01'
#         else:
#             self.device_no = '1026925503_01'
#         self.tin = getattr(company, 'tin', '')
# 
#     def get_numeric_tax_rate(self, tax_rate_value):
#         """Convert EFRIS tax rate codes to numeric values"""
#         if isinstance(tax_rate_value, str):
#             tax_rate_mapping = {
#                 'A': 18.0,  # Standard VAT
#                 'B': 0.0,   # Zero rate
#                 'C': 0.0,   # Exempt
#                 'D': 18.0,  # Deemed
#                 'E': 18.0,  # Standard
#             }
#             return tax_rate_mapping.get(tax_rate_value.upper(), 18.0)
#         try:
#             return float(tax_rate_value or 18)
#         except (ValueError, TypeError):
#             return 18.0
# 
#     def build_invoice_data(self, invoice) -> Dict[str, Any]:
#         """Build complete T109 invoice data structure"""
#         try:
#             invoice_data = {
#                 "sellerDetails": self._build_seller_details(),
#                 "basicInformation": self._build_basic_info(invoice),
#                 "buyerDetails": self._build_buyer_details(invoice),
#                 "goodsDetails": self._build_goods_details(invoice),
#                 "taxDetails": self._build_tax_details(invoice),
#                 "summary": self._build_summary(invoice)
#             }
# 
#             logger.info(f"Built invoice data for {getattr(invoice, 'number', 'unknown')}")
#             return invoice_data
# 
#         except Exception as e:
#             logger.error(f"Invoice data building failed: {e}")
#             raise Exception(f"Failed to build invoice data: {e}")
# 
#     def _build_seller_details(self) -> Dict[str, Any]:
#         """Build seller details from company information"""
#         return {
#             "tin": self.company.tin,
#             "ninBrn": getattr(self.company, 'brn', '') or getattr(self.company, 'nin', '') or "",
#             "legalName": getattr(self.company, 'efris_taxpayer_name', '') or self.company.name,
#             "businessName": (getattr(self.company, 'efris_business_name', '') or
#                            getattr(self.company, 'trading_name', '') or self.company.name),
#             "address": (getattr(self.company, 'efris_business_address', '') or
#                       getattr(self.company, 'physical_address', '') or ""),
#             "mobilePhone": (getattr(self.company, 'efris_phone_number', '') or
#                           getattr(self.company, 'phone', '') or ""),
#             "emailAddress": (getattr(self.company, 'efris_email_address', '') or
#                            getattr(self.company, 'email', '') or ""),
#             "placeOfBusiness": (getattr(self.company, 'efris_business_address', '') or
#                               getattr(self.company, 'physical_address', '') or ""),
#             "referenceNo": "+256789000826"
#         }
# 
#     def _build_basic_info(self, invoice) -> Dict[str, Any]:
#         """Build basic invoice information"""
#         return {
#             "deviceNo": self.device_no,
#             "invoiceNo": getattr(invoice, 'number', '') or "",
#             "issuedDate": invoice.issue_date.strftime('%Y-%m-%d %H:%M:%S'),
#             "operator": getattr(invoice, 'operator_name', '') or 'System',
#             "currency": getattr(invoice, 'currency_code', '') or 'UGX',
#             "invoiceType": "1",  # Normal invoice
#             "invoiceKind": "1",  # Sales invoice
#             "dataSource": "103",  # Web service
#             "invoiceIndustryCode": "101"  # General business
#         }
# 
#     def _build_buyer_details(self, invoice) -> Dict[str, Any]:
#         """Build buyer details with proper defaults"""
#         customer = getattr(invoice, 'customer', None)
#         if not customer:
#             return {
#                 "buyerType": "1",  # B2C
#                 "buyerLegalName": "Walk-in Customer",
#                 "buyerTin": "",
#                 "buyerNinBrn": "",
#                 "buyerAddress": "",
#                 "buyerEmail": "",
#                 "buyerMobilePhone": ""
#             }
# 
#         # Determine buyer type
#         buyer_type = "1"  # Default B2C
#         if getattr(customer, 'tin', None):
#             buyer_type = "0"  # B2B if has TIN
# 
#         return {
#             "buyerTin": getattr(customer, 'tin', '') or "",
#             "buyerNinBrn": (getattr(customer, 'nin', '') or
#                            getattr(customer, 'brn', '') or ""),
#             "buyerLegalName": getattr(customer, 'name', '') or "Unknown Customer",
#             "buyerType": buyer_type,
#             "buyerEmail": getattr(customer, 'email', '') or "",
#             "buyerMobilePhone": getattr(customer, 'phone', '') or "",
#             "buyerAddress": getattr(customer, 'address', '') or ""
#         }
# 
#     def _build_goods_details(self, invoice) -> List[Dict[str, Any]]:
#         """Build goods details with proper EFRIS itemCode"""
#         goods_details = []
#         items = self._get_invoice_items(invoice)
# 
#         if not items:
#             raise Exception("Invoice must have at least one item")
# 
#         for idx, item in enumerate(items, 1):
#             try:
#                 product = getattr(item, 'product', None)
# 
#                 if product:
#                     # Get commodity category
#                     commodity_category_id = (
#                             getattr(product, 'efris_commodity_category_id', None) or
#                             (getattr(product.category, 'efris_commodity_category_id', None)
#                              if product.category else None) or
#                             '1010101000'
#                     )
# 
#                     commodity_category_name = (
#                             getattr(product, 'efris_commodity_category_name', None) or
#                             (getattr(product.category, 'efris_commodity_category_name', None)
#                              if product.category else None) or
#                             (getattr(product.category, 'name', None)
#                              if product.category else None) or
#                             'General Goods'
#                     )
# 
#                     # Get amounts
#                     quantity = float(getattr(item, 'quantity', 1))
#                     unit_price = float(getattr(item, 'unit_price', 0) or getattr(item, 'price', 0))
#                     line_total = quantity * unit_price
# 
#                     # Get tax rate
#                     tax_rate_raw = getattr(item, 'tax_rate', 'A')
#                     tax_rate = self.get_numeric_tax_rate(tax_rate_raw)
#                     tax_amount = line_total * (tax_rate / 100)
# 
#                     # CRITICAL FIX: Use product's efris_item_code property
#                     item_code = product.efris_item_code if hasattr(product,
#                                                                    'efris_item_code') else commodity_category_id
# 
#                     goods_detail = {
#                         "item": product.name[:200],  # Ensure name length limit
#                         "itemCode": '101',
#                         "qty": str(quantity),
#                         "unitOfMeasure": getattr(product, 'efris_unit_of_measure_code', 'U'),
#                         "unitPrice": f"{unit_price:.2f}",
#                         "total": f"{line_total:.2f}",
#                         "taxRate": f"{tax_rate / 100:.2f}",
#                         "tax": f"{tax_amount:.2f}",
#                         "orderNumber": str(idx),
#                         "discountFlag": "2",
#                         "discountTotal": "0",
#                         "deemedFlag": "2",
#                         "exciseFlag": "2",
#                         "goodsCategoryId":'A',
#                         "goodsCategoryName": 'test',
#                     }
# 
#                     logger.debug(
#                         f"Item {idx}: {product.name}, "
#                         f"itemCode={item_code}, "
#                         f"goodsCategoryId={commodity_category_id}"
#                     )
# 
#                 else:
#                     # Fallback for items without product
#                     goods_detail = {
#                         "item": f"Item {idx}",
#                         "itemCode": '101',
#                         "qty": str(float(getattr(item, 'quantity', 1))),
#                         "unitOfMeasure": "U",
#                         "unitPrice": f"{float(getattr(item, 'unit_price', 0)):.2f}",
#                         "total": f"{float(getattr(item, 'quantity', 1)) * float(getattr(item, 'unit_price', 0)):.2f}",
#                         "taxRate": "0.18",
#                         "tax": f"{float(getattr(item, 'quantity', 1)) * float(getattr(item, 'unit_price', 0)) * 0.18:.2f}",
#                         "orderNumber": str(idx),
#                         "discountFlag": "2",
#                         "discountTotal": "0",
#                         "deemedFlag": "2",
#                         "exciseFlag": "2",
#                         "goodsCategoryId": '101',
#                         "goodsCategoryName": 'test',
#                     }
# 
#                 goods_details.append(goods_detail)
# 
#             except Exception as e:
#                 logger.error(f"Failed to process item {idx}: {e}", exc_info=True)
#                 raise Exception(f"Item {idx} processing failed: {e}")
# 
#         return goods_details
# 
# 
# 
#     def _build_tax_details(self, invoice) -> List[Dict[str, Any]]:
#         """Build tax details summary"""
#         subtotal = float(getattr(invoice, 'subtotal', 0))
#         tax_amount = float(getattr(invoice, 'tax_amount', 0))
#         total_amount = float(getattr(invoice, 'total_amount', 0))
# 
#         tax_details = []
#         if tax_amount > 0:
#             tax_details.append({
#                 "taxCategoryCode": "01",
#                 "netAmount": f"{subtotal:.2f}",
#                 "taxRate": "0.18",
#                 "taxAmount": f"{tax_amount:.2f}",
#                 "grossAmount": f"{total_amount:.2f}",
#                 "taxRateName": "Standard Rate (18%)"
#             })
#         else:
#             tax_details.append({
#                 "taxCategoryCode": "02",
#                 "netAmount": f"{subtotal:.2f}",
#                 "taxRate": "0.00",
#                 "taxAmount": "0.00",
#                 "grossAmount": f"{total_amount:.2f}",
#                 "taxRateName": "Zero Rate (0%)"
#             })
# 
#         return tax_details
# 
#     def _build_summary(self, invoice) -> Dict[str, Any]:
#         """Build invoice summary"""
#         subtotal = float(getattr(invoice, 'subtotal', 0))
#         tax_amount = float(getattr(invoice, 'tax_amount', 0))
#         total_amount = float(getattr(invoice, 'total_amount', 0))
# 
#         items = self._get_invoice_items(invoice)
#         item_count = len(items) if items else 1
# 
#         return {
#             "netAmount": f"{subtotal:.2f}",
#             "taxAmount": f"{tax_amount:.2f}",
#             "grossAmount": f"{total_amount:.2f}",
#             "itemCount": str(item_count),
#             "modeCode": "1",
#             "remarks": getattr(invoice, 'notes', '') or "Invoice via EFRIS integration"
#         }
# 
#     def _get_invoice_items(self, invoice) -> List:
#         """Get invoice items with multiple attribute attempts"""
#         # Try different item attributes
#         for attr in ['items', 'line_items', 'invoice_items', 'sale_items']:
#             if hasattr(invoice, attr):
#                 items = getattr(invoice, attr)
#                 if hasattr(items, 'all'):
#                     return list(items.all())
#                 elif hasattr(items, '__iter__'):
#                     return list(items)
# 
#         # Try from related sale
#         if hasattr(invoice, 'sale') and invoice.sale:
#             return self._get_invoice_items(invoice.sale)
# 
#         return []
# 
# 
# class EnhancedEFRISAPIClient:
#     """Clean EFRIS API Client with proper authentication flow"""
# 
#     def __init__(self, company):
#         self.company = company
#         self.efris_config = company.efris_config
#         self.security_manager = SecurityManager(
#             self.efris_config.device_number or '1026925503_01',
#             company.tin
#         )
#         self.data_transformer = EFRISDataTransformer(company)
# 
#         # Session management
#         self._is_authenticated = False
#         self._last_login = None
#         self._device_initialized = self._check_device_initialization()
# 
#     def __enter__(self):
#         return self
# 
#     def __exit__(self, exc_type, exc_val, exc_tb):
#         pass
# 
#     def _check_device_initialization(self) -> bool:
#         """Check if device has been initialized"""
#         cache_key = f"efris_device_init_{self.company.pk}_{self.company.tin}"
#         is_initialized = cache.get(cache_key, False)
#         logger.debug(f"Device init check: {is_initialized}")
#         return bool(is_initialized)
# 
#     def _mark_device_initialized(self):
#         """Mark device as initialized"""
#         cache_key = f"efris_device_init_{self.company.pk}_{self.company.tin}"
#         cache.set(cache_key, True, timeout=86400)
#         self._device_initialized = True
#         logger.info("Device marked as initialized")
# 
#     def _load_private_key(self) -> rsa.RSAPrivateKey:
#         """Load private key from EFRIS configuration"""
#         try:
#             return serialization.load_pem_private_key(
#                 self.efris_config.private_key.encode('utf-8'),
#                 password=(self.efris_config.key_password.encode('utf-8')
#                          if self.efris_config.key_password else None)
#             )
#         except Exception as e:
#             raise Exception(f"Failed to load private key: {e}")
# 
#     def validate_configuration(self) -> Tuple[bool, List[str]]:
#         """Validate EFRIS configuration before API operations"""
#         errors = []
# 
#         if not hasattr(self.company, 'efris_config'):
#             errors.append("EFRIS configuration not found for company")
#             return False, errors
# 
#         config = self.efris_config
# 
#         # Check required fields
#         if not config.private_key:
#             errors.append("Private key is missing")
#         if not config.public_certificate:
#             errors.append("Public certificate/key is missing")
#         if not config.is_active:
#             errors.append("EFRIS configuration is not active")
#         if config.mode == 'online' and not config.device_number:
#             errors.append("Device number is required for online mode")
# 
#         # Validate keys can be loaded
#         try:
#             if config.private_key:
#                 self._load_private_key()
#         except Exception as e:
#             errors.append(f"Private key validation failed: {str(e)}")
# 
#         return len(errors) == 0, errors
# 
#     def _make_http_request(self, data: Dict) -> requests.Response:
#         """Make HTTP request to EFRIS API"""
#         api_url = getattr(settings, 'EFRIS_API_URL',
#                          'https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation')
# 
#         try:
#             response = requests.post(
#                 api_url,
#                 json=data,
#                 headers={'Content-Type': 'application/json'},
#                 timeout=30
#             )
#             logger.debug(f"HTTP {response.status_code}: {len(response.content)} bytes")
#             return response
#         except Exception as e:
#             logger.error(f"HTTP request failed: {e}")
#             raise Exception(f"HTTP request failed: {e}")
# 
#     def ensure_authenticated(self) -> Dict:
#         """Complete authentication flow"""
#         try:
#             # Check if already authenticated
#             if (self._is_authenticated and self._last_login and
#                 (timezone.now() - self._last_login) < timedelta(minutes=30) and
#                 self.security_manager.is_aes_key_valid()):
#                 logger.debug("Already authenticated")
#                 return {"success": True, "message": "Already authenticated"}
# 
#             logger.info("Starting authentication flow")
# 
#             # Step 1: Device initialization (if needed)
#             if not self._device_initialized:
#                 logger.info("Device not initialized, running T102")
#                 init_result = self._client_initialization()
#                 if not init_result.get("success"):
#                     return {"success": False, "error": f"T102 failed: {init_result.get('error')}"}
#                 self._mark_device_initialized()
# 
#             # Step 2: Get AES key (T104)
#             logger.info("Getting symmetric key (T104)")
#             key_result = self._get_symmetric_key()
#             if not key_result.get("success"):
#                 return {"success": False, "error": f"T104 failed: {key_result.get('error')}"}
# 
#             # Step 3: Login (T103)
#             logger.info("Performing login (T103)")
#             login_result = self._login()
#             if not login_result.get("success"):
#                 return {"success": False, "error": f"T103 failed: {login_result.get('error')}"}
# 
#             # Mark as authenticated
#             self._is_authenticated = True
#             self._last_login = timezone.now()
# 
#             logger.info("Authentication completed successfully")
#             return {"success": True, "message": "Authentication successful"}
# 
#         except Exception as e:
#             logger.error(f"Authentication failed: {e}")
#             return {"success": False, "error": str(e)}
# 
#     def _client_initialization(self) -> Dict:
#         """T102 - Client initialization"""
#         try:
#             request_data = {
#                 "data": {
#                     "content": "",
#                     "signature": "",
#                     "dataDescription": {"codeType": "0", "encryptCode": "0", "zipCode": "0"}
#                 },
#                 "globalInfo": self.security_manager.create_global_info("T102"),
#                 "returnStateInfo": {"returnCode": "", "returnMessage": ""}
#             }
# 
#             response = self._make_http_request(request_data)
#             if response.status_code != 200:
#                 return {"success": False, "error": f"HTTP {response.status_code}"}
# 
#             response_data = response.json()
#             return_info = response_data.get('returnStateInfo', {})
#             return_code = return_info.get('returnCode', '99')
# 
#             if return_code == '00':
#                 logger.info("T102 client initialization successful")
#                 return {"success": True, "data": response_data}
#             else:
#                 error_message = return_info.get('returnMessage', 'T102 failed')
#                 logger.error(f"T102 failed: {error_message}")
#                 return {"success": False, "error": error_message}
# 
#         except Exception as e:
#             logger.error(f"T102 initialization failed: {e}")
#             return {"success": False, "error": str(e)}
# 
#     def _get_symmetric_key(self) -> Dict:
#         """T104 - Get symmetric key with proper caching"""
#         try:
#             # Check if we already have valid AES key
#             if self.security_manager.is_aes_key_valid():
#                 logger.debug("Using cached AES key")
#                 return {"success": True, "message": "Using cached AES key"}
# 
#             request_data = {
#                 "data": {
#                     "content": "",
#                     "signature": "",
#                     "dataDescription": {"codeType": "0", "encryptCode": "0", "zipCode": "0"}
#                 },
#                 "globalInfo": self.security_manager.create_global_info("T104"),
#                 "returnStateInfo": {"returnCode": "", "returnMessage": ""}
#             }
# 
#             response = self._make_http_request(request_data)
#             if response.status_code != 200:
#                 return {"success": False, "error": f"HTTP {response.status_code}"}
# 
#             response_data = response.json()
#             return_info = response_data.get('returnStateInfo', {})
#             return_code = return_info.get('returnCode', '99')
# 
#             if return_code == '00':
#                 data_section = response_data.get('data', {})
#                 private_key = self._load_private_key()
#                 key_result = self.security_manager.process_t104_response(data_section, private_key)
# 
#                 if key_result.get("success"):
#                     logger.info("T104 AES key obtained and cached")
#                     return {"success": True, "aes_key": key_result["aes_key"]}
#                 else:
#                     error = key_result.get("error", "Failed to process AES key")
#                     logger.error(f"T104 key processing failed: {error}")
#                     return {"success": False, "error": error}
#             else:
#                 error_message = return_info.get('returnMessage', 'T104 failed')
#                 logger.error(f"T104 failed: {error_message}")
#                 return {"success": False, "error": error_message}
# 
#         except Exception as e:
#             logger.error(f"T104 failed: {e}")
#             return {"success": False, "error": str(e)}
# 
#     def _login(self) -> Dict:
#         """T103 - Login"""
#         try:
#             request_data = {
#                 "data": {
#                     "content": "",
#                     "signature": "",
#                     "dataDescription": {"codeType": "0", "encryptCode": "0", "zipCode": "0"}
#                 },
#                 "globalInfo": self.security_manager.create_global_info("T103"),
#                 "returnStateInfo": {"returnCode": "", "returnMessage": ""}
#             }
# 
#             response = self._make_http_request(request_data)
#             if response.status_code != 200:
#                 return {"success": False, "error": f"HTTP {response.status_code}"}
# 
#             response_data = response.json()
#             return_info = response_data.get('returnStateInfo', {})
#             return_code = return_info.get('returnCode', '99')
# 
#             if return_code == '00':
#                 logger.info("T103 login successful")
#                 return {"success": True, "data": response_data}
#             else:
#                 error_message = return_info.get('returnMessage', 'T103 failed')
#                 logger.error(f"T103 failed: {error_message}")
#                 return {"success": False, "error": error_message}
# 
#         except Exception as e:
#             logger.error(f"T103 failed: {e}")
#             return {"success": False, "error": str(e)}
# 
#     def register_product_with_efris(self, product) -> Dict[str, Any]:
#         try:
#             # Ensure authentication
#             auth_result = self.ensure_authenticated()
#             if not auth_result.get("success"):
#                 return {
#                     "success": False,
#                     "error": f"Authentication failed: {auth_result.get('error')}"
#                 }
#
#             # Get commodity category information
#             commodity_category_id = (
#                 getattr(product, 'efris_commodity_category_id', None) or
#                 (getattr(product.category, 'efris_commodity_category_id', None)
#                  if hasattr(product, 'category') and product.category else None) or
#                 '10111301'  # Default category
#             )
#
#             # Get or generate goods code
#             goods_code = getattr(product, 'efris_item_code', None)
#             if not goods_code:
#                 goods_code = f"{getattr(product, 'sku', 'PROD')}_{product.id}"
#
#             # Get product pricing and stock info
#             selling_price = float(getattr(product, 'selling_price', 0) or 0)
#             stock_qty = int(getattr(product, 'quantity_in_stock', 0) or 0)
#             min_stock = int(getattr(product, 'min_stock_level', 10) or 10)
#
#             # Determine if product has excise tax
#             has_excise = self._product_has_excise_tax(product)
#
#             # Build goods data matching T130 specification exactly
#             goods_data = {
#                 "operationType": "101",  # 101=Add, 102=Modify
#                 "goodsName": str(product.name[:200] if product.name else "Unnamed Product"),
#                 "goodsCode": str(goods_code),
#
#                 # Main unit of measure (REQUIRED)
#                 "measureUnit": str(
#                     getattr(product, 'efris_unit_of_measure_code', None) or
#                     self._get_default_unit_code()
#                 ),
#
#                 "unitPrice": f"{selling_price:.2f}",
#                 "currency": "101",  # 101=UGX (from T115 currencyType)
#                 "commodityCategoryId": str(commodity_category_id),
#
#                 # Excise tax flag (REQUIRED)
#                 "haveExciseTax": "101" if has_excise else "102",  # 101=Yes, 102=No
#
#                 # Description (optional, max 1024 chars)
#                 "description": str(
#                     (getattr(product, 'description', None) or product.name or "")[:1024]
#                 ),
#
#                 # Stock pre-warning level (REQUIRED)
#                 "stockPrewarning": str(min_stock),
#
#                 # Piece unit fields (conditional based on havePieceUnit)
#                 "havePieceUnit": "102",  # 102=No (default, unless excise has piece unit)
#                 "pieceMeasureUnit": "",  # Empty when havePieceUnit=102
#                 "pieceUnitPrice": "",    # Empty when havePieceUnit=102
#                 "packageScaledValue": "",  # Empty when havePieceUnit=102
#                 "pieceScaledValue": "",    # Empty when havePieceUnit=102
#
#                 # Excise duty code (conditional)
#                 "exciseDutyCode": "",  # Empty when haveExciseTax=102
#
#                 # Other unit flag (conditional)
#                 "haveOtherUnit": "102",  # 102=No (must be 102 if havePieceUnit=102)
#
#                 # Goods type
#                 "goodsTypeCode": "101",  # 101=Goods, 102=Fuel
#             }
#
#             # Add excise tax details if applicable
#             if has_excise:
#                 excise_info = self._build_excise_tax_info(product)
#                 goods_data.update(excise_info)
#
#             # Add customs UoM if available
#             customs_info = self._build_customs_info(product)
#             if customs_info:
#                 goods_data["commodityGoodsExtendEntity"] = customs_info
#
#             # Add other units if configured
#             other_units = self._build_other_units(product)
#             if other_units:
#                 goods_data["goodsOtherUnits"] = other_units
#                 goods_data["haveOtherUnit"] = "101"  # Must update if other units exist
#
#             # CRITICAL: T130 expects array directly in content, not nested
#             product_data = [goods_data]
#
#             # Validate the structure
#             validation_errors = self._validate_t130_data(goods_data)
#             if validation_errors:
#                 return {
#                     "success": False,
#                     "error": f"Validation failed: {'; '.join(validation_errors)}"
#                 }
#
#             # Create signed and encrypted request
#             private_key = self._load_private_key()
#             request_data = self.security_manager.create_signed_encrypted_request(
#                 "T130", product_data, private_key
#             )
#
#             # Send request
#             logger.info(f"Registering product {goods_code} with EFRIS (T130)")
#             response = self._make_http_request(request_data)
#
#             if response.status_code != 200:
#                 return {
#                     "success": False,
#                     "error": f"HTTP {response.status_code}: {response.text[:200]}"
#                 }
#
#             response_data = response.json()
#             return_info = response_data.get('returnStateInfo', {})
#             return_code = return_info.get('returnCode', '99')
#
#             if return_code == '00':
#                 # Process successful response
#                 self._process_t130_success_response(product, response_data)
#
#                 return {
#                     "success": True,
#                     "message": "Product registered with EFRIS",
#                     "item_code": goods_code,
#                     "data": response_data
#                 }
#             else:
#                 error_message = return_info.get('returnMessage', 'T130 failed')
#                 logger.error(f"T130 failed: {return_code} - {error_message}")
#
#                 return {
#                     "success": False,
#                     "error": error_message,
#                     "error_code": return_code,
#                     "item_code": goods_code
#                 }
#
#         except Exception as e:
#             logger.error(f"Product registration failed: {e}", exc_info=True)
#             return {"success": False, "error": str(e)}

    # def _product_has_excise_tax(self, product) -> bool:
    #     """Check if product is subject to excise tax"""
    #     # Check if excise duty rate is set
    #     excise_rate = getattr(product, 'excise_duty_rate', None)
    #     if excise_rate and float(excise_rate) > 0:
    #         return True
    #
    #     # Check if excise duty code is set
    #     excise_code = getattr(product, 'efris_excise_duty_code', None)
    #     if excise_code and excise_code.strip():
    #         return True
    #
    #     return False
    #
    # def _build_excise_tax_info(self, product) -> Dict[str, str]:
    #     """Build excise tax information for products with excise duty"""
    #     excise_info = {}
    #
    #     # Excise duty code (required when haveExciseTax=101)
    #     excise_code = getattr(product, 'efris_excise_duty_code', '')
    #     if excise_code:
    #         excise_info["exciseDutyCode"] = str(excise_code)[:20]
    #
    #     # If excise has piece unit measurement
    #     has_piece_unit = getattr(product, 'efris_has_piece_unit', False)
    #     if has_piece_unit:
    #         excise_info["havePieceUnit"] = "101"
    #
    #         piece_measure_unit = getattr(product, 'efris_piece_measure_unit', 'U')
    #         excise_info["pieceMeasureUnit"] = str(piece_measure_unit)
    #
    #         piece_price = float(getattr(product, 'efris_piece_unit_price', 0) or 0)
    #         excise_info["pieceUnitPrice"] = f"{piece_price:.2f}"
    #
    #         # Scaling values (default to 1)
    #         excise_info["packageScaledValue"] = str(
    #             getattr(product, 'efris_package_scaled_value', 1)
    #         )
    #         excise_info["pieceScaledValue"] = str(
    #             getattr(product, 'efris_piece_scaled_value', 1)
    #         )
    #
    #     return excise_info
    #
    # def _build_customs_info(self, product) -> Optional[Dict[str, str]]:
    #     """Build customs unit of measure information if available"""
    #     customs_unit = getattr(product, 'efris_customs_measure_unit', None)
    #
    #     if not customs_unit:
    #         return None
    #
    #     return {
    #         "customsMeasureUnit": str(customs_unit),
    #         "customsUnitPrice": f"{float(getattr(product, 'efris_customs_unit_price', 0)):.2f}",
    #         "packageScaledValueCustoms": str(
    #             getattr(product, 'efris_package_scaled_customs', 1)
    #         ),
    #         "customsScaledValue": f"{float(getattr(product, 'efris_customs_scaled_value', 1)):.2f}"
    #     }
    #
    # def _build_other_units(self, product) -> Optional[List[Dict[str, str]]]:
    #     """Build other units of measure if configured"""
    #     # Check if product has other units configured
    #     if not hasattr(product, 'efris_other_units') or not product.efris_other_units:
    #         return None
    #
    #     other_units = []
    #
    #     try:
    #         # Assuming efris_other_units is a JSON field or related objects
    #         units_data = product.efris_other_units
    #         if isinstance(units_data, str):
    #             import json
    #             units_data = json.loads(units_data)
    #
    #         for unit_data in units_data:
    #             other_unit = {
    #                 "otherUnit": str(unit_data.get('unit_code', 'U')),
    #                 "otherPrice": f"{float(unit_data.get('price', 0)):.2f}",
    #                 "otherScaled": f"{float(unit_data.get('scaled_value', 1)):.2f}",
    #                 "packageScaled": f"{float(unit_data.get('package_scaled', 1)):.2f}"
    #             }
    #             other_units.append(other_unit)
    #     except Exception as e:
    #         logger.warning(f"Failed to build other units: {e}")
    #         return None
    #
    #     return other_units if other_units else None
    #
    # def _get_default_unit_code(self) -> str:
    #     """Get default unit of measure code"""
    #     return "101"  # Default from T115 rateUnit - adjust based on your business
    #
    # def _validate_t130_data(self, goods_data: Dict) -> List[str]:
    #     """Validate T130 goods data against EFRIS rules"""
    #     errors = []
    #
    #     # Required fields validation
    #     required_fields = [
    #         'goodsName', 'goodsCode', 'measureUnit', 'unitPrice',
    #         'currency', 'commodityCategoryId', 'haveExciseTax',
    #         'stockPrewarning', 'havePieceUnit'
    #     ]
    #
    #     for field in required_fields:
    #         if field not in goods_data or not str(goods_data[field]).strip():
    #             errors.append(f"Missing required field: {field}")
    #
    #     # Conditional validation for piece unit
    #     have_piece_unit = goods_data.get('havePieceUnit')
    #     if have_piece_unit == '101':
    #         # Piece unit fields required
    #         if not goods_data.get('pieceMeasureUnit'):
    #             errors.append("pieceMeasureUnit required when havePieceUnit=101")
    #         if not goods_data.get('pieceUnitPrice'):
    #             errors.append("pieceUnitPrice required when havePieceUnit=101")
    #         if not goods_data.get('packageScaledValue'):
    #             errors.append("packageScaledValue required when havePieceUnit=101")
    #         if not goods_data.get('pieceScaledValue'):
    #             errors.append("pieceScaledValue required when havePieceUnit=101")
    #     elif have_piece_unit == '102':
    #         # Piece unit fields must be empty
    #         if goods_data.get('pieceMeasureUnit'):
    #             errors.append("pieceMeasureUnit must be empty when havePieceUnit=102")
    #
    #     # Conditional validation for excise tax
    #     have_excise = goods_data.get('haveExciseTax')
    #     if have_excise == '102' and goods_data.get('exciseDutyCode'):
    #         errors.append("exciseDutyCode must be empty when haveExciseTax=102")
    #
    #     # Conditional validation for other units
    #     have_other_unit = goods_data.get('haveOtherUnit')
    #     if have_piece_unit == '102' and have_other_unit == '101':
    #         errors.append("haveOtherUnit must be 102 when havePieceUnit=102")
    #
    #     # Length validations
    #     if len(goods_data.get('goodsName', '')) > 200:
    #         errors.append("goodsName cannot exceed 200 characters")
    #
    #     if len(goods_data.get('goodsCode', '')) > 50:
    #         errors.append("goodsCode cannot exceed 50 characters")
    #
    #     if len(goods_data.get('description', '')) > 1024:
    #         errors.append("description cannot exceed 1024 characters")
    #
    #     return errors
    #
    # def _process_t130_success_response(self, product, response_data: Dict):
    #     """Process successful T130 response and update product"""
    #     try:
    #         data_section = response_data.get('data', {})
    #         if data_section.get('content'):
    #             decrypted_content = self._decrypt_response_content(data_section)
    #
    #             if decrypted_content and isinstance(decrypted_content, list):
    #                 # T130 returns array of goods
    #                 for goods_info in decrypted_content:
    #                     return_code = goods_info.get('returnCode')
    #
    #                     if return_code == '601' or return_code == '00':
    #                         # Success - update product
    #                         if hasattr(product, 'efris_is_uploaded'):
    #                             product.efris_is_uploaded = True
    #
    #                         if hasattr(product, 'efris_upload_date'):
    #                             product.efris_upload_date = timezone.now()
    #
    #                         # Store any returned commodity goods ID
    #                         goods_id = goods_info.get('commodityGoodsId')
    #                         if goods_id and hasattr(product, 'efris_goods_id'):
    #                             product.efris_goods_id = goods_id
    #
    #                         product.save()
    #                         logger.info(f"Product {product.id} marked as uploaded to EFRIS")
    #                         break
    #
    #     except Exception as e:
    #         logger.warning(f"Failed to process T130 response: {e}")
    #

# 
#     def upload_invoice(self, invoice, user=None) -> Dict[str, Any]:
#         """T109 - Upload invoice to EFRIS with product pre-registration check"""
#         try:
#             # Ensure authentication
#             auth_result = self.ensure_authenticated()
#             if not auth_result.get("success"):
#                 return {
#                     "success": False,
#                     "error": f"Authentication failed: {auth_result.get('error')}",
#                     "error_code": None,
#                     "response_data": None
#                 }
# 
#             # PRE-CHECK: Ensure all products are registered with EFRIS
#             items = self.data_transformer._get_invoice_items(invoice)
#             unregistered_products = []
# 
#             for item in items:
#                 product = getattr(item, 'product', None)
#                 if product and not product.efris_is_uploaded:
#                     unregistered_products.append(product)
# 
#             # Register any unregistered products
#             if unregistered_products:
#                 logger.info(f"Registering {len(unregistered_products)} products with EFRIS first")
#                 for product in unregistered_products:
#                     reg_result = self.register_product_with_efris(product)
#                     if not reg_result.get("success"):
#                         logger.warning(
#                             f"Failed to register product {product.sku}: "
#                             f"{reg_result.get('error')}"
#                         )
#                         # Continue anyway - some EFRIS implementations allow this
# 
#             # Build and upload invoice
#             logger.info(f"Building invoice data for {getattr(invoice, 'number', 'unknown')}")
#             invoice_data = self.data_transformer.build_invoice_data(invoice)
# 
#             private_key = self._load_private_key()
#             request_data = self.security_manager.create_signed_encrypted_request(
#                 "T109", invoice_data, private_key
#             )
# 
#             logger.info("Sending T109 invoice upload request")
#             response = self._make_http_request(request_data)
# 
#             # Log raw HTTP response for debugging
#             logger.debug(f"Raw HTTP response for invoice {invoice.id}: {response.status_code}, {response.text}")
# 
#             if response.status_code != 200:
#                 return {
#                     "success": False,
#                     "error": f"HTTP {response.status_code}",
#                     "error_code": str(response.status_code),
#                     "response_data": response.text
#                 }
# 
#             response_data = response.json()
#             return_info = response_data.get('returnStateInfo', {})
#             return_code = return_info.get('returnCode', '99')
# 
#             if return_code == '00':
#                 logger.info(f"T109 invoice upload successful for invoice {invoice.id}")
#                 try:
#                     self._process_successful_upload(invoice, response_data)
#                 except Exception as e:
#                     logger.warning(f"Failed to process upload response for invoice {invoice.id}: {e}")
# 
#                 return {
#                     "success": True,
#                     "data": response_data,
#                     "message": "Invoice uploaded successfully",
#                     "error_code": None
#                 }
#             else:
#                 error_message = return_info.get('returnMessage', 'T109 upload failed')
#                 logger.error(f"T109 failed for invoice {invoice.id}: {return_code} - {error_message}")
# 
#                 return {
#                     "success": False,
#                     "error": error_message,
#                     "error_code": return_code,
#                     "response_data": response_data
#                 }
# 
#         except Exception as e:
#             logger.error(f"T109 upload failed for invoice {invoice.id}: {str(e)}", exc_info=True)
#             return {
#                 "success": False,
#                 "error": str(e),
#                 "error_code": None,
#                 "response_data": None
#             }
# 
# 
#     def _decrypt_response_content(self, data_section: Dict) -> Optional[Dict]:
#         """Decrypt EFRIS response content if encrypted"""
#         try:
#             content = data_section.get('content', '')
#             if not content:
#                 return None
# 
#             data_description = data_section.get('dataDescription', {})
#             encrypt_code = data_description.get('encryptCode', '0')
# 
#             if encrypt_code == '0':
#                 decoded = base64.b64decode(content).decode('utf-8')
#                 return json.loads(decoded)
#             elif encrypt_code in ['1', '2']:
#                 aes_key = self.security_manager.get_current_aes_key()
#                 if aes_key:
#                     decrypted = self.security_manager.decrypt_with_aes(content, aes_key)
#                     return json.loads(decrypted)
# 
#             return None
#         except Exception as e:
#             logger.debug(f"Content decryption failed: {e}")
#             return None
# 
#     def _process_successful_upload(self, invoice, response_data: Dict):
#         """Process successful T109 response"""
#         try:
#             data_section = response_data.get('data', {})
#             if data_section.get('content'):
#                 decrypted_content = self._decrypt_response_content(data_section)
#                 if decrypted_content:
#                     basic_info = decrypted_content.get('basicInformation', {})
# 
#                     # Update invoice with EFRIS data
#                     updates_made = False
#                     if hasattr(invoice, 'fiscal_document_number') and basic_info.get('invoiceNo'):
#                         invoice.fiscal_document_number = basic_info['invoiceNo']
#                         updates_made = True
# 
#                     if hasattr(invoice, 'verification_code') and basic_info.get('antifakeCode'):
#                         invoice.verification_code = basic_info['antifakeCode']
#                         updates_made = True
# 
#                     if hasattr(invoice, 'is_fiscalized'):
#                         invoice.is_fiscalized = True
#                         invoice.fiscalization_time = timezone.now()
#                         updates_made = True
# 
#                     if updates_made:
#                         invoice.save()
#                         logger.info(f"Invoice updated with EFRIS data")
# 
#         except Exception as e:
#             logger.warning(f"Failed to process upload response: {e}")
# 
#     def get_server_time(self) -> Dict:
#         """T101 - Get server time"""
#         try:
#             request_data = {
#                 "data": {
#                     "content": "",
#                     "signature": "",
#                     "dataDescription": {"codeType": "0", "encryptCode": "0", "zipCode": "0"}
#                 },
#                 "globalInfo": self.security_manager.create_global_info("T101"),
#                 "returnStateInfo": {"returnCode": "", "returnMessage": ""}
#             }
# 
#             response = self._make_http_request(request_data)
#             if response.status_code != 200:
#                 return {"success": False, "error": f"HTTP {response.status_code}"}
# 
#             response_data = response.json()
#             return_info = response_data.get('returnStateInfo', {})
#             return_code = return_info.get('returnCode', '99')
# 
#             if return_code == '00':
#                 logger.info("T101 server time retrieved")
#                 return {"success": True, "data": response_data}
#             else:
#                 error_message = return_info.get('returnMessage', 'T101 failed')
#                 return {"success": False, "error": error_message}
# 
#         except Exception as e:
#             logger.error(f"T101 failed: {e}")
#             return {"success": False, "error": str(e)}
# 
# from django_tenants.utils import schema_context
# 
# def bulk_register_products_with_efris(company):
#     """
#     Register all active products with EFRIS in the company's tenant schema.
#     FIXED: Better error handling and progress tracking
#     """
#     from efris.services import EnhancedEFRISAPIClient
# 
#     results = {
#         'total': 0,
#         'successful': 0,
#         'failed': 0,
#         'errors': [],
#         'warnings': [],
#         'registered_products': []
#     }
# 
#     try:
#         # Switch to the company's tenant schema
#         with schema_context(company.schema_name):
#             from inventory.models import Product  # Import inside tenant context
# 
#             # Get products that need registration
#             products = Product.objects.filter(
#                 is_active=True,
#                 efris_is_uploaded=False
#             ).select_related('category')  # Optimize queries
# 
#             results['total'] = products.count()
# 
#             if results['total'] == 0:
#                 results['warnings'].append('No products found that need EFRIS registration')
#                 return results
# 
#             logger.info(f"Starting bulk registration of {results['total']} products for company {company.name}")
# 
#             with EnhancedEFRISAPIClient(company) as client:
#                 # Process products in smaller batches to avoid timeouts
#                 batch_size = 10
#                 for i in range(0, results['total'], batch_size):
#                     batch_products = products[i:i + batch_size]
# 
#                     for product in batch_products:
#                         try:
#                             # Validate product before registration
#                             validation_errors = []
# 
#                             if not product.name or len(product.name.strip()) < 2:
#                                 validation_errors.append("Product name is too short")
# 
#                             if not hasattr(product, 'selling_price') or product.selling_price is None:
#                                 validation_errors.append("Selling price is missing")
# 
#                             if validation_errors:
#                                 results['failed'] += 1
#                                 results['errors'].append({
#                                     'product_id': product.id,
#                                     'sku': getattr(product, 'sku', 'N/A'),
#                                     'name': product.name,
#                                     'error': f"Validation failed: {'; '.join(validation_errors)}"
#                                 })
#                                 continue
# 
#                             # Register the product
#                             result = client.register_product_with_efris(product)
# 
#                             if result.get('success'):
#                                 results['successful'] += 1
#                                 results['registered_products'].append({
#                                     'product_id': product.id,
#                                     'sku': getattr(product, 'sku', 'N/A'),
#                                     'name': product.name,
#                                     'item_code': result.get('item_code', 'N/A')
#                                 })
#                                 logger.info(f"Successfully registered product: {product.name}")
#                             else:
#                                 results['failed'] += 1
#                                 error_detail = {
#                                     'product_id': product.id,
#                                     'sku': getattr(product, 'sku', 'N/A'),
#                                     'name': product.name,
#                                     'error': result.get('error', 'Unknown error'),
#                                     'error_code': result.get('error_code')
#                                 }
#                                 results['errors'].append(error_detail)
#                                 logger.error(f"Failed to register product {product.name}: {result.get('error')}")
# 
#                         except Exception as e:
#                             results['failed'] += 1
#                             error_detail = {
#                                 'product_id': product.id,
#                                 'sku': getattr(product, 'sku', 'N/A'),
#                                 'name': product.name,
#                                 'error': f"Registration exception: {str(e)}"
#                             }
#                             results['errors'].append(error_detail)
#                             logger.error(f"Exception during product registration: {e}", exc_info=True)
# 
#                     # Add small delay between batches to avoid overwhelming EFRIS
#                     if i + batch_size < results['total']:
#                         import time
#                         time.sleep(1)
# 
#     except Exception as e:
#         results['errors'].append({
#             'product_id': None,
#             'sku': 'SYSTEM',
#             'name': 'Bulk Registration',
#             'error': f"System error: {str(e)}"
#         })
#         logger.error(f"Bulk registration system error: {e}", exc_info=True)
# 
#     # Generate summary
#     success_rate = (results['successful'] / results['total'] * 100) if results['total'] > 0 else 0
#     logger.info(
#         f"Bulk registration completed: {results['successful']}/{results['total']} "
#         f"products registered ({success_rate:.1f}% success rate)"
#     )
# 
#     return results
# 
# 
# def debug_product_json_format(product):
#     """
#     Debug function to test JSON serialization of product data
#     """
#     print("=== PRODUCT JSON DEBUG ===")
# 
#     try:
#         # Build the same data structure as register_product_with_efris
#         commodity_category_id = (
#                 # getattr(product, 'efris_commodity_category_id', None) or
#                 # (getattr(product.category, 'efris_commodity_category_id', None)
#                 #  if hasattr(product, 'category') and product.category else None) or
#                 '101113010000000000'
#         )
# 
#         item_code = getattr(product, 'efris_item_code', None)
#         if not item_code:
#             item_code = f"{getattr(product, 'sku', 'PROD')}_{product.id}"
# 
#         selling_price = getattr(product, 'selling_price', 0) or 0
#         min_stock = getattr(product, 'min_stock_level', 0) or 0
# 
#         goods_data = {
#             "operationType": "101",
#             "commodityGoodsId": "",
#             "goodsCode": str(item_code),
#             "goodsName": str(product.name[:200] if product.name else "Unnamed Product"),
#             "goodsDesc": str((getattr(product, 'description', None) or product.name or "No description")[:1000]),
#             "categoryId": str(commodity_category_id),
#             "unitPrice": f"{float(selling_price):.2f}",
#             "currency": "UGX",
#             "unitOfMeasure": str(getattr(product, 'efris_unit_of_measure_code', None) or "U"),
#             "haveExciseTax": "102",
#             "stockPrewarning": str(int(min_stock))
#         }
# 
#         product_data = {
#             "goodsStockIn": [goods_data]
#         }
# 
#         # Test JSON serialization
#         json_str = json.dumps(product_data, ensure_ascii=False, separators=(',', ':'))
#         print(f"✅ JSON serialization successful")
#         print(f"Length: {len(json_str)} characters")
#         print(f"JSON: {json_str}")
# 
#         # Test deserialization
#         parsed_back = json.loads(json_str)
#         print(f"✅ JSON deserialization successful")
# 
#         # Check for problematic characters
#         problematic_chars = []
#         for char in json_str:
#             if ord(char) > 127 or char in ['\n', '\r', '\t']:
#                 problematic_chars.append((char, ord(char)))
# 
#         if problematic_chars:
#             print(f"⚠️ Found {len(problematic_chars)} problematic characters:")
#             for char, code in problematic_chars[:10]:  # Show first 10
#                 print(f"   '{char}' (Unicode {code})")
#         else:
#             print(f"✅ No problematic characters found")
# 
#         return True, json_str
# 
#     except Exception as e:
#         print(f"❌ JSON formatting error: {e}")
#         print(f"Product ID: {product.id}")
#         print(f"Product name: {getattr(product, 'name', 'N/A')}")
#         print(f"Product description: {getattr(product, 'description', 'N/A')}")
#         return False, str(e)
# 
# class EFRISCustomerService:
#     """Enhanced service for handling EFRIS customer operations"""
# 
#     def __init__(self, company):
#         self.company = company
#         self.client = EnhancedEFRISAPIClient(company)
#         self.validator = DataValidator()
# 
#     def query_taxpayer(self, tin: str, nin_brn: Optional[str] = None) -> Tuple[bool, Union[Dict, str]]:
#         """T119 - Query taxpayer by TIN with enhanced validation and error handling"""
# 
#         # Validate TIN format
#         is_valid, error = self.validator.validate_tin(tin)
#         if not is_valid:
#             return False, f"Invalid TIN format: {error}"
# 
#         # Validate BRN if provided
#         if nin_brn:
#             is_valid_brn, brn_error = self.validator.validate_brn(nin_brn)
#             if not is_valid_brn:
#                 logger.warning(f"Invalid BRN provided: {brn_error}")
#                 nin_brn = None  # Clear invalid BRN
# 
#         try:
#             with self.client as client:
#                 response = client.query_taxpayer_by_tin(tin, nin_brn)
# 
#                 if response.success:
#                     # Process and validate taxpayer data
#                     taxpayer_data = self._process_taxpayer_data(response.data)
#                     return True, taxpayer_data
#                 else:
#                     error_msg = response.error_message or "Taxpayer query failed"
#                     logger.warning(
#                         "Taxpayer query failed",
#                         tin=tin,
#                         error=error_msg,
#                         error_code=response.error_code
#                     )
#                     return False, error_msg
# 
#         except Exception as e:
#             logger.error("Taxpayer query failed", tin=tin, error=str(e))
#             return False, f"Query error: {e}"
# 
#     def _process_taxpayer_data(self, raw_data: Optional[Dict]) -> Dict[str, Any]:
#         """Process and normalize taxpayer data from EFRIS response"""
#         if not raw_data:
#             return {}
# 
#         # Extract taxpayer information with safe defaults
#         taxpayer_info = raw_data.get('taxpayer', {})
# 
#         processed_data = {
#             'tin': taxpayer_info.get('tin', ''),
#             'nin_brn': taxpayer_info.get('ninBrn', ''),
#             'legal_name': taxpayer_info.get('legalName', ''),
#             'business_name': taxpayer_info.get('businessName', ''),
#             'trading_name': taxpayer_info.get('tradingName', ''),
#             'taxpayer_type': taxpayer_info.get('taxpayerType', ''),
#             'status': taxpayer_info.get('status', ''),
#             'registration_date': taxpayer_info.get('registrationDate', ''),
#             'address': taxpayer_info.get('address', ''),
#             'phone': taxpayer_info.get('mobilePhone', ''),
#             'email': taxpayer_info.get('emailAddress', ''),
#             'sector': taxpayer_info.get('sector', ''),
#             'is_vat_registered': taxpayer_info.get('isVATRegistered', False),
#             'effective_registration_date': taxpayer_info.get('effectiveRegistrationDate', ''),
#             'last_updated': timezone.now().isoformat()
#         }
# 
#         return processed_data
# 
#     def validate_customer_for_efris(self, customer) -> Tuple[bool, List[str]]:
#         """Enhanced customer validation for EFRIS operations"""
#         errors = []
# 
#         # Basic validation
#         if not customer:
#             return False, ["Customer object is required"]
# 
#         # Name validation
#         customer_name = getattr(customer, 'name', None)
#         if not customer_name or not customer_name.strip():
#             errors.append("Customer name is required")
#         elif len(customer_name.strip()) < 2:
#             errors.append("Customer name must be at least 2 characters")
# 
#         # Phone validation
#         phone = getattr(customer, 'phone', None)
#         if not phone or not phone.strip():
#             errors.append("Customer phone number is required")
#         else:
#             # Basic phone format validation for Uganda
#             clean_phone = phone.replace(' ', '').replace('-', '').replace('+', '')
#             if not (clean_phone.isdigit() and len(clean_phone) >= 9):
#                 errors.append("Invalid phone number format")
# 
#         # Business customer validation
#         customer_type = getattr(customer, 'customer_type', '').upper()
#         if customer_type in ['BUSINESS', 'CORPORATE', 'COMPANY']:
#             tin = getattr(customer, 'tin', None)
#             brn = getattr(customer, 'brn', None)
# 
#             if not tin and not brn:
#                 errors.append("Business customers must have either TIN or BRN")
# 
#             if tin:
#                 is_valid, error = self.validator.validate_tin(tin)
#                 if not is_valid:
#                     errors.append(f"Customer TIN: {error}")
# 
#             if brn:
#                 is_valid, error = self.validator.validate_brn(brn)
#                 if not is_valid:
#                     errors.append(f"Customer BRN: {error}")
# 
#         # Email validation if provided
#         email = getattr(customer, 'email', None)
#         if email and email.strip():
#             if '@' not in email or '.' not in email.split('@')[1]:
#                 errors.append("Invalid email format")
# 
#         return len(errors) == 0, errors
# 
#     def enrich_customer_from_efris(self, customer) -> Tuple[bool, str]:
#         """Enrich customer data from EFRIS taxpayer information"""
# 
#         if not customer:
#             return False, "Customer is required"
# 
#         customer_tin = getattr(customer, 'tin', None)
#         if not customer_tin:
#             return False, "Customer TIN is required for EFRIS enrichment"
# 
#         try:
#             # Query EFRIS for taxpayer info
#             success, result = self.query_taxpayer(customer_tin)
# 
#             if not success:
#                 return False, f"EFRIS query failed: {result}"
# 
#             if not isinstance(result, dict):
#                 return False, "Invalid EFRIS response format"
# 
#             # Update customer with EFRIS data
#             updates_made = []
# 
#             # Update business name if not set
#             if not getattr(customer, 'business_name', None) and result.get('business_name'):
#                 customer.business_name = result['business_name']
#                 updates_made.append('business_name')
# 
#             # Update legal name if not set
#             if not getattr(customer, 'legal_name', None) and result.get('legal_name'):
#                 customer.legal_name = result['legal_name']
#                 updates_made.append('legal_name')
# 
#             # Update address if not set
#             if not getattr(customer, 'address', None) and result.get('address'):
#                 customer.address = result['address']
#                 updates_made.append('address')
# 
#             # Update contact info if not set
#             if not getattr(customer, 'email', None) and result.get('email'):
#                 customer.email = result['email']
#                 updates_made.append('email')
# 
#             if not getattr(customer, 'phone', None) and result.get('phone'):
#                 customer.phone = result['phone']
#                 updates_made.append('phone')
# 
#             # Set customer type based on EFRIS data
#             if result.get('taxpayer_type') and not getattr(customer, 'customer_type', None):
#                 customer.customer_type = 'BUSINESS' if result['is_vat_registered'] else 'INDIVIDUAL'
#                 updates_made.append('customer_type')
# 
#             # Save updates
#             if updates_made:
#                 customer.save(update_fields=updates_made)
#                 return True, f"Customer enriched with: {', '.join(updates_made)}"
#             else:
#                 return True, "No updates needed - customer data is complete"
# 
#         except Exception as e:
#             logger.error(
#                 "Customer enrichment failed",
#                 customer_id=getattr(customer, 'pk', None),
#                 error=str(e)
#             )
#             return False, f"Enrichment error: {e}"
# 
# 
# class EFRISInvoiceService:
#     """Service wrapper for invoice fiscalization with consistent return format"""
# 
#     def __init__(self, company):
#         self.company = company
# 
#     def fiscalize_invoice(self, invoice, user=None) -> Dict[str, Any]:
#         """Fiscalize invoice with proper return format"""
#         try:
#             with EnhancedEFRISAPIClient(self.company) as client:
#                 result = client.upload_invoice(invoice, user)
# 
#                 # Log raw result for debugging
#                 logger.debug(f"Raw upload_invoice result for invoice {invoice.id}: {result} (type: {type(result)})")
# 
#                 # Ensure consistent return format
#                 if isinstance(result, dict):
#                     if result.get("success", False):
#                         return {
#                             "success": True,
#                             "message": result.get("message", "Invoice fiscalized successfully"),
#                             "data": result.get("data", {})
#                         }
#                     else:
#                         return {
#                             "success": False,
#                             "message": result.get("error", "Fiscalization failed"),
#                             "error_code": result.get("error_code"),
#                             "data": result.get("response_data")
#                         }
#                 elif isinstance(result, tuple):
#                     # Temporary handling for unexpected tuple response
#                     logger.warning(f"Unexpected tuple response from upload_invoice: {result}")
#                     if len(result) >= 2:
#                         success, message = result[:2]
#                         extra_data = result[2:] if len(result) > 2 else None
#                         return {
#                             "success": bool(success),
#                             "message": str(message) if message else "Unexpected tuple format",
#                             "data": {"extra": extra_data} if extra_data else {},
#                             "error_code": None
#                         }
#                     else:
#                         return {
#                             "success": False,
#                             "message": f"Invalid tuple format: {result}",
#                             "data": None,
#                             "error_code": None
#                         }
#                 else:
#                     logger.error(f"Unexpected response type from upload_invoice: {type(result)}")
#                     return {
#                         "success": False,
#                         "message": f"Unexpected response type: {type(result)}",
#                         "data": None,
#                         "error_code": None
#                     }
# 
#         except Exception as e:
#             logger.error(f"Invoice fiscalization failed for invoice {invoice.id}: {str(e)}", exc_info=True)
#             return {
#                 "success": False,
#                 "message": f"Fiscalization error: {str(e)}",
#                 "data": None,
#                 "error_code": None
#             }
# 
#     def bulk_fiscalize_invoices(self, invoices: List, user=None) -> Dict[str, Any]:
#         """
#         Bulk fiscalize multiple invoices
#         Required by bulk_fiscalize_invoices_async task
#         """
#         results = {
#             'success': True,
#             'total_invoices': len(invoices),
#             'successful_count': 0,
#             'failed_count': 0,
#             'errors': []
#         }
# 
#         for invoice in invoices:
#             try:
#                 result = self.fiscalize_invoice(invoice, user)
# 
#                 if result.get('success'):
#                     results['successful_count'] += 1
#                 else:
#                     results['failed_count'] += 1
#                     results['errors'].append({
#                         'invoice_id': invoice.id,
#                         'invoice_number': getattr(invoice, 'number', 'Unknown'),
#                         'error': result.get('message', 'Unknown error')
#                     })
#             except Exception as e:
#                 results['failed_count'] += 1
#                 results['errors'].append({
#                     'invoice_id': invoice.id,
#                     'invoice_number': getattr(invoice, 'number', 'Unknown'),
#                     'error': str(e)
#                 })
# 
#         # Overall success if at least 80% succeeded
#         if results['total_invoices'] > 0:
#             success_rate = results['successful_count'] / results['total_invoices']
#             results['success'] = success_rate >= 0.8
#         else:
#             results['success'] = False
# 
#         return results
# 
# def diagnose_efris_issue(company, invoice=None):
#     """Comprehensive EFRIS diagnostic tool"""
#     print("=== EFRIS DIAGNOSTIC REPORT ===")
#     print(f"Company: {company.name}")
#     print(f"TIN: {company.tin}")
#     print(f"Device: {getattr(company.efris_config, 'device_number', 'Not set')}")
#     print(f"Timestamp: {timezone.now()}")
#     print()
# 
#     try:
#         # Configuration Check
#         print("=== 1. CONFIGURATION CHECK ===")
#         config_issues = []
# 
#         if not hasattr(company, 'efris_config'):
#             config_issues.append("No EFRIS configuration found")
#         else:
#             config = company.efris_config
#             if not config.private_key:
#                 config_issues.append("Private key missing")
#             if not config.device_number:
#                 config_issues.append("Device number missing")
#             if not config.is_active:
#                 config_issues.append("Configuration not active")
# 
#         if config_issues:
#             print("❌ Issues found:")
#             for issue in config_issues:
#                 print(f"   - {issue}")
#         else:
#             print("✅ Configuration OK")
# 
#         # Connectivity Test
#         print("\n=== 2. CONNECTIVITY TEST ===")
#         try:
#             with EnhancedEFRISAPIClient(company) as client:
#                 result = client.get_server_time()
#                 if result.get("success"):
#                     print("✅ Server connectivity OK")
#                 else:
#                     print(f"❌ Server connectivity failed: {result.get('error')}")
#         except Exception as e:
#             print(f"❌ Connectivity test failed: {e}")
# 
#         # Authentication Test
#         print("\n=== 3. AUTHENTICATION TEST ===")
#         try:
#             with EnhancedEFRISAPIClient(company) as client:
#                 auth_result = client.ensure_authenticated()
#                 if auth_result.get("success"):
#                     print("✅ Authentication successful")
#                     if client.security_manager.is_aes_key_valid():
#                         print("✅ AES key is valid")
#                     else:
#                         print("❌ AES key invalid")
#                 else:
#                     print(f"❌ Authentication failed: {auth_result.get('error')}")
#         except Exception as e:
#             print(f"❌ Authentication test failed: {e}")
# 
#         # Invoice Test
#         if invoice:
#             print(f"\n=== 4. INVOICE TEST ({getattr(invoice, 'number', 'unknown')}) ===")
#             try:
#                 transformer = EFRISDataTransformer(company)
#                 invoice_data = transformer.build_invoice_data(invoice)
#                 print("✅ Invoice data structure OK")
# 
#                 # Validate amounts
#                 summary = invoice_data.get('summary', {})
#                 net_amount = float(summary.get('netAmount', 0))
#                 tax_amount = float(summary.get('taxAmount', 0))
#                 gross_amount = float(summary.get('grossAmount', 0))
# 
#                 expected_gross = net_amount + tax_amount
#                 if abs(gross_amount - expected_gross) <= 0.01:
#                     print("✅ Amount calculations correct")
#                     print(f"   Net: {net_amount}, Tax: {tax_amount}, Gross: {gross_amount}")
#                 else:
#                     print(f"❌ Amount calculation error:")
#                     print(f"   Expected: {expected_gross}, Actual: {gross_amount}")
# 
#             except Exception as e:
#                 print(f"❌ Invoice test failed: {e}")
# 
#         print("\n=== RECOMMENDATIONS ===")
#         print("1. Ensure device number matches EFRIS registration")
#         print("2. Verify private key is correct and not expired")
#         print("3. Check invoice amount calculations")
#         print("4. Ensure tax rates are properly mapped (A=18%, B=0%, etc.)")
#         print("5. Use SHA1withRSA signature as per EFRIS documentation")
# 
#     except Exception as e:
#         print(f"Diagnostic failed: {e}")
# 
# 
# def test_efris_integration(company, test_invoice=None):
#     """Test EFRIS integration step by step"""
#     print("=== EFRIS INTEGRATION TEST ===")
#     test_results = {}
# 
#     try:
#         with EnhancedEFRISAPIClient(company) as client:
# 
#             # Test T101
#             print("Testing T101 (Server Time)...")
#             result = client.get_server_time()
#             test_results['T101'] = result.get('success', False)
#             print(f"T101: {'✅ PASS' if result.get('success') else '❌ FAIL'}")
#             if not result.get('success'):
#                 print(f"   Error: {result.get('error')}")
# 
#             # Test Authentication
#             print("\nTesting Authentication Flow...")
#             result = client.ensure_authenticated()
#             test_results['AUTH'] = result.get('success', False)
#             print(f"Authentication: {'✅ PASS' if result.get('success') else '❌ FAIL'}")
#             if not result.get('success'):
#                 print(f"   Error: {result.get('error')}")
# 
#             # Test Invoice Upload
#             if test_invoice and test_results.get('AUTH'):
#                 print(f"\nTesting T109 (Invoice Upload)...")
#                 result = client.upload_invoice(test_invoice)
#                 test_results['T109'] = result.get('success', False)
#                 print(f"T109: {'✅ PASS' if result.get('success') else '❌ FAIL'}")
#                 if not result.get('success'):
#                     print(f"   Error: {result.get('error')}")
#                     if result.get('error_code'):
#                         print(f"   Code: {result.get('error_code')}")
# 
#         # Summary
#         passed = sum(1 for success in test_results.values() if success)
#         total = len(test_results)
#         print(f"\n=== TEST SUMMARY ===")
#         print(f"Tests Passed: {passed}/{total}")
# 
#         if passed == total:
#             print("🎉 All tests passed! EFRIS integration is working.")
#         else:
#             print("⚠️ Some tests failed. Check errors above.")
# 
#         return test_results
# 
#     except Exception as e:
#         print(f"Integration test failed: {e}")
#         return {"error": str(e)}
# 
# 
# class EFRISProductService:
#     """Enhanced service for handling EFRIS product operations"""
# 
#     def __init__(self, company):
#         self.company = company
#         self.client = EnhancedEFRISAPIClient(company)
# 
#     async def upload_products_async(self, products: List[Any], user: Optional[Any] = None) -> Tuple[bool, str]:
#         """Async version of product upload for better performance"""
#         # This would be implemented with proper async/await patterns in a real system
#         return self.upload_products(products, user)
# 
#     def upload_products(self, products: List[Any], user: Optional[Any] = None) -> Tuple[bool, str]:
#         """Upload products to EFRIS with enhanced validation and error handling"""
# 
#         if not products:
#             return False, "No products provided"
# 
#         try:
#             with self.client as client:
#                 # Validate products before upload
#                 validation_errors = self._validate_products(products)
#                 if validation_errors:
#                     return False, f"Validation failed: {'; '.join(validation_errors)}"
# 
#                 # Build products data
#                 products_data = self._build_products_data(products)
# 
#                 # Upload to EFRIS
#                 response = client.upload_goods(products_data)
# 
#                 if response.success:
#                     # Update products with response data
#                     updated_count = self._update_products_from_response(products, response.data)
#                     return True, f"Successfully uploaded {updated_count} products"
#                 else:
#                     return False, response.error_message or "Upload failed"
# 
#         except Exception as e:
#             logger.error("Product upload failed", error=str(e))
#             return False, f"Upload error: {e}"
# 
#     def _validate_products(self, products: List[Any]) -> List[str]:
#         """Validate products before upload"""
#         errors = []
# 
#         if len(products) > EFRISConstants.MAX_BATCH_SIZE:
#             errors.append(f"Too many products (max {EFRISConstants.MAX_BATCH_SIZE})")
# 
#         for i, product in enumerate(products, 1):
#             if not getattr(product, 'name', None):
#                 errors.append(f"Product {i}: Name is required")
# 
#             if not getattr(product, 'sku', None):
#                 errors.append(f"Product {i}: SKU is required")
# 
#             selling_price = getattr(product, 'selling_price', 0)
#             is_valid, error = DataValidator.validate_amount(selling_price, f"Product {i} selling price")
#             if not is_valid:
#                 errors.append(error)
# 
#         return errors
# 
#     def _build_products_data(self, products: List[Any]) -> List[Dict]:
#         """Build product data for EFRIS upload with enhanced mapping"""
#         products_data = []
# 
#         for product in products:
#             is_uploaded = getattr(product, 'efris_is_uploaded', False)
# 
#             # Determine operation type
#             operation_type = "102" if is_uploaded else "101"  # Update or Create
# 
#             product_data = {
#                 "operationType": operation_type,
#                 "goodsName": self._get_efris_goods_name(product),
#                 "goodsCode": self._get_efris_goods_code(product),
#                 "measureUnit": self._get_unit_of_measure(product),
#                 "unitPrice": str(getattr(product, 'selling_price', 0)),
#                 "currency": "101",  # UGX
#                 "commodityCategoryId": self._get_commodity_category_id(product),
#                 "haveExciseTax": "101" if self._has_excise_tax(product) else "102",
#                 "description": self._get_product_description(product),
#                 "stockPrewarning": str(getattr(product, 'min_stock_level', 0)),
#                 "havePieceUnit": "102"  # No piece unit by default
#             }
# 
#             # Add excise duty information if applicable
#             if self._has_excise_tax(product):
#                 excise_rate = getattr(product, 'excise_duty_rate', 0) or 0
#                 product_data.update({
#                     "exciseDutyCode": getattr(product, 'efris_excise_duty_code', '') or "",
#                     "pieceUnitPrice": str(getattr(product, 'selling_price', 0)),
#                     "packageScaledValue": "1",
#                     "pieceScaledValue": "1"
#                 })
# 
#             products_data.append(product_data)
# 
#         return products_data
# 
#     def _get_efris_goods_name(self, product) -> str:
#         """Get EFRIS goods name with fallback"""
#         return (getattr(product, 'efris_goods_name', None) or
#                 getattr(product, 'name', '') or
#                 'Unnamed Product')
# 
#     def _get_efris_goods_code(self, product) -> str:
#         """Get EFRIS goods code with fallback"""
#         return (getattr(product, 'efris_goods_code', None) or
#                 getattr(product, 'sku', '') or
#                 f'PROD{getattr(product, "pk", 0):06d}')
# 
#     def _get_unit_of_measure(self, product) -> str:
#         """Get unit of measure with default"""
#         return (getattr(product, 'efris_unit_of_measure_code', None) or
#                 getattr(product, 'unit_of_measure', None) or
#                 'U')  # Default to 'Unit'
# 
#     def _get_commodity_category_id(self, product) -> str:
#         """Get commodity category ID with default"""
#         return (getattr(product, 'efris_commodity_category_id', None) or
#                 "1010101000")  # General goods category
# 
#     def _has_excise_tax(self, product) -> bool:
#         """Check if product has excise tax"""
#         excise_rate = getattr(product, 'excise_duty_rate', 0) or 0
#         return excise_rate > 0
# 
#     def _get_product_description(self, product) -> str:
#         """Get product description with fallback"""
#         return (getattr(product, 'efris_goods_description', None) or
#                 getattr(product, 'description', '') or
#                 getattr(product, 'name', '') or
#                 'No description available')
# 
#     def _update_products_from_response(self, products: List[Any], response_data: Optional[Dict]) -> int:
#         """Update products with EFRIS upload results"""
#         updated_count = 0
# 
#         try:
#             if not response_data:
#                 return updated_count
# 
#             # Handle different response formats
#             if isinstance(response_data, list):
#                 # Batch response with individual results
#                 for idx, product in enumerate(products):
#                     if idx < len(response_data):
#                         result = response_data[idx]
#                         if result.get('returnCode') == EFRISConstants.SUCCESS_CODE:
#                             if self._mark_product_uploaded(product, result):
#                                 updated_count += 1
#             elif isinstance(response_data, dict):
#                 # Single response or bulk success
#                 for product in products:
#                     if self._mark_product_uploaded(product, response_data):
#                         updated_count += 1
# 
#         except Exception as e:
#             logger.error("Failed to update products from response", error=str(e))
# 
#         return updated_count
# 
#     def _mark_product_uploaded(self, product: Any, result: Dict) -> bool:
#         """Mark product as uploaded to EFRIS"""
#         try:
#             # Update product fields
#             updates = {}
# 
#             if hasattr(product, 'efris_is_uploaded'):
#                 updates['efris_is_uploaded'] = True
# 
#             if hasattr(product, 'efris_upload_date'):
#                 updates['efris_upload_date'] = timezone.now()
# 
#             if 'goodsId' in result and hasattr(product, 'efris_goods_id'):
#                 updates['efris_goods_id'] = result['goodsId']
# 
#             if updates:
#                 for field, value in updates.items():
#                     setattr(product, field, value)
# 
#                 product.save(update_fields=list(updates.keys()))
#                 return True
# 
#         except Exception as e:
#             logger.error(
#                 "Failed to mark product as uploaded",
#                 product_id=getattr(product, 'pk', None),
#                 error=str(e)
#             )
# 
#         return False
# 
# 
# 
# def create_efris_service(company, service_type: str = 'client'):
#     """Factory function to create EFRIS services with validation"""
# 
#     if not company:
#         raise EFRISConfigurationError("Company is required")
# 
#     if not getattr(company, 'efris_enabled', False):
#         raise EFRISConfigurationError("EFRIS is not enabled for this company")
# 
#     services = {
#         'client': EnhancedEFRISAPIClient,
#         'product': EFRISProductService,
#         'invoice': EFRISInvoiceService,
#         'customer': EFRISCustomerService,
#     }
# 
#     service_class = services.get(service_type)
#     if not service_class:
#         available = ', '.join(services.keys())
#         raise ValueError(f"Unknown service type '{service_type}'. Available: {available}")
# 
#     try:
#         return service_class(company)
#     except Exception as e:
#         logger.error(
#             "Failed to create EFRIS service",
#             company_id=getattr(company, 'pk', None),
#             service_type=service_type,
#             error=str(e)
#         )
#         raise EFRISConfigurationError(f"Failed to create {service_type} service: {e}")
# 
# 
# def validate_efris_configuration(company) -> Tuple[bool, List[str]]:
#     """Comprehensive EFRIS configuration validation"""
#     try:
#         config_manager = ConfigurationManager(company)
#         # If we can create the config manager without exceptions, it's valid
#         return True, []
#     except EFRISConfigurationError as e:
#         return False, [str(e)]
#     except Exception as e:
#         logger.error("Unexpected error during configuration validation", error=str(e))
#         return False, [f"Validation error: {e}"]
# 
# 
# @asynccontextmanager
# async def efris_client_context(company):
#     """Async context manager for EFRIS client"""
#     client = None
#     try:
#         client = EnhancedEFRISAPIClient(company)
#         yield client
#     finally:
#         if client:
#             client.close()
# 
# 
# 
# class EFRISHealthChecker:
#     """Health check utilities for EFRIS integration"""
# 
#     def __init__(self, company):
#         self.company = company
# 
#     def check_system_health(self) -> Dict[str, Any]:
#         """Comprehensive health check"""
#         health_status = {
#             'overall_status': 'healthy',
#             'checks': {},
#             'timestamp': timezone.now().isoformat(),
#             'company_id': self.company.pk
#         }
# 
#         # Check configuration
#         config_status = self._check_configuration()
#         health_status['checks']['configuration'] = config_status
# 
#         # Check connectivity
#         connectivity_status = self._check_connectivity()
#         health_status['checks']['connectivity'] = connectivity_status
# 
#         # Check authentication
#         auth_status = self._check_authentication()
#         health_status['checks']['authentication'] = auth_status
# 
#         # Check recent operations
#         operations_status = self._check_recent_operations()
#         health_status['checks']['recent_operations'] = operations_status
# 
#         # Determine overall status
#         failed_checks = [
#             check for check in health_status['checks'].values()
#             if not check.get('healthy', False)
#         ]
# 
#         if failed_checks:
#             health_status['overall_status'] = 'unhealthy' if len(failed_checks) > 1 else 'degraded'
# 
#         return health_status
# 
#     def _check_configuration(self) -> Dict[str, Any]:
#         """Check EFRIS configuration validity"""
#         try:
#             is_valid, errors = validate_efris_configuration(self.company)
#             return {
#                 'healthy': is_valid,
#                 'errors': errors,
#                 'check_type': 'configuration'
#             }
#         except Exception as e:
#             return {
#                 'healthy': False,
#                 'errors': [str(e)],
#                 'check_type': 'configuration'
#             }
# 
#     def _check_connectivity(self) -> Dict[str, Any]:
#         """Check EFRIS API connectivity"""
#         try:
#             with EnhancedEFRISAPIClient(self.company) as client:
#                 response = client.get_server_time()
#                 return {
#                     'healthy': response.success,
#                     'response_time_ms': response.duration_ms,
#                     'error': response.error_message if not response.success else None,
#                     'check_type': 'connectivity'
#                 }
#         except Exception as e:
#             return {
#                 'healthy': False,
#                 'error': str(e),
#                 'check_type': 'connectivity'
#             }
# 
#     def _check_authentication(self) -> Dict[str, Any]:
#         """Check EFRIS authentication status"""
#         try:
#             with EnhancedEFRISAPIClient(self.company) as client:
#                 # Try a simple authenticated operation
#                 auth_response = client.authenticate()
#                 return {
#                     'healthy': auth_response.success,
#                     'authenticated': client.is_authenticated,
#                     'error': auth_response.error_message if not auth_response.success else None,
#                     'check_type': 'authentication'
#                 }
#         except Exception as e:
#             return {
#                 'healthy': False,
#                 'error': str(e),
#                 'authenticated': False,
#                 'check_type': 'authentication'
#             }
# 
#     def _check_recent_operations(self) -> Dict[str, Any]:
#         """Check recent EFRIS operations status"""
#         try:
#             # Get recent API logs (last 24 hours)
#             recent_logs = EFRISAPILog.objects.filter(
#                 company=self.company,
#                 created_at__gte=timezone.now() - timedelta(hours=24)
#             ).order_by('-created_at')[:10]
# 
#             if not recent_logs:
#                 return {
#                     'healthy': True,
#                     'message': 'No recent operations',
#                     'check_type': 'recent_operations'
#                 }
# 
#             success_count = sum(1 for log in recent_logs if log.status == OperationStatus.SUCCESS.value)
#             success_rate = success_count / len(recent_logs) if recent_logs else 1.0
# 
#             return {
#                 'healthy': success_rate >= 0.8,  # 80% success rate threshold
#                 'success_rate': success_rate,
#                 'total_operations': len(recent_logs),
#                 'successful_operations': success_count,
#                 'check_type': 'recent_operations'
#             }
# 
#         except Exception as e:
#             return {
#                 'healthy': False,
#                 'error': str(e),
#                 'check_type': 'recent_operations'
#             }
# 
# 
# class EFRISMetricsCollector:
#     """Enhanced metrics collection for EFRIS operations"""
# 
#     @staticmethod
#     def get_system_metrics(company, time_range_hours: int = 24) -> Dict[str, Any]:
#         """Get comprehensive system metrics"""
#         start_time = timezone.now() - timedelta(hours=time_range_hours)
# 
#         # Get API logs for the time range
#         api_logs = EFRISAPILog.objects.filter(
#             company=company,
#             created_at__gte=start_time
#         ).values('interface_code', 'status', 'duration_ms', 'created_at')
# 
#         # Calculate metrics
#         metrics = {
#             'time_range_hours': time_range_hours,
#             'total_requests': len(api_logs),
#             'interfaces': {},
#             'overall': {
#                 'success_rate': 0,
#                 'average_duration_ms': 0,
#                 'error_rate': 0
#             },
#             'errors': [],
#             'performance': {
#                 'fastest_request_ms': None,
#                 'slowest_request_ms': None,
#                 'requests_per_hour': 0
#             }
#         }
# 
#         if not api_logs:
#             return metrics
# 
#         # Process logs
#         successful_requests = 0
#         total_duration = 0
#         durations = []
#         interface_stats = {}
#         errors = []
# 
#         for log in api_logs:
#             interface = log['interface_code']
#             status = log['status']
#             duration = log['duration_ms'] or 0
# 
#             # Interface-specific metrics
#             if interface not in interface_stats:
#                 interface_stats[interface] = {
#                     'total': 0,
#                     'successful': 0,
#                     'total_duration': 0,
#                     'errors': []
#                 }
# 
#             interface_stats[interface]['total'] += 1
#             interface_stats[interface]['total_duration'] += duration
# 
#             if status == OperationStatus.SUCCESS.value:
#                 successful_requests += 1
#                 interface_stats[interface]['successful'] += 1
#             else:
#                 error_info = {
#                     'interface_code': interface,
#                     'timestamp': log['created_at'],
#                     'status': status
#                 }
#                 errors.append(error_info)
#                 interface_stats[interface]['errors'].append(error_info)
# 
#             total_duration += duration
#             durations.append(duration)
# 
#         # Calculate overall metrics
#         metrics['overall']['success_rate'] = successful_requests / len(api_logs)
#         metrics['overall']['error_rate'] = 1 - metrics['overall']['success_rate']
#         metrics['overall']['average_duration_ms'] = total_duration / len(api_logs)
# 
#         # Performance metrics
#         if durations:
#             metrics['performance']['fastest_request_ms'] = min(durations)
#             metrics['performance']['slowest_request_ms'] = max(durations)
# 
#         metrics['performance']['requests_per_hour'] = len(api_logs) / time_range_hours
# 
#         # Interface-specific metrics
#         for interface, stats in interface_stats.items():
#             metrics['interfaces'][interface] = {
#                 'total_requests': stats['total'],
#                 'success_rate': stats['successful'] / stats['total'],
#                 'average_duration_ms': stats['total_duration'] / stats['total'],
#                 'error_count': len(stats['errors'])
#             }
# 
#         metrics['errors'] = errors[:10]  # Limit to recent errors
# 
#         return metrics
# 
#     @staticmethod
#     def get_invoice_fiscalization_metrics(company, days: int = 30) -> Dict[str, Any]:
#         """Get invoice fiscalization-specific metrics"""
#         start_date = timezone.now().date() - timedelta(days=days)
# 
#         # Get fiscalization audits
#         audits = FiscalizationAudit.objects.filter(
#             invoice__company=company,
#             created_at__date__gte=start_date
#         ).values('success', 'action', 'created_at__date').order_by('created_at__date')
# 
#         metrics = {
#             'period_days': days,
#             'total_fiscalization_attempts': 0,
#             'successful_fiscalizations': 0,
#             'failed_fiscalizations': 0,
#             'success_rate': 0,
#             'daily_breakdown': {},
#             'common_errors': []
#         }
# 
#         if not audits:
#             return metrics
# 
#         # Process audits
#         daily_stats = {}
#         successful_count = 0
# 
#         for audit in audits:
#             date_str = audit['created_at__date'].isoformat()
# 
#             if date_str not in daily_stats:
#                 daily_stats[date_str] = {'attempts': 0, 'successes': 0}
# 
#             if audit['action'] == 'FISCALIZE':
#                 daily_stats[date_str]['attempts'] += 1
#                 metrics['total_fiscalization_attempts'] += 1
# 
#                 if audit['success']:
#                     daily_stats[date_str]['successes'] += 1
#                     successful_count += 1
# 
#         metrics['successful_fiscalizations'] = successful_count
#         metrics['failed_fiscalizations'] = metrics['total_fiscalization_attempts'] - successful_count
# 
#         if metrics['total_fiscalization_attempts'] > 0:
#             metrics['success_rate'] = successful_count / metrics['total_fiscalization_attempts']
# 
#         metrics['daily_breakdown'] = daily_stats
# 
#         return metrics
# 
# 
# 
# class EFRISConfigurationWizard:
#     """Helper class for setting up EFRIS configuration"""
# 
#     def __init__(self, company):
#         self.company = company
# 
#     def validate_setup_requirements(self) -> Dict[str, Any]:
#         """Validate all requirements for EFRIS setup"""
#         requirements = {
#             'company_info': self._validate_company_info(),
#             'certificates': self._validate_certificates(),
#             'network': self._validate_network_access(),
#             'permissions': self._validate_permissions()
#         }
# 
#         # Make sure 'valid' fields are booleans, not iterables
#         all_valid = all(req.get('valid', False) for req in requirements.values())
# 
#         return {
#             'ready_for_setup': all_valid,
#             'requirements': requirements,
#             'next_steps': self._get_next_steps(requirements)
#         }
# 
#     def _validate_company_info(self) -> Dict[str, Any]:
#         """Validate company information completeness"""
#         required_fields = {
#             'tin': 'Tax Identification Number',
#             'name': 'Company Name',
#             'efris_taxpayer_name': 'EFRIS Taxpayer Name',
#             'efris_business_name': 'EFRIS Business Name',
#             'efris_email_address': 'EFRIS Email Address',
#             'efris_phone_number': 'EFRIS Phone Number',
#             'efris_business_address': 'EFRIS Business Address'
#         }
# 
#         missing_fields = []
#         invalid_fields = []
# 
#         for field, display_name in required_fields.items():
#             value = getattr(self.company, field, None)
# 
#             if not value:
#                 missing_fields.append(display_name)
#             elif field == 'tin':
#                 is_valid, error = DataValidator.validate_tin(value)
#                 if not is_valid:
#                     invalid_fields.append(f"{display_name}: {error}")
# 
#         return {
#             'valid': len(missing_fields) == 0 and len(invalid_fields) == 0,
#             'missing_fields': missing_fields,
#             'invalid_fields': invalid_fields
#         }
# 
#     def _validate_certificates(self) -> Dict[str, Any]:
#         """Validate certificate requirements"""
#         # Wrap boolean values consistently
#         has_certificate = bool(getattr(self.company, 'certificate', False))
#         certificate_valid = has_certificate  # Placeholder
#         certificate_uploaded = has_certificate  # Placeholder
# 
#         return {
#             'valid': has_certificate and certificate_valid and certificate_uploaded,
#             'has_certificate': has_certificate,
#             'certificate_valid': certificate_valid,
#             'certificate_uploaded': certificate_uploaded
#         }
# 
#     def _validate_network_access(self) -> Dict[str, Any]:
#         """Validate network access to EFRIS servers"""
#         try:
#             config = {
#                 'api_url': getattr(settings, 'EFRIS_API_URL', 'https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation'),
#                 'timeout': 10
#             }
# 
#             response = requests.get(config['api_url'], timeout=config['timeout'])
# 
#             return {
#                 'valid': response.status_code < 500,
#                 'status_code': response.status_code,
#                 'response_time_ms': int(response.elapsed.total_seconds() * 1000)
#             }
# 
#         except requests.RequestException as e:
#             return {
#                 'valid': False,
#                 'error': str(e)
#             }
# 
#     def _validate_permissions(self) -> Dict[str, Any]:
#         """Validate required permissions"""
#         return {
#             'valid': True,  # Adjust actual checks as needed
#             'database_access': True,
#             'file_system_access': True,
#             'cache_access': True
#         }
# 
#     def _get_next_steps(self, requirements: Dict[str, Any]) -> List[str]:
#         """Get next steps based on validation results"""
#         steps = []
# 
#         if not requirements['company_info']['valid']:
#             steps.append("Complete company information in EFRIS settings")
# 
#         if not requirements['certificates']['valid']:
#             steps.append("Generate and upload digital certificates")
# 
#         if not requirements['network']['valid']:
#             steps.append("Verify network connectivity to EFRIS servers")
# 
#         if not requirements['permissions']['valid']:
#             steps.append("Ensure all required system permissions are granted")
# 
#         if not steps:
#             steps.append("Configuration is complete. You can now initialize EFRIS integration.")
# 
#         return steps
# 
#     def generate_setup_checklist(self) -> Dict[str, Any]:
#         """Generate a comprehensive setup checklist"""
#         validation_result = self.validate_setup_requirements()
# 
#         checklist_items = [
#             {
#                 'title': 'Company Information',
#                 'description': 'Complete all required company details for EFRIS registration',
#                 'completed': bool(validation_result['requirements']['company_info']['valid']),
#                 'details': validation_result['requirements']['company_info']
#             },
#             {
#                 'title': 'Digital Certificates',
#                 'description': 'Generate and upload required digital certificates',
#                 'completed': bool(validation_result['requirements']['certificates']['valid']),
#                 'details': validation_result['requirements']['certificates']
#             },
#             {
#                 'title': 'Network Connectivity',
#                 'description': 'Verify connection to EFRIS servers',
#                 'completed': bool(validation_result['requirements']['network']['valid']),
#                 'details': validation_result['requirements']['network']
#             },
#             {
#                 'title': 'System Permissions',
#                 'description': 'Ensure all required system permissions are available',
#                 'completed': bool(validation_result['requirements']['permissions']['valid']),
#                 'details': validation_result['requirements']['permissions']
#             }
#         ]
# 
#         total_items = len(checklist_items)
#         completed_items = sum(1 for item in checklist_items if item['completed'])
#         completion_percentage = (completed_items / total_items) * 100 if total_items else 0
# 
#         return {
#             'ready_for_production': bool(validation_result['ready_for_setup']),
#             'completion_percentage': completion_percentage,
#             'checklist_items': checklist_items,
#             'next_steps': validation_result['next_steps']
#         }
# 
# # Example usage and integration helpers
# 
# def setup_efris_for_company(company) -> Dict[str, Any]:
#     """Complete EFRIS setup workflow for a company"""
# 
#     setup_result = {
#         'success': False,
#         'steps_completed': [],
#         'errors': [],
#         'warnings': []
#     }
# 
#     try:
#         # Step 1: Validate configuration
#         wizard = EFRISConfigurationWizard(company)
#         validation_result = wizard.validate_setup_requirements()
# 
#         if not validation_result['ready_for_setup']:
#             setup_result['errors'].append("Company not ready for EFRIS setup")
#             setup_result['validation_details'] = validation_result
#             return setup_result
# 
#         setup_result['steps_completed'].append('validation')
# 
#         # Step 2: Initialize EFRIS client
#         try:
#             client = EnhancedEFRISAPIClient(company)
#             setup_result['steps_completed'].append('client_initialization')
#         except Exception as e:
#             setup_result['errors'].append(f"Client initialization failed: {e}")
#             return setup_result
# 
#         # Step 3: Test connectivity
#         try:
#             with client:
#                 response = client.get_server_time()
#                 if response.success:
#                     setup_result['steps_completed'].append('connectivity_test')
#                 else:
#                     setup_result['warnings'].append(f"Connectivity test warning: {response.error_message}")
#         except Exception as e:
#             setup_result['errors'].append(f"Connectivity test failed: {e}")
#             return setup_result
# 
#         # Step 4: Run health check
#         try:
#             health_checker = EFRISHealthChecker(company)
#             health_status = health_checker.check_system_health()
#             setup_result['health_status'] = health_status
#             setup_result['steps_completed'].append('health_check')
# 
#             if health_status['overall_status'] != 'healthy':
#                 setup_result['warnings'].append("System health check shows issues")
# 
#         except Exception as e:
#             setup_result['warnings'].append(f"Health check failed: {e}")
# 
#         setup_result['success'] = True
#         setup_result[
#             'message'] = f"EFRIS setup completed successfully. {len(setup_result['steps_completed'])} steps completed."
# 
#     except Exception as e:
#         logger.error("EFRIS setup failed", company_id=company.pk, error=str(e))
#         setup_result['errors'].append(f"Setup failed: {e}")
# 
#     return setup_result
# 
# 
# # Constants and final exports
# __version__ = "2.0.0"
# __author__ = "EFRIS Integration Team"
# 
# # Export main classes and functions
# __all__ = [
#     'EFRISConstants',
#     'EFRISError',
#     'EFRISConfigurationError',
#     'EFRISNetworkError',
#     'EFRISValidationError',
#     'EFRISSecurityError',
#     'EFRISBusinessLogicError',
#     'EnhancedEFRISAPIClient',
#     'EFRISProductService',
#     'SecurityManager',
#     'ConfigurationManager',
#     'DataValidator',
#     'EFRISHealthChecker',
#     'EFRISMetricsCollector',
#     'EFRISConfigurationWizard',
#     'create_efris_service',
#     'validate_efris_configuration',
#     'setup_efris_for_company',
#     'efris_client_context'
# ]