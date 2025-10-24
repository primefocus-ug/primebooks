# import json
# import base64
# import uuid
# import os
# import pytz
# from datetime import datetime, timedelta,date
# from decimal import Decimal, InvalidOperation
# from typing import Dict, List, Optional, Tuple, Any, Union
# from dataclasses import dataclass, field
# from enum import Enum
# from contextlib import asynccontextmanager
# from datetime import datetime, date
# import requests
# import structlog
# from requests.adapters import HTTPAdapter
# from urllib3.util.retry import Retry
# from cryptography.hazmat.primitives import serialization
# from typing import Dict, Optional, Union, Tuple
# from cryptography.hazmat.primitives import hashes, padding as sym_padding
# from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
# from cryptography.hazmat.primitives.asymmetric import rsa, padding as rsa_padding
# from django.utils import timezone
# from django.utils import timezone
# from django.core.cache import cache
# from django.conf import settings
# from pydantic import BaseModel, field_validator, Field, ConfigDict
# import threading
# from django_tenants.utils import schema_context
# from .models import (
#     EFRISConfiguration, EFRISAPILog, FiscalizationAudit,
#     EFRISSystemDictionary
# )
# import re  # Added import for re module
# 
# logger = structlog.get_logger(__name__)
# 
# class EFRISConstants:
#     class InterfaceCodes:
#         GET_SERVER_TIME = 'T101'
#         CLIENT_INITIALIZATION = 'T102'
#         LOGIN = 'T103'
#         GET_SYMMETRIC_KEY = 'T104'
#         QUERY_BRANCH_LIST = 'T105'
#         QUERY_DEVICE_LIST = 'T106'
#         QUERY_INVOICE_APPLY_LIST = 'T107'
#         QUERY_INVOICE_DETAIL = 'T108'
#         UPLOAD_INVOICE = 'T109'
#         APPLY_CREDIT_NOTE = 'T110'
#         NOTICE_UPLOAD = 'T111'
#         QUERY_NOTICE_LIST = 'T112'
#         QUERY_NOTICE_DETAIL = 'T113'
#         QUERY_CREDIT_NOTE_LIST = 'T114'
#         GET_SYSTEM_DICTIONARY = 'T115'
#         Z_REPORT_DAILY_UPLOAD = 'T116'
#         INVOICE_CHECKS = 'T117'
#         QUERY_CREDIT_DEBIT_NOTE_DETAILS = 'T118'
#         QUERY_TAXPAYER = 'T119'
#         VOID_CREDIT_DEBIT_NOTE = 'T120'
#         ACQUIRE_EXCHANGE_RATE = 'T121'
#         QUERY_EXCHANGE_RATE = 'T122'
#         QUERY_COMMODITY_CATEGORY = 'T123'
#         QUERY_COMMODITY_CATEGORY_BY_KEYWORD = 'T124'
#         QUERY_EXCISE_DUTY = 'T125'
#         GET_ALL_EXCHANGE_RATES = 'T126'
#         GOODS_INQUIRY = 'T127'
#         GOODS_IMPORT = 'T128'
#         BATCH_INVOICE_UPLOAD = 'T129'
#         UPLOAD_GOODS = 'T130'
#         GOODS_STOCK_MAINTAIN = 'T131'
#         QUERY_GOODS_STOCK = 'T132'
#         QUERY_GOODS_STOCK_DETAIL = 'T133'
#         QUERY_GOODS_STOCK_APPLY_LIST = 'T134'
#         QUERY_GOODS_STOCK_APPLY_DETAIL = 'T135'
#         UPLOAD_CERTIFICATE = 'T136'
#         QUERY_CERTIFICATES = 'T137'
#         QUERY_BRANCH_LIST = 'T138'
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
# class OperationStatus(Enum):
#     SUCCESS = "success"
#     FAILED = "failed"
#     TIMEOUT = "timeout"
#     PENDING = "pending"
#     RETRYING = "retrying"
#     CANCELLED = "cancelled"
# 
# class EFRISErrorSeverity(Enum):
#     LOW = "low"
#     MEDIUM = "medium"
#     HIGH = "high"
#     CRITICAL = "critical"
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
# class EFRISConfigurationError(EFRISError):
#     def __init__(self, message: str, **kwargs):
#         super().__init__(message, severity=EFRISErrorSeverity.HIGH, **kwargs)
# 
# class EFRISNetworkError(EFRISError):
#     def __init__(self, message: str, **kwargs):
#         super().__init__(message, severity=EFRISErrorSeverity.MEDIUM, retryable=True, **kwargs)
# 
# class EFRISValidationError(EFRISError):
#     def __init__(self, message: str, **kwargs):
#         super().__init__(message, severity=EFRISErrorSeverity.HIGH, **kwargs)
# 
# class EFRISSecurityError(EFRISError):
#     """Security related errors"""
# 
#     def __init__(self, message: str, **kwargs):
#         super().__init__(message, severity=EFRISErrorSeverity.CRITICAL, **kwargs)
# 
# class EFRISBusinessLogicError(EFRISError):
#     def __init__(self, message: str, **kwargs):
#         super().__init__(message, severity=EFRISErrorSeverity.MEDIUM, **kwargs)
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
# class EncryptionDebugger:
#     @staticmethod
#     def analyze_key(key_bytes: bytes) -> dict:
#         """Analyze encryption key and suggest algorithm"""
#         key_len = len(key_bytes)
#         analysis = {
#             'length_bytes': key_len,
#             'length_bits': key_len * 8,
#             'hex_preview': key_bytes[:8].hex() if len(key_bytes) >= 8 else key_bytes.hex(),
#             'suggested_algorithms': []
#         }
# 
#         if key_len == 8:
#             analysis['suggested_algorithms'] = ['DES', '3DES (padded)']
#         elif key_len == 16:
#             analysis['suggested_algorithms'] = ['AES-128', '3DES (padded)']
#         elif key_len == 24:
#             analysis['suggested_algorithms'] = ['3DES', 'AES-192']
#         elif key_len == 32:
#             analysis['suggested_algorithms'] = ['AES-256']
#         else:
#             analysis['suggested_algorithms'] = ['UNKNOWN']
# 
#         return analysis
# 
#     @staticmethod
#     def test_encryption_algorithms(content: str, key: bytes) -> dict:
#         """Test content encryption with all possible algorithms"""
#         results = {}
# 
#         # Test 3DES (if 24-byte key)
#         if len(key) == 24:
#             results['3des'] = EncryptionDebugger._test_3des(content, key)
# 
#         # Test AES (if 16, 24, or 32-byte key)
#         if len(key) in [16, 24, 32]:
#             results['aes'] = EncryptionDebugger._test_aes(content, key)
# 
#         # Test DES (if 8-byte key or can be truncated)
#         if len(key) >= 8:
#             results['des'] = EncryptionDebugger._test_des(content, key[:8])
# 
#         return results
# 
#     @staticmethod
#     def _test_3des(content: str, key: bytes) -> dict:
#         """Test 3DES encryption"""
#         try:
#             content_bytes = content.encode('utf-8')
#             iv = b'\0' * 8  # FIXED: Use zero IV for CBC
#             cipher = Cipher(algorithms.TripleDES(key), modes.CBC(iv))
#             encryptor = cipher.encryptor()
# 
#             # PKCS7 padding for 64-bit block
#             padder = sym_padding.PKCS7(64).padder()
#             padded = padder.update(content_bytes) + padder.finalize()
# 
#             encrypted = encryptor.update(padded) + encryptor.finalize()
#             b64 = base64.b64encode(encrypted).decode('utf-8')
# 
#             # Test decrypt
#             decryptor = cipher.decryptor()
#             decrypted_padded = decryptor.update(encrypted) + decryptor.finalize()
#             unpadder = sym_padding.PKCS7(64).unpadder()
#             decrypted = unpadder.update(decrypted_padded) + unpadder.finalize()
# 
#             roundtrip_success = decrypted.decode('utf-8') == content
# 
#             return {
#                 'success': True,
#                 'encrypted_b64': b64[:50] + '...',
#                 'encrypted_length': len(b64),
#                 'roundtrip_success': roundtrip_success
#             }
#         except Exception as e:
#             return {'success': False, 'error': str(e)}
# 
#     @staticmethod
#     def _test_aes(content: str, key: bytes) -> dict:
#         """Test AES encryption"""
#         try:
#             content_bytes = content.encode('utf-8')
#             iv = b'\0' * 16  # FIXED: Use zero IV for CBC
#             cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
#             encryptor = cipher.encryptor()
# 
#             # PKCS7 padding for 128-bit block
#             padder = sym_padding.PKCS7(128).padder()
#             padded = padder.update(content_bytes) + padder.finalize()
# 
#             encrypted = encryptor.update(padded) + encryptor.finalize()
#             b64 = base64.b64encode(encrypted).decode('utf-8')
# 
#             # Test decrypt
#             decryptor = cipher.decryptor()
#             decrypted_padded = decryptor.update(encrypted) + decryptor.finalize()
#             unpadder = sym_padding.PKCS7(128).unpadder()
#             decrypted = unpadder.update(decrypted_padded) + unpadder.finalize()
# 
#             roundtrip_success = decrypted.decode('utf-8') == content
# 
#             return {
#                 'success': True,
#                 'encrypted_b64': b64[:50] + '...',
#                 'encrypted_length': len(b64),
#                 'roundtrip_success': roundtrip_success
#             }
#         except Exception as e:
#             return {'success': False, 'error': str(e)}
# 
#     @staticmethod
#     def _test_des(content: str, key: bytes) -> dict:
#         """Test DES encryption (using 3DES with key triplication)"""
#         try:
#             # DES uses 8-byte key, but we use 3DES for compatibility
#             key_24 = key[:8] * 3  # Triplicate the 8-byte key
#             return EncryptionDebugger._test_3des(content, key_24)
#         except Exception as e:
#             return {'success': False, 'error': str(e)}
# 
# class SecurityManager:
#     _t104_lock = threading.Lock()
#     def __init__(self, device_no: str, tin: str):
#         self.device_no = device_no
#         self.tin = tin
#         self.app_id = "AP04"
#         self._current_aes_key = None
#         self._aes_key_expiry = None
#         self._encryption_algorithm = None
# 
# 
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
#         """
#         FIXED: Generate AES key - now supports all valid lengths
#         """
#         if key_length not in [8, 16, 24, 32]:  # ✅ ADDED 24
#             raise ValueError(f"Unsupported key length: {key_length}. Valid: 8, 16, 24, 32")
#         return os.urandom(key_length)
# 
#     def get_current_aes_key(self) -> Optional[bytes]:
#         """Get current valid AES key with thread safety"""
#         # Check cache first (no lock needed for reads)
#         if self.is_aes_key_valid():
#             return self._current_aes_key
# 
#         cache_key = f"efris_aes_key_{self.tin}_{self.device_no}"
#         cached_data = cache.get(cache_key)
# 
#         if cached_data:
#             try:
#                 key_data, expiry_str = cached_data
#                 expiry = datetime.fromisoformat(expiry_str)
#                 if timezone.now() < expiry:
#                     self._current_aes_key = key_data
#                     self._aes_key_expiry = expiry
#                     return key_data
#             except (ValueError, TypeError):
#                 pass
# 
#         return None
# 
#     def set_current_aes_key(self, aes_key: bytes, expiry_hours: int = 24):
#         """Store AES key and detect algorithm"""
#         self._current_aes_key = aes_key
#         self._aes_key_expiry = timezone.now() + timedelta(hours=expiry_hours)
# 
#         # Detect algorithm
#         self._encryption_algorithm = self._detect_algorithm(aes_key)
# 
#         # Log key analysis
#         analysis = EncryptionDebugger.analyze_key(aes_key)
#         logger.info(
#             "AES key set and analyzed",
#             length_bytes=analysis['length_bytes'],
#             length_bits=analysis['length_bits'],
#             suggested_algorithms=analysis['suggested_algorithms'],
#             selected_algorithm=self._encryption_algorithm
#         )
# 
#         # Cache
#         cache_key = f"efris_aes_key_{self.tin}_{self.device_no}"
#         cache_value = (aes_key, self._aes_key_expiry.isoformat())
#         cache.set(cache_key, cache_value, timeout=expiry_hours * 3600)
# 
#     def is_aes_key_valid(self) -> bool:
#         """Check if current AES key is valid"""
#         if not self._current_aes_key or not self._aes_key_expiry:
#             return False
#         return timezone.now() < self._aes_key_expiry
# 
#     def _detect_algorithm(self, key: bytes) -> str:
#         """Detect encryption algorithm from key length"""
#         key_len = len(key)
# 
#         if key_len == 24:
#             # Most likely 3DES based on EFRIS documentation
#             return '3DES'
#         elif key_len == 16:
#             return 'AES-128'
#         elif key_len == 32:
#             return 'AES-256'
#         elif key_len == 8:
#             return 'DES'
#         else:
#             logger.warning(f"Unknown key length: {key_len}, defaulting to 3DES")
#             return '3DES'
# 
#     def create_t104_request(self, private_key=None) -> Dict:
#         """Create T104 request (no content, not encrypted)"""
#         return {
#             "data": {
#                 "content": "",
#                 "signature": "",
#                 "dataDescription": {
#                     "codeType": "0",
#                     "encryptCode": "0",
#                     "zipCode": "0"
#                 }
#             },
#             "globalInfo": self.create_global_info("T104"),
#             "returnStateInfo": {
#                 "returnCode": "",
#                 "returnMessage": ""
#             }
#         }
# 
#     # ============ ENCRYPTION & DECRYPTION ============
# 
#     def _prepare_aes_key(self, aes_key: bytes) -> bytes:
#         key_length = len(aes_key)
# 
#         # If docs say 8 bytes, force it
#         if key_length == 24:
#             logger.warning(f"Got 24-byte key but docs say 8 bytes - using first 8 bytes")
#             aes_key = aes_key[:8]  # Take first 8 bytes
#             key_length = 8
# 
#         if key_length == 8:
#             return aes_key + aes_key  # Duplicate to 16 bytes for AES-128
#         elif key_length in [16, 24, 32]:
#             return aes_key
#         else:
#             raise Exception(f"Unsupported AES key length: {key_length}")
# 
#     def encrypt_with_aes(self, content: str, aes_key: bytes) -> str:
#         """
#         Encrypt content using appropriate algorithm based on key length
#         Supports: DES, 3DES, AES-128, AES-256
#         FIXED: Use CBC mode with zero IV
#         """
#         if not content:
#             return ""
# 
#         try:
#             key_len = len(aes_key)
#             content_bytes = content.encode('utf-8')
# 
#             logger.debug(
#                 "Starting encryption",
#                 key_length=key_len,
#                 content_length=len(content),
#                 algorithm=self._encryption_algorithm or 'detecting'
#             )
# 
#             # FIXED: Use CBC with zero IV
#             if key_len == 24:
#                 # 3DES with 64-bit blocks
#                 iv = b'\0' * 8
#                 cipher = Cipher(algorithms.TripleDES(aes_key), modes.CBC(iv))
#                 padder = sym_padding.PKCS7(64).padder()
#                 algo_name = "3DES-CBC"
# 
#             elif key_len in [16, 32]:
#                 # AES with 128-bit blocks
#                 iv = b'\0' * 16
#                 cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
#                 padder = sym_padding.PKCS7(128).padder()
#                 algo_name = f"AES-{key_len * 8}-CBC"
# 
#             elif key_len == 8:
#                 # DES - convert to 3DES by triplication
#                 key_24 = aes_key * 3
#                 iv = b'\0' * 8
#                 cipher = Cipher(algorithms.TripleDES(key_24), modes.CBC(iv))
#                 padder = sym_padding.PKCS7(64).padder()
#                 algo_name = "DES (as 3DES)-CBC"
# 
#             else:
#                 raise ValueError(f"Unsupported key length: {key_len} bytes")
# 
#             # Encrypt
#             encryptor = cipher.encryptor()
#             padded_data = padder.update(content_bytes) + padder.finalize()
#             encrypted = encryptor.update(padded_data) + encryptor.finalize()
#             encrypted_b64 = base64.b64encode(encrypted).decode('utf-8').replace('\n', '').replace('\r', '')
# 
#             logger.info(
#                 "Encryption successful",
#                 algorithm=algo_name,
#                 input_length=len(content),
#                 output_length=len(encrypted_b64),
#                 padded_length=len(padded_data)
#             )
# 
#             logger.debug(
#                 "Encrypted data preview",
#                 first_20=encrypted_b64[:20],
#                 last_20=encrypted_b64[-20:]
#             )
# 
#             return encrypted_b64
# 
#         except Exception as e:
#             logger.error("Encryption failed", error=str(e), exc_info=True)
#             raise Exception(f"Encryption failed: {e}")
# 
#     def test_aes_roundtrip(self):
#         """Test that our AES encryption can be decrypted"""
#         aes_key = self.get_current_aes_key()
#         test_content = '{"test":"data"}'
# 
#         encrypted = self.encrypt_with_aes(test_content, aes_key)
#         logger.info(f"Test encrypted: {encrypted}")
# 
#         decrypted = self.decrypt_with_aes(encrypted, aes_key)
#         logger.info(f"Test decrypted: {decrypted}")
# 
#         if decrypted == test_content:
#             logger.info("✅ AES round-trip successful")
#             return True
#         else:
#             logger.error(f"❌ AES round-trip failed: '{decrypted}' != '{test_content}'")
#             return False
# 
#     def decrypt_with_aes_fixed(self, encrypted_content: str, aes_key: bytes) -> str:
#         """Enhanced decryption that handles misaligned block sizes"""
#         try:
#             # Remove ALL whitespace first
#             encrypted_content = ''.join(encrypted_content.split())
# 
#             # Decode base64
#             encrypted_data = base64.b64decode(encrypted_content)
# 
#             logger.debug(f"Encrypted data length: {len(encrypted_data)} bytes")
#             logger.debug(f"AES key length: {len(aes_key)} bytes")
# 
#             # Choose cipher based on key length
#             if len(aes_key) == 24:
#                 block_size = 8  # 3DES uses 64-bit blocks
#                 cipher = Cipher(algorithms.TripleDES(aes_key), modes.ECB())
#                 unpadder = sym_padding.PKCS7(64).unpadder()
#                 algo_name = "3DES"
#             elif len(aes_key) in [16, 32]:
#                 block_size = 16  # AES uses 128-bit blocks
#                 cipher = Cipher(algorithms.AES(aes_key), modes.ECB())
#                 unpadder = sym_padding.PKCS7(128).unpadder()
#                 algo_name = f"AES-{len(aes_key) * 8}"
#             else:
#                 raise ValueError(f"Unsupported key length: {len(aes_key)}")
# 
#             # CRITICAL FIX: Handle misaligned block sizes
#             if len(encrypted_data) % block_size != 0:
#                 logger.warning(
#                     f"Data length {len(encrypted_data)} is not multiple of block size {block_size}. "
#                     f"Attempting to fix alignment..."
#                 )
# 
#                 # Option 1: Try padding with zeros to next block boundary
#                 padded_length = ((len(encrypted_data) // block_size) + 1) * block_size
#                 padded_data = encrypted_data.ljust(padded_length, b'\x00')
# 
#                 logger.debug(f"Padded data length: {len(padded_data)} bytes")
#                 encrypted_data = padded_data
# 
#             # Decrypt
#             decryptor = cipher.decryptor()
#             decrypted_padded = decryptor.update(encrypted_data) + decryptor.finalize()
# 
#             # Remove padding
#             try:
#                 decrypted = unpadder.update(decrypted_padded) + unpadder.finalize()
#                 logger.debug("PKCS7 unpadding successful")
#             except Exception as padding_error:
#                 logger.warning(f"Padding removal failed: {padding_error}. Trying without unpadding.")
#                 # If unpadding fails, try to use the data as-is (might be already unpadded)
#                 decrypted = decrypted_padded
# 
#             result = decrypted.decode('utf-8', errors='ignore').strip()
#             logger.info(f"Decryption successful using {algo_name}: {len(result)} chars")
# 
#             return result
# 
#         except Exception as e:
#             logger.error(f"Decryption failed: {e}", exc_info=True)
#             raise Exception(f"Decryption failed: {e}")
# 
#     def decrypt_with_aes(self, encrypted_content: str, aes_key: bytes) -> str:
#         """Decrypt content using appropriate algorithm with enhanced error handling"""
#         try:
#             key_len = len(aes_key)
# 
#             # CRITICAL FIX: Remove ALL whitespace (newlines, spaces, tabs) from base64
#             # EFRIS sometimes includes line breaks in large responses
#             encrypted_content = ''.join(encrypted_content.split())
#             encrypted_data = base64.b64decode(encrypted_content)
# 
#             # Log for debugging
#             logger.debug(f"Encrypted data length: {len(encrypted_data)} bytes")
# 
#             # Choose cipher based on key length
#             if key_len == 24:
#                 block_size = 8  # 3DES uses 64-bit blocks
#                 cipher = Cipher(algorithms.TripleDES(aes_key), modes.ECB())
#                 unpadder = sym_padding.PKCS7(64).unpadder()
#                 algo_name = "3DES"
#             elif key_len in [16, 32]:
#                 block_size = 16  # AES uses 128-bit blocks
#                 cipher = Cipher(algorithms.AES(aes_key), modes.ECB())
#                 unpadder = sym_padding.PKCS7(128).unpadder()
#                 algo_name = f"AES-{key_len * 8}"
#             elif key_len == 8:
#                 block_size = 8
#                 key_24 = aes_key * 3
#                 cipher = Cipher(algorithms.TripleDES(key_24), modes.ECB())
#                 unpadder = sym_padding.PKCS7(64).unpadder()
#                 algo_name = "DES (as 3DES)"
#             else:
#                 raise ValueError(f"Unsupported key length: {key_len}")
# 
#             # VALIDATION: Check block alignment
#             if len(encrypted_data) % block_size != 0:
#                 raise ValueError(
#                     f"Data length {len(encrypted_data)} is not a multiple of "
#                     f"block size {block_size}. After cleaning whitespace, data is still misaligned. "
#                     f"This indicates the server sent corrupted or incorrectly encrypted data."
#                 )
# 
#             # Decrypt
#             decryptor = cipher.decryptor()
#             decrypted_padded = decryptor.update(encrypted_data) + decryptor.finalize()
#             decrypted = unpadder.update(decrypted_padded) + unpadder.finalize()
# 
#             result = decrypted.decode('utf-8')
#             logger.info(f"Decryption successful using {algo_name}: {len(result)} chars")
#             return result
# 
#         except ValueError as e:
#             logger.error(f"Decryption failed: {e}", exc_info=True)
#             raise Exception(f"Decryption failed: {e}")
#         except Exception as e:
#             logger.error(f"Decryption failed: {e}", exc_info=True)
#             raise Exception(f"Decryption failed: {e}")
# 
#     def decrypt_with_3des(self, encrypted_content: str, aes_key: bytes) -> str:
#         """Enhanced 3DES decryption with better encoding detection"""
#         try:
#             # Clean the input thoroughly
#             encrypted_content = ''.join(encrypted_content.split())
# 
#             # Base64 decode
#             encrypted_data = base64.b64decode(encrypted_content)
#             logger.debug(f"3DES input data length: {len(encrypted_data)} bytes")
# 
#             # Convert AES key to proper 3DES key (24 bytes)
#             if len(aes_key) == 16:
#                 des_key = aes_key + aes_key[:8]  # 16 + 8 = 24 bytes
#             elif len(aes_key) == 24:
#                 des_key = aes_key
#             else:
#                 des_key = aes_key.ljust(24, b'\x00')[:24]
# 
#             logger.debug(f"3DES key length: {len(des_key)} bytes")
# 
#             # Handle block alignment
#             block_size = 8
#             data_length = len(encrypted_data)
# 
#             if data_length % block_size != 0:
#                 logger.warning(f"3DES data length {data_length} not multiple of {block_size}")
#                 padded_length = ((data_length // block_size) + 1) * block_size
#                 encrypted_data = encrypted_data.ljust(padded_length, b'\x00')
#                 logger.debug(f"Padded 3DES data length: {len(encrypted_data)} bytes")
# 
#             # Decrypt
#             cipher = Cipher(algorithms.TripleDES(des_key), modes.ECB())
#             decryptor = cipher.decryptor()
#             decrypted_padded = decryptor.update(encrypted_data) + decryptor.finalize()
# 
#             # Try to remove padding
#             try:
#                 unpadder = sym_padding.PKCS7(64).unpadder()
#                 decrypted = unpadder.update(decrypted_padded) + unpadder.finalize()
#                 logger.debug("PKCS7 unpadding successful")
#             except Exception as padding_error:
#                 logger.warning(f"PKCS7 unpadding failed: {padding_error}")
#                 decrypted = decrypted_padded
# 
#             # Try multiple encoding strategies
#             encoding_strategies = [
#                 ('utf-8', 'strict'),
#                 ('utf-8', 'ignore'),
#                 ('utf-8', 'replace'),
#                 ('latin-1', 'strict'),
#                 ('cp1252', 'strict'),
#                 ('utf-16', 'strict'),
#                 ('utf-16-le', 'strict'),
#             ]
# 
#             for encoding, errors in encoding_strategies:
#                 try:
#                     result = decrypted.decode(encoding, errors=errors)
#                     # Basic validation - should have reasonable length and some structure
#                     if (1000 < len(result) < 100000000 and
#                             (('{' in result and '}' in result) or
#                              ('[' in result and ']' in result) or
#                              ('commodityCategory' in result))):
#                         logger.info(f"3DES decryption successful with {encoding} ({errors}): {len(result)} chars")
#                         return result
#                 except UnicodeDecodeError:
#                     continue
# 
#             # Final fallback - use latin-1 with replace
#             result = decrypted.decode('latin-1', errors='replace')
#             logger.warning(f"3DES decryption fallback: {len(result)} chars with replacements")
#             return result
# 
#         except Exception as e:
#             logger.error(f"3DES decryption failed: {e}")
#             raise Exception(f"3DES decryption failed: {e}")
#     # ============ SIGNATURE GENERATION ============
# 
#     def sign_content(self, content: str, private_key: rsa.RSAPrivateKey) -> str:
#         """Sign with explicit no-linebreak base64"""
#         try:
#             content_bytes = content.encode('utf-8')
# 
#             signature = private_key.sign(
#                 content_bytes,
#                 rsa_padding.PKCS1v15(),
#                 hashes.SHA1()
#             )
# 
#             # Ensure no line breaks in base64
#             signature_b64 = base64.b64encode(signature).decode('ascii').replace('\n', '').replace('\r', '')
# 
#             logger.info(f"Signature (no linebreaks): {len(signature_b64)} chars")
#             logger.debug(f"Signature sample: {signature_b64[:50]}...{signature_b64[-20:]}")
# 
#             return signature_b64
# 
#         except Exception as e:
#             logger.error(f"Signature failed: {e}")
#             raise
# 
#     def sign_content_v2(self, content: str, private_key: rsa.RSAPrivateKey) -> str:
#         """
#         Alternative signature with SHA256 (instead of SHA1)
#         """
#         try:
#             content_bytes = content.encode('utf-8')
# 
#             # Try SHA256 instead of SHA1
#             signature = private_key.sign(
#                 content_bytes,
#                 rsa_padding.PKCS1v15(),
#                 hashes.SHA256()  # Changed from SHA1
#             )
# 
#             signature_b64 = base64.b64encode(signature).decode('utf-8')
#             logger.info(f"Signature generated with SHA256: {len(signature_b64)} chars")
# 
#             return signature_b64
# 
#         except Exception as e:
#             logger.error(f"Signature generation failed: {e}")
#             raise
# 
#     def sign_content_v3(self, content: str, private_key: rsa.RSAPrivateKey) -> str:
#         """
#         Alternative with base64 encode BEFORE signing (double encoding)
#         Some systems expect this
#         """
#         try:
#             # Encode content to base64 first
#             content_b64 = base64.b64encode(content.encode('utf-8'))
# 
#             # Sign the base64 string
#             signature = private_key.sign(
#                 content_b64,
#                 rsa_padding.PKCS1v15(),
#                 hashes.SHA1()
#             )
# 
#             signature_b64 = base64.b64encode(signature).decode('utf-8')
#             logger.info(f"Signature (base64 input) with SHA1: {len(signature_b64)} chars")
# 
#             return signature_b64
# 
#         except Exception as e:
#             logger.error(f"Signature generation failed: {e}")
#             raise
# 
#     def create_signed_encrypted_request(self, interface_code: str, content: Dict,
#                                         private_key: rsa.RSAPrivateKey) -> Dict:
#         """
#         Create EFRIS request per documentation:
#         1. Serialize JSON
#         2. Encrypt with AES → base64 string
#         3. Sign the base64 encrypted string with RSA
#         FIXED: Set encryptCode to "2" for AES
#         """
#         try:
#             aes_key = self.get_current_aes_key()
#             if not aes_key:
#                 raise Exception("No valid AES key available")
# 
#             # 1. Serialize content
#             content_json = json.dumps(content, separators=(',', ':'), ensure_ascii=False, sort_keys=True)
#             logger.debug(f"Content JSON length: {len(content_json)}")
# 
#             # 2. Encrypt and base64 encode (step 5-6 from docs)
#             encrypted_content = self.encrypt_with_aes(content_json, aes_key)
#             logger.debug(f"Encrypted content length: {len(encrypted_content)}")
# 
#             # 3. Sign the encrypted base64 string (step 7 from docs)
#             signature = self.sign_content(encrypted_content, private_key)
#             logger.debug(f"Generated signature length: {len(signature)}")
# 
#             # 4. Build request envelope (step 8 from docs)
#             request = {
#                 "data": {
#                     "content": encrypted_content,
#                     "signature": signature,
#                     "dataDescription": {
#                         "codeType": "1",
#                         "encryptCode": "2",  # FIXED: 2 for AES
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
# 
#     def test_encryption_roundtrip(self) -> dict:
#         """
#         Test encryption/decryption round-trip with current key
#         Returns detailed test results
#         """
#         aes_key = self.get_current_aes_key()
#         if not aes_key:
#             return {
#                 'success': False,
#                 'error': 'No AES key available'
#             }
# 
#         test_data = {
#             'test': 'hello',
#             'value': 123,
#             'nested': {'key': 'value'}
#         }
#         test_json = json.dumps(test_data, separators=(',', ':'))
# 
#         logger.info("Starting encryption round-trip test")
# 
#         try:
#             # Test encryption
#             encrypted = self.encrypt_with_aes(test_json, aes_key)
#             logger.info(f"Test encryption successful: {len(encrypted)} chars")
# 
#             # Test decryption
#             decrypted = self.decrypt_with_aes(encrypted, aes_key)
#             logger.info(f"Test decryption successful: {len(decrypted)} chars")
# 
#             # Verify match
#             success = decrypted == test_json
# 
#             result = {
#                 'success': success,
#                 'algorithm': self._encryption_algorithm,
#                 'key_length': len(aes_key),
#                 'original_length': len(test_json),
#                 'encrypted_length': len(encrypted),
#                 'decrypted_length': len(decrypted),
#                 'match': success
#             }
# 
#             if not success:
#                 result['original'] = test_json
#                 result['decrypted'] = decrypted
#                 logger.error("Round-trip test FAILED - data mismatch")
#             else:
#                 logger.info("Round-trip test PASSED")
# 
#             return result
# 
#         except Exception as e:
#             logger.error(f"Round-trip test failed: {e}", exc_info=True)
#             return {
#                 'success': False,
#                 'error': str(e)
#             }
# 
#     def run_comprehensive_diagnostics(self) -> dict:
#         """Run comprehensive encryption diagnostics"""
#         aes_key = self.get_current_aes_key()
# 
#         if not aes_key:
#             return {'error': 'No AES key available'}
# 
#         logger.info("Running comprehensive encryption diagnostics")
# 
#         # Key analysis
#         key_analysis = EncryptionDebugger.analyze_key(aes_key)
# 
#         # Algorithm tests
#         test_content = '{"test":"data"}'
#         algorithm_tests = EncryptionDebugger.test_encryption_algorithms(test_content, aes_key)
# 
#         # Round-trip test
#         roundtrip_result = self.test_encryption_roundtrip()
# 
#         diagnostics = {
#             'key_analysis': key_analysis,
#             'algorithm_tests': algorithm_tests,
#             'roundtrip_test': roundtrip_result,
#             'current_algorithm': self._encryption_algorithm,
#             'timestamp': timezone.now().isoformat()
#         }
# 
#         logger.info("Diagnostics complete", summary=diagnostics)
# 
#         return diagnostics
# 
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
#             logger.debug(f"Decrypted key (repr): {repr(decrypted)}")
# 
#             # CRITICAL FIX: The decrypted result is base64-encoded!
#             if decrypted.endswith(b'==') or decrypted.endswith(b'='):
#                 logger.debug("Detected base64-encoded key, decoding...")
#                 aes_key_bytes = base64.b64decode(decrypted)
#                 logger.debug(f"After base64 decode: {len(aes_key_bytes)} bytes")
#             else:
#                 aes_key_bytes = decrypted
# 
#             return aes_key_bytes
# 
#         except Exception as e:
#             logger.error(f"RSA decryption failed: {e}")
#             raise Exception(f"AES key decryption failed: {e}")
# 
#     def process_t104_response(self, response_data: dict, private_key) -> dict:
#         """Process T104 response and extract AES key"""
#         try:
#             content = response_data.get("content", "")
#             if not content:
#                 return {"success": False, "error": "No content in T104 response"}
# 
#             # Decode content
#             decoded_content = base64.b64decode(content).decode("utf-8")
#             content_data = json.loads(decoded_content)
# 
#             # Get encrypted AES key (handle typo)
#             encrypted_aes_key = (
#                     content_data.get("passowrdDes") or
#                     content_data.get("passwordDes") or
#                     content_data.get("password")
#             )
# 
#             if not encrypted_aes_key:
#                 return {"success": False, "error": "No encrypted key in response"}
# 
#             # Decrypt AES key
#             aes_key_bytes = self.decrypt_aes_key(encrypted_aes_key, private_key)
# 
#             # Store and analyze
#             self.set_current_aes_key(aes_key_bytes)
# 
#             # Run diagnostics
#             diagnostics = self.run_comprehensive_diagnostics()
# 
#             return {
#                 "success": True,
#                 "aes_key": aes_key_bytes,
#                 "diagnostics": diagnostics
#             }
# 
#         except Exception as e:
#             logger.error(f"T104 processing failed: {e}", exc_info=True)
#             return {"success": False, "error": str(e)}
# 
#     # ============ EFRIS REQUEST HELPERS ============
# 
#     def create_global_info(self, interface_code: str) -> dict:
#         """Create globalInfo section for EFRIS requests"""
#         import uuid
#         import pytz
# 
#         utc_time = datetime.now(pytz.UTC)
#         utc_plus_3 = utc_time + timedelta(hours=3)
#         request_time = utc_plus_3.strftime('%Y-%m-%d %H:%M:%S')
# 
#         return {
#             "appId": self.app_id,
#             "version": "1.1.20191201",
#             "dataExchangeId": str(uuid.uuid4()).replace('-', '')[:32],
#             "interfaceCode": interface_code,
#             "requestCode": "TP",
#             "requestTime": request_time,
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
# class EnhancedHTTPClient:
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
#         """
#         FIXED: Build goods details with correct itemCode and goodsCategoryId
#         Use proper HS code for water: 22011000
#         """
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
#                     # FIXED: Use proper category for water - 22011000 for mineral waters
#                     commodity_category_id = (
#                             getattr(product, 'efris_commodity_category_id', None) or
#                             (getattr(product.category, 'efris_commodity_category_id', None)
#                              if hasattr(product, 'category') and product.category else None) or
#                             '22011000'  # HS code for bottled water
#                     )
# 
#                     # FIXED: Make itemCode match category format, e.g., category + suffix
#                     item_code = getattr(product, 'efris_item_code', None)
#                     if not item_code:
#                         # Generate matching code
#                         item_code = f"{commodity_category_id}-{getattr(product, 'sku', f'ITEM{product.id}')[:10]}"
# 
#                     # Get amounts
#                     quantity = float(getattr(item, 'quantity', 1))
#                     unit_price = float(getattr(item, 'unit_price', 0) or getattr(item, 'price', 0))
#                     line_total = quantity * unit_price
# 
#                     # Tax calculation
#                     tax_rate_raw = getattr(item, 'tax_rate', 'A')
#                     tax_rate = self.get_numeric_tax_rate(tax_rate_raw)
# 
#                     # Calculate tax from net amount
#                     net_amount = line_total / (1 + tax_rate / 100)
#                     tax_amount = line_total - net_amount
# 
#                     goods_detail = {
#                         "item": product.name[:200],
#                         "itemCode": item_code,  # FIXED: Match category
#                         "qty": f"{quantity:.2f}",
#                         "unitOfMeasure": getattr(product, 'efris_unit_of_measure_code', 'U'),
#                         "unitPrice": f"{unit_price:.2f}",
#                         "total": f"{line_total:.2f}",
#                         "taxRate": f"{tax_rate / 100:.4f}",  # As decimal (0.18 for 18%)
#                         "tax": f"{tax_amount:.2f}",
#                         "orderNumber": str(idx),
#                         "discountFlag": "2",  # 2=No discount
#                         "discountTotal": "0.00",
#                         "deemedFlag": "2",  # 2=Not deemed
#                         "exciseFlag": "2",  # 2=No excise
#                         "categoryId": "",
#                         "categoryName": "",
#                         "goodsCategoryId": str(commodity_category_id),  # FIXED: Proper HS code
#                         "goodsCategoryName": getattr(product, 'efris_commodity_category_name', 'Mineral Water'),
#                         "exciseCurrency": "",
#                         "exciseTax": "",
#                         "pack": "",
#                         "stick": "",
#                         "exciseUnit": "",
#                         "exciseDutyCode": ""
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
#                         "itemCode": f"22011000-{idx}",  # FIXED: Use HS code base
#                         "qty": f"{float(getattr(item, 'quantity', 1)):.2f}",
#                         "unitOfMeasure": "U",
#                         "unitPrice": f"{float(getattr(item, 'unit_price', 0)):.2f}",
#                         "total": f"{float(getattr(item, 'quantity', 1)) * float(getattr(item, 'unit_price', 0)):.2f}",
#                         "taxRate": "0.18",
#                         "tax": f"{float(getattr(item, 'quantity', 1)) * float(getattr(item, 'unit_price', 0)) * 0.18:.2f}",
#                         "orderNumber": str(idx),
#                         "discountFlag": "2",
#                         "discountTotal": "0.00",
#                         "deemedFlag": "2",
#                         "exciseFlag": "2",
#                         "goodsCategoryId": "22011000",
#                         "goodsCategoryName": "Mineral Water",
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
# class EnhancedEFRISAPIClient:
#     def __init__(self, company):
#         self.company = company
# 
#         # Get EFRIS configuration safely
#         try:
#             self.efris_config = company.efris_config
#         except AttributeError:
#             raise EFRISConfigurationError("Company does not have EFRIS configuration")
# 
#         # Initialize SecurityManager with device number and TIN
#         device_no = self.efris_config.device_number or '1026925503_01'
#         tin = getattr(company, 'tin', '') or ''
#         self.security_manager = SecurityManager(device_no, tin)
# 
#         # Configuration manager and API config
#         self.config_manager = ConfigurationManager(company)
#         self.config = self.config_manager.get_api_config()
# 
#         # HTTP client and data transformer
#         self.http_client = EnhancedHTTPClient(self.config)
#         self.data_transformer = EFRISDataTransformer(company)
# 
#         # Session management
#         self._is_authenticated = False
#         self._last_login = None
#         self._last_auth_error = None
# 
#         # Device initialization check
#         self._device_initialized = self._check_device_initialization()
# 
#     def __enter__(self):
#         return self
# 
#     def __exit__(self, exc_type, exc_val, exc_tb):
#         self.close()
# 
#     def close(self):
#         self.http_client.close()
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
#             with self.security_manager._t104_lock:
#                 # Check if we already have valid AES key
#                 if self.security_manager.is_aes_key_valid():
#                     logger.debug("Another worker got key, using cached")
#                     return {"success": True, "message": "Using cached key"}
# 
#                 request_data = {
#                     "data": {
#                         "content": "",
#                         "signature": "",
#                         "dataDescription": {"codeType": "0", "encryptCode": "0", "zipCode": "0"}
#                     },
#                     "globalInfo": self.security_manager.create_global_info("T104"),
#                     "returnStateInfo": {"returnCode": "", "returnMessage": ""}
#                 }
# 
#                 response = self._make_http_request(request_data)
#                 if response.status_code != 200:
#                     return {"success": False, "error": f"HTTP {response.status_code}"}
# 
#                 response_data = response.json()
#                 return_info = response_data.get('returnStateInfo', {})
#                 return_code = return_info.get('returnCode', '99')
# 
#                 if return_code == '00':
#                     data_section = response_data.get('data', {})
#                     private_key = self._load_private_key()
#                     key_result = self.security_manager.process_t104_response(data_section, private_key)
# 
#                     if key_result.get("success"):
#                         logger.info("T104 AES key obtained and cached")
#                         return {"success": True, "aes_key": key_result["aes_key"]}
#                     else:
#                         error = key_result.get("error", "Failed to process AES key")
#                         logger.error(f"T104 key processing failed: {error}")
#                         return {"success": False, "error": error}
#                 else:
#                     error_message = return_info.get('returnMessage', 'T104 failed')
#                     logger.error(f"T104 failed: {error_message}")
#                     return {"success": False, "error": error_message}
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
#     def query_all_commodity_categories_fixed(self) -> Dict[str, Any]:
#         """T123 - Query categories with comprehensive format handling"""
#         import gzip
#         import zipfile
#         import io
# 
#         try:
#             self.ensure_authenticated()
#             private_key = self._load_private_key()
# 
#             request_data = self.security_manager.create_signed_encrypted_request(
#                 "T123", {}, private_key
#             )
# 
#             logger.info("Querying all commodity categories (T123) with comprehensive format handling")
#             response = self._make_http_request(request_data)
# 
#             if response.status_code != 200:
#                 return {"success": False, "error": f"HTTP {response.status_code}", "categories": []}
# 
#             response_data = response.json()
#             return_info = response_data.get('returnStateInfo', {})
#             return_code = return_info.get('returnCode', '99')
# 
#             if return_code == '00':
#                 data_section = response_data.get('data', {})
#                 data_description = data_section.get('dataDescription', {})
#                 content_b64 = data_section.get('content', '')
# 
#                 logger.info(
#                     f"T123 zipCode: {data_description.get('zipCode')}, encryptCode: {data_description.get('encryptCode')}")
# 
#                 if not content_b64:
#                     return {"success": True, "categories": []}
# 
#                 # Step 1: Base64 decode
#                 decoded_bytes = base64.b64decode(content_b64)
#                 logger.info(f"Base64 decoded: {len(decoded_bytes)} bytes")
# 
#                 # Step 2: Handle compression
#                 decompressed_bytes = decoded_bytes
#                 if data_description.get('zipCode') == '1':
#                     logger.info("Decompressing response...")
#                     try:
#                         decompressed_bytes = gzip.decompress(decoded_bytes)
#                         logger.info(f"Gzip decompression successful: {len(decompressed_bytes)} bytes")
#                     except gzip.BadGzipFile:
#                         logger.warning("Gzip decompression failed, trying zlib...")
#                         try:
#                             import zlib
#                             decompressed_bytes = zlib.decompress(decoded_bytes)
#                             logger.info(f"Zlib decompression successful: {len(decompressed_bytes)} bytes")
#                         except Exception as e:
#                             logger.error(f"All decompression methods failed: {e}")
#                             return {"success": False, "error": f"Decompression failed: {e}", "categories": []}
# 
#                 # Step 3: 3DES Decryption
#                 aes_key = self.security_manager.get_current_aes_key()
#                 if not aes_key:
#                     return {"success": False, "error": "No AES key available", "categories": []}
# 
#                 # Convert to base64 for decryption function
#                 encrypted_b64 = base64.b64encode(decompressed_bytes).decode('utf-8')
# 
#                 logger.info("Using 3DES decryption for T123 response...")
#                 decrypted_content = self.security_manager.decrypt_with_3des(encrypted_b64, aes_key)
# 
#                 logger.info(f"3DES decryption completed: {len(decrypted_content)} chars")
# 
#                 # Step 4: Analyze the decrypted content
#                 analysis = self.analyze_decrypted_content(decrypted_content)
#                 logger.info(f"Content analysis: {analysis}")
# 
#                 # Step 5: Handle different content formats
#                 categories_data = None
# 
#                 # Try different parsing strategies based on content analysis
#                 if analysis['likely_format'] == 'json':
#                     categories_data = self._parse_as_json(decrypted_content)
#                 elif analysis['contains_binary']:
#                     categories_data = self._handle_binary_content(decrypted_content)
#                 else:
#                     # Try all methods
#                     categories_data = self._parse_as_json(decrypted_content)
#                     if not categories_data:
#                         categories_data = self._handle_binary_content(decrypted_content)
# 
#                 if categories_data:
#                     categories = self._extract_categories_from_response(categories_data)
#                     logger.info(f"T123 successful: {len(categories)} categories retrieved")
#                     return {"success": True, "categories": categories}
#                 else:
#                     logger.error("All parsing methods failed")
#                     # Save for detailed analysis
#                     self._save_debug_data(decrypted_content, "t123_decrypted_raw")
#                     return {"success": False, "error": "All parsing methods failed", "categories": []}
# 
#             else:
#                 error_message = return_info.get('returnMessage', 'T123 failed')
#                 logger.error(f"T123 failed: {return_code} - {error_message}")
#                 return {"success": False, "error": error_message, "categories": []}
# 
#         except Exception as e:
#             logger.error(f"T123 query failed: {e}", exc_info=True)
#             return {"success": False, "error": str(e), "categories": []}
# 
#     def _parse_as_json(self, content: str) -> Optional[Dict]:
#         """Parse content as JSON with multiple strategies"""
#         strategies = [
#             self._parse_json_direct,
#             self._parse_json_extract,
#             self._parse_json_clean,
#             self._parse_json_find_structure
#         ]
# 
#         for strategy in strategies:
#             try:
#                 result = strategy(content)
#                 if result:
#                     logger.info(f"✅ JSON parsing successful with {strategy.__name__}")
#                     return result
#             except Exception as e:
#                 logger.debug(f"JSON strategy {strategy.__name__} failed: {e}")
#                 continue
# 
#         return None
# 
#     def _parse_json_direct(self, content: str) -> Optional[Dict]:
#         """Direct JSON parsing"""
#         try:
#             logger.debug(f"JSON strategy _parse_json_direct failed: Expecting value: line 1 column 1 (char 0)")
#             return json.loads(content)
#         except:
#             return None
# 
#     def _parse_json_extract(self, content: str) -> Optional[Dict]:
#         """Extract JSON from surrounding content"""
#         import re
# 
#         # Look for complete JSON objects
#         json_patterns = [
#             r'\{[^{}]*"[^{}]*"[^{}]*\}',  # Nested objects
#             r'\[[^\[\]]*\{[^\[\]]*\}[^\[\]]*?\]',  # Arrays with objects
#         ]
# 
#         for pattern in json_patterns:
#             matches = re.findall(pattern, content, re.DOTALL)
#             for match in matches:
#                 try:
#                     if len(match) > 100:  # Reasonable minimum size
#                         return json.loads(match)
#                 except:
#                     continue
#         return None
# 
#     def _parse_json_clean(self, content: str) -> Optional[Dict]:
#         """Clean content and try JSON parsing"""
#         # Remove null bytes and control characters
#         cleaned = ''.join(char for char in content if ord(char) >= 32 or char in '\r\n\t')
#         cleaned = cleaned.strip()
# 
#         # Remove any non-JSON prefixes/suffixes
#         lines = cleaned.split('\n')
#         json_lines = []
#         in_json = False
# 
#         for line in lines:
#             line = line.strip()
#             if line.startswith(('{', '[')):
#                 in_json = True
#             if in_json:
#                 json_lines.append(line)
#             if line.endswith(('}', ']')):
#                 break
# 
#         if json_lines:
#             try:
#                 return json.loads(''.join(json_lines))
#             except:
#                 pass
# 
#         return None
# 
#     def _parse_json_find_structure(self, content: str) -> Optional[Dict]:
#         """Find and parse the main data structure"""
#         # Look for common EFRIS response patterns
#         patterns = [
#             r'"data"\s*:\s*(\{[^}]+\})',
#             r'"records"\s*:\s*(\[[^]]+\])',
#             r'"commodityCategoryList"\s*:\s*(\[[^]]+\])',
#             r'"list"\s*:\s*(\[[^]]+\])'
#         ]
# 
#         for pattern in patterns:
#             match = re.search(pattern, content)
#             if match:
#                 try:
#                     return json.loads(match.group(1))
#                 except:
#                     continue
#         return None
# 
#     def _handle_binary_content(self, content: str) -> Optional[Dict]:
#         """Handle potentially binary or multi-format content"""
#         try:
#             # Convert string back to bytes for binary processing
#             content_bytes = content.encode('latin-1')
# 
#             # Check if it's a ZIP file
#             if content_bytes.startswith(b'PK'):
#                 logger.info("Content appears to be ZIP format, attempting extraction...")
#                 return self._extract_zip_content(content_bytes)
# 
#             # Check if it's another compressed format
#             if content_bytes.startswith(b'\x1f\x8b'):  # Gzip magic number
#                 logger.info("Content appears to be gzipped, decompressing...")
#                 try:
#                     decompressed = gzip.decompress(content_bytes)
#                     return self._parse_as_json(decompressed.decode('utf-8'))
#                 except:
#                     pass
# 
#             # Try to decode as UTF-8 with BOM
#             if content_bytes.startswith(b'\xef\xbb\xbf'):
#                 try:
#                     decoded = content_bytes.decode('utf-8-sig')
#                     return self._parse_as_json(decoded)
#                 except:
#                     pass
# 
#             # Try to find text segments in binary data
#             text_segments = re.findall(b'[\\x20-\\x7E\\r\\n\\t]{100,}', content_bytes)
#             for segment in text_segments:
#                 try:
#                     decoded = segment.decode('utf-8')
#                     parsed = self._parse_as_json(decoded)
#                     if parsed:
#                         return parsed
#                 except:
#                     continue
# 
#             return None
# 
#         except Exception as e:
#             logger.error(f"Binary content handling failed: {e}")
#             return None
# 
#     def _extract_zip_content(self, zip_bytes: bytes) -> Optional[Dict]:
#         """Extract and parse content from ZIP file"""
#         try:
#             import zipfile
#             from io import BytesIO
# 
#             with zipfile.ZipFile(BytesIO(zip_bytes)) as zip_file:
#                 # Look for JSON files in the archive
#                 for file_info in zip_file.filelist:
#                     if file_info.filename.lower().endswith('.json'):
#                         with zip_file.open(file_info.filename) as json_file:
#                             content = json_file.read().decode('utf-8')
#                             return json.loads(content)
# 
#                 # If no JSON files, try to read any text file
#                 for file_info in zip_file.filelist:
#                     if file_info.file_size > 0:
#                         with zip_file.open(file_info.filename) as text_file:
#                             content = text_file.read().decode('utf-8', errors='ignore')
#                             parsed = self._parse_as_json(content)
#                             if parsed:
#                                 return parsed
# 
#             return None
#         except Exception as e:
#             logger.error(f"ZIP extraction failed: {e}")
#             return None
# 
#     def _extract_json_from_response(self, content: str) -> Optional[Dict]:
#         """Extract JSON from potentially malformed response"""
#         if not content:
#             return None
# 
#         # Method 1: Look for JSON object/array patterns
#         import re
# 
#         # Try to find JSON object
#         json_match = re.search(r'\{[^{}]*"[^{}]*"[^{}]*\}', content)
#         if json_match:
#             try:
#                 json_str = json_match.group()
#                 return json.loads(json_str)
#             except:
#                 pass
# 
#         # Method 2: Look for array pattern
#         array_match = re.search(r'\[[^\[\]]*\{[^\[\]]*\}[^\[\]]*?\]', content)
#         if array_match:
#             try:
#                 json_str = array_match.group()
#                 return json.loads(json_str)
#             except:
#                 pass
# 
#         # Method 3: Try to find the main data structure
#         lines = content.split('\n')
#         for line in lines:
#             line = line.strip()
#             if line.startswith('{') and line.endswith('}'):
#                 try:
#                     return json.loads(line)
#                 except:
#                     continue
#             elif line.startswith('[') and line.endswith(']'):
#                 try:
#                     return json.loads(line)
#                 except:
#                     continue
# 
#         return None
# 
#     def _save_debug_data(self, content: str, filename: str):
#         """Save debug data to file for analysis"""
#         try:
#             import os
#             debug_dir = "/tmp/efris_debug"
#             os.makedirs(debug_dir, exist_ok=True)
# 
#             filepath = os.path.join(debug_dir, f"{filename}.txt")
#             with open(filepath, 'w', encoding='utf-8') as f:
#                 f.write(content)
# 
#             logger.info(f"Debug data saved to: {filepath}")
# 
#             # Also save first and last 1000 chars for quick analysis
#             preview = f"First 1000 chars:\n{content[:1000]}\n\nLast 1000 chars:\n{content[-1000:]}"
#             preview_path = os.path.join(debug_dir, f"{filename}_preview.txt")
#             with open(preview_path, 'w', encoding='utf-8') as f:
#                 f.write(preview)
# 
#         except Exception as e:
#             logger.warning(f"Failed to save debug data: {e}")
# 
#     def update_system_dictionary(self, force_update: bool = False) -> Dict[str, Any]:
#         """
#         T115 - Update system dictionary
#         Downloads and caches system parameters from EFRIS
# 
#         Args:
#             force_update: Force update even if cached version is current
#         """
#         try:
#             # Check if update is needed
#             if not force_update and self._is_dictionary_current():
#                 logger.info("System dictionary is current, skipping update")
#                 return {
#                     "success": True,
#                     "message": "Dictionary already current",
#                     "cached": True
#                 }
# 
#             # Ensure authentication
#             auth_result = self.ensure_authenticated()
#             if not auth_result.get("success"):
#                 return {
#                     "success": False,
#                     "error": f"Authentication failed: {auth_result.get('error')}"
#                 }
# 
#             # Create T115 request
#             private_key = self._load_private_key()
#             request_data = self.security_manager.create_signed_encrypted_request(
#                 "T115", {}, private_key
#             )
# 
#             logger.info("Requesting system dictionary update (T115)")
#             response = self._make_http_request(request_data)
# 
#             if response.status_code != 200:
#                 return {
#                     "success": False,
#                     "error": f"HTTP {response.status_code}"
#                 }
# 
#             response_data = response.json()
#             return_info = response_data.get('returnStateInfo', {})
#             return_code = return_info.get('returnCode', '99')
# 
#             if return_code == '00':
#                 # Decrypt response
#                 data_section = response_data.get('data', {})
#                 decrypted_content = self._decrypt_response_content(data_section)
# 
#                 if decrypted_content:
#                     # Store dictionary data
#                     self._store_dictionary_data(decrypted_content)
# 
#                     logger.info("System dictionary updated successfully")
#                     return {
#                         "success": True,
#                         "message": "System dictionary updated",
#                         "data": decrypted_content,
#                         "cached": False
#                     }
#                 else:
#                     return {
#                         "success": False,
#                         "error": "Failed to decrypt dictionary response"
#                     }
#             else:
#                 error_message = return_info.get('returnMessage', 'T115 failed')
#                 logger.error(f"T115 failed: {return_code} - {error_message}")
#                 return {
#                     "success": False,
#                     "error": error_message,
#                     "error_code": return_code
#                 }
# 
#         except Exception as e:
#             logger.error(f"System dictionary update failed: {e}", exc_info=True)
#             return {
#                 "success": False,
#                 "error": str(e)
#             }
# 
#     def _is_dictionary_current(self) -> bool:
#         """Check if cached dictionary is still current"""
#         from django.core.cache import cache
# 
#         cache_key = f"efris_dict_version_{self.company.pk}"
#         cached_version = cache.get(cache_key)
# 
#         if not cached_version:
#             return False
# 
#         # Dictionary should be refreshed daily
#         cache_timestamp = cache.get(f"{cache_key}_timestamp")
#         if not cache_timestamp:
#             return False
# 
#         from django.utils import timezone
#         age_hours = (timezone.now() - cache_timestamp).total_seconds() / 3600
#         return age_hours < 24  # Refresh after 24 hours
# 
#     def _store_dictionary_data(self, data: Dict[str, Any]):
#         """Store dictionary data in database and cache"""
#         from django.core.cache import cache
#         from django.utils import timezone
# 
#         try:
#             # Store in EFRISSystemDictionary model
#             from efris.models import EFRISSystemDictionary
# 
#             EFRISSystemDictionary.objects.update_or_create(
#                 company=self.company,
#                 defaults={
#                     'data': data,
#                     'last_updated': timezone.now()
#                 }
#             )
# 
#             # Cache for quick access
#             cache_key = f"efris_system_dict_{self.company.pk}"
#             cache.set(cache_key, data, timeout=86400)  # 24 hours
# 
#             # Store version timestamp
#             cache.set(
#                 f"efris_dict_version_{self.company.pk}_timestamp",
#                 timezone.now(),
#                 timeout=86400
#             )
# 
#             logger.info("System dictionary stored successfully")
# 
#         except Exception as e:
#             logger.error(f"Failed to store system dictionary: {e}", exc_info=True)
# 
#     def get_dictionary_value(self, category: str, code: Optional[str] = None) -> Any:
#         """
#         Get value from cached system dictionary
# 
#         Args:
#             category: Dictionary category (e.g., 'payWay', 'currencyType')
#             code: Optional code to lookup specific value
#         """
#         from django.core.cache import cache
# 
#         cache_key = f"efris_system_dict_{self.company.pk}"
#         dictionary = cache.get(cache_key)
# 
#         if not dictionary:
#             # Try to load from database
#             try:
#                 from efris.models import EFRISSystemDictionary
#                 dict_obj = EFRISSystemDictionary.objects.filter(
#                     company=self.company
#                 ).first()
# 
#                 if dict_obj:
#                     dictionary = dict_obj.data
#                     cache.set(cache_key, dictionary, timeout=86400)
#             except Exception:
#                 pass
# 
#         if not dictionary:
#             return None
# 
#         category_data = dictionary.get(category)
# 
#         if not category_data:
#             return None
# 
#         # If no code specified, return entire category
#         if code is None:
#             return category_data
# 
#         # Search for specific code
#         if isinstance(category_data, list):
#             for item in category_data:
#                 if item.get('value') == code or item.get('code') == code:
#                     return item
#         elif isinstance(category_data, dict):
#             return category_data.get(code)
# 
#         return None
# 
# class ZReportService:
#     """Service for Z-Report Daily Upload (T116)"""
# 
#     def __init__(self, company):
#         self.company = company
#         self.client = EnhancedEFRISAPIClient(company)
# 
#     def upload_daily_zreport(self, report_date: date, report_data: Dict[str, Any]) -> Dict[str, Any]:
#         """
#         T116 - Upload daily Z-report to EFRIS
# 
#         Args:
#             report_date: Date of the Z-report
#             report_data: Z-report data structure
#         """
#         try:
#             # Validate report data
#             validation_errors = self._validate_zreport_data(report_data)
#             if validation_errors:
#                 return {
#                     "success": False,
#                     "error": f"Validation failed: {'; '.join(validation_errors)}"
#                 }
# 
#             # Ensure authentication
#             auth_result = self.client.ensure_authenticated()
#             if not auth_result.get("success"):
#                 return {
#                     "success": False,
#                     "error": f"Authentication failed: {auth_result.get('error')}"
#                 }
# 
#             # Build Z-report request
#             zreport_content = self._build_zreport_content(report_date, report_data)
# 
#             # Create encrypted request
#             private_key = self.client._load_private_key()
#             request_data = self.client.security_manager.create_signed_encrypted_request(
#                 "T116", zreport_content, private_key
#             )
# 
#             logger.info(f"Uploading Z-report for date: {report_date}")
#             response = self.client._make_http_request(request_data)
# 
#             if response.status_code != 200:
#                 return {
#                     "success": False,
#                     "error": f"HTTP {response.status_code}"
#                 }
# 
#             response_data = response.json()
#             return_info = response_data.get('returnStateInfo', {})
#             return_code = return_info.get('returnCode', '99')
# 
#             if return_code == '00':
#                 # Log successful upload
#                 self._log_zreport_upload(report_date, True)
# 
#                 logger.info(f"Z-report uploaded successfully for {report_date}")
#                 return {
#                     "success": True,
#                     "message": "Z-report uploaded successfully",
#                     "report_date": report_date.isoformat(),
#                     "data": response_data
#                 }
#             else:
#                 error_message = return_info.get('returnMessage', 'T116 failed')
#                 logger.error(f"T116 failed: {return_code} - {error_message}")
# 
#                 # Log failed upload
#                 self._log_zreport_upload(report_date, False, error_message)
# 
#                 return {
#                     "success": False,
#                     "error": error_message,
#                     "error_code": return_code
#                 }
# 
#         except Exception as e:
#             logger.error(f"Z-report upload failed: {e}", exc_info=True)
#             self._log_zreport_upload(report_date, False, str(e))
# 
#             return {
#                 "success": False,
#                 "error": str(e)
#             }
# 
#     def _validate_zreport_data(self, data: Dict[str, Any]) -> List[str]:
#         """Validate Z-report data structure"""
#         errors = []
# 
#         # Add validation based on EFRIS documentation
#         # Note: The documentation shows "To be determined" for T116 request structure
#         # Update this method when the actual structure is defined
# 
#         required_fields = ['reportDate', 'deviceNo', 'totalSales', 'totalTax']
# 
#         for field in required_fields:
#             if field not in data:
#                 errors.append(f"Missing required field: {field}")
# 
#         return errors
# 
#     def _build_zreport_content(self, report_date: date, report_data: Dict[str, Any]) -> Dict[str, Any]:
#         """
#         Build Z-report content structure
# 
#         Note: Update this structure based on final EFRIS T116 specification
#         """
#         device_no = self.client.security_manager.device_no
# 
#         return {
#             "reportDate": report_date.strftime('%Y-%m-%d'),
#             "deviceNo": device_no,
#             "reportData": report_data,
#             "summary": {
#                 "totalSales": str(report_data.get('totalSales', 0)),
#                 "totalTax": str(report_data.get('totalTax', 0)),
#                 "totalTransactions": str(report_data.get('totalTransactions', 0)),
#                 "totalCash": str(report_data.get('totalCash', 0)),
#                 "totalCard": str(report_data.get('totalCard', 0)),
#                 "totalMobileMoney": str(report_data.get('totalMobileMoney', 0))
#             }
#         }
# 
#     def _log_zreport_upload(self, report_date: date, success: bool, error: Optional[str] = None):
#         """Log Z-report upload attempt"""
#         try:
#             from efris.models import EFRISAPILog
#             from django.utils import timezone
# 
#             EFRISAPILog.objects.create(
#                 company=self.company,
#                 interface_code='T116',
#                 request_type='Z_REPORT_UPLOAD',
#                 status='SUCCESS' if success else 'FAILED',
#                 error_message=error,
#                 request_data={'report_date': report_date.isoformat()},
#                 created_at=timezone.now()
#             )
#         except Exception as e:
#             logger.warning(f"Failed to log Z-report upload: {e}")
# 
#     def generate_daily_zreport(self, report_date: date) -> Dict[str, Any]:
#         """
#         Generate Z-report from daily sales data
# 
#         Args:
#             report_date: Date to generate report for
#         """
#         from django_tenants.utils import schema_context
# 
#         try:
#             with schema_context(self.company.schema_name):
#                 # Import models inside tenant context
#                 from sales.models import Sale
#                 from django.db.models import Sum, Count
# 
#                 # Get all sales for the date
#                 sales = Sale.objects.filter(
#                     company=self.company,
#                     sale_date__date=report_date,
#                     is_fiscalized=True
#                 )
# 
#                 # Calculate totals
#                 aggregates = sales.aggregate(
#                     total_sales=Sum('total_amount'),
#                     total_tax=Sum('tax_amount'),
#                     total_transactions=Count('id'),
#                     total_cash=Sum('cash_amount'),
#                     total_card=Sum('card_amount'),
#                     total_mobile_money=Sum('mobile_money_amount')
#                 )
# 
#                 # Build report data
#                 report_data = {
#                     'totalSales': float(aggregates.get('total_sales') or 0),
#                     'totalTax': float(aggregates.get('total_tax') or 0),
#                     'totalTransactions': aggregates.get('total_transactions') or 0,
#                     'totalCash': float(aggregates.get('total_cash') or 0),
#                     'totalCard': float(aggregates.get('total_card') or 0),
#                     'totalMobileMoney': float(aggregates.get('total_mobile_money') or 0),
#                     'reportDate': report_date.isoformat()
#                 }
# 
#                 return {
#                     "success": True,
#                     "report_data": report_data
#                 }
# 
#         except Exception as e:
#             logger.error(f"Failed to generate Z-report: {e}", exc_info=True)
#             return {
#                 "success": False,
#                 "error": str(e)
#             }
# 
# def schedule_daily_dictionary_update(company):
#     """
#     Schedule daily system dictionary update
#     Can be called from a Celery task or cron job
#     """
#     try:
#         manager = SystemDictionaryManager(company)
#         result = manager.update_system_dictionary()
# 
#         logger.info(
#             f"Scheduled dictionary update completed for {company.name}",
#             success=result.get('success'),
#             cached=result.get('cached', False)
#         )
# 
#         return result
# 
#     except Exception as e:
#         logger.error(f"Scheduled dictionary update failed: {e}", exc_info=True)
#         return {"success": False, "error": str(e)}
# 
# def schedule_daily_zreport_upload(company, report_date: Optional[date] = None):
#     """
#     Schedule daily Z-report upload
#     Can be called from a Celery task or cron job
# 
#     Args:
#         company: Company object
#         report_date: Date to generate report for (defaults to yesterday)
#     """
#     from datetime import timedelta
# 
#     try:
#         if report_date is None:
#             # Default to yesterday
#             report_date = date.today() - timedelta(days=1)
# 
#         service = ZReportService(company)
# 
#         # Generate report from sales data
#         generation_result = service.generate_daily_zreport(report_date)
# 
#         if not generation_result.get('success'):
#             return {
#                 "success": False,
#                 "error": f"Report generation failed: {generation_result.get('error')}"
#             }
# 
#         # Upload to EFRIS
#         upload_result = service.upload_daily_zreport(
#             report_date,
#             generation_result['report_data']
#         )
# 
#         logger.info(
#             f"Scheduled Z-report upload completed for {company.name}",
#             report_date=report_date.isoformat(),
#             success=upload_result.get('success')
#         )
# 
#         return upload_result
# 
#     except Exception as e:
#         logger.error(f"Scheduled Z-report upload failed: {e}", exc_info=True)
#         return {"success": False, "error": str(e)}
# 
# class TaxpayerQueryService:
#     """Service for querying taxpayer information (T119)"""
# 
#     def __init__(self, company):
#         self.company = company
#         self.client = EnhancedEFRISAPIClient(company)
# 
#     def query_taxpayer_by_tin(
#             self,
#             tin: str,
#             nin_brn: Optional[str] = None
#     ) -> Dict[str, Any]:
#         """
#         T119 - Query taxpayer information by TIN or NIN/BRN
# 
#         Args:
#             tin: Tax Identification Number (required)
#             nin_brn: National ID Number or Business Registration Number (optional)
# 
#         Returns:
#             Dict containing taxpayer information or error details
#         """
#         try:
#             # Validate TIN format
#             is_valid, error = DataValidator.validate_tin(tin)
#             if not is_valid:
#                 return {
#                     "success": False,
#                     "error": f"Invalid TIN: {error}"
#                 }
# 
#             # Validate NIN/BRN if provided
#             if nin_brn:
#                 is_valid_brn, brn_error = DataValidator.validate_brn(nin_brn)
#                 if not is_valid_brn:
#                     logger.warning(f"Invalid NIN/BRN provided: {brn_error}")
#                     # Clear invalid NIN/BRN
#                     nin_brn = None
# 
#             # Ensure authentication
#             auth_result = self.client.ensure_authenticated()
#             if not auth_result.get("success"):
#                 return {
#                     "success": False,
#                     "error": f"Authentication failed: {auth_result.get('error')}"
#                 }
# 
#             # Build request content
#             content = {"tin": tin}
#             if nin_brn:
#                 content["ninBrn"] = nin_brn
# 
#             # Create encrypted request
#             private_key = self.client._load_private_key()
#             request_data = self.client.security_manager.create_signed_encrypted_request(
#                 "T119", content, private_key
#             )
# 
#             logger.info(f"Querying taxpayer information for TIN: {tin}")
#             response = self.client._make_http_request(request_data)
# 
#             if response.status_code != 200:
#                 return {
#                     "success": False,
#                     "error": f"HTTP {response.status_code}",
#                     "taxpayer": None
#                 }
# 
#             response_data = response.json()
#             return_info = response_data.get('returnStateInfo', {})
#             return_code = return_info.get('returnCode', '99')
# 
#             if return_code == '00':
#                 # Decrypt response
#                 data_section = response_data.get('data', {})
#                 decrypted_content = self.client._decrypt_response_content(data_section)
# 
#                 if decrypted_content and 'taxpayer' in decrypted_content:
#                     taxpayer_data = decrypted_content['taxpayer']
# 
#                     logger.info(
#                         f"Taxpayer query successful",
#                         tin=tin,
#                         business_name=taxpayer_data.get('businessName', 'N/A')
#                     )
# 
#                     return {
#                         "success": True,
#                         "taxpayer": self._normalize_taxpayer_data(taxpayer_data),
#                         "raw_data": taxpayer_data
#                     }
#                 else:
#                     return {
#                         "success": False,
#                         "error": "Failed to decrypt taxpayer response",
#                         "taxpayer": None
#                     }
#             else:
#                 error_message = return_info.get('returnMessage', 'T119 query failed')
#                 logger.warning(f"T119 failed: {return_code} - {error_message}")
# 
#                 return {
#                     "success": False,
#                     "error": error_message,
#                     "error_code": return_code,
#                     "taxpayer": None
#                 }
# 
#         except Exception as e:
#             logger.error(f"Taxpayer query failed: {e}", exc_info=True)
#             return {
#                 "success": False,
#                 "error": str(e),
#                 "taxpayer": None
#             }
# 
#     def _normalize_taxpayer_data(self, taxpayer: Dict[str, Any]) -> Dict[str, Any]:
#         """Normalize taxpayer data structure"""
#         return {
#             'tin': taxpayer.get('tin', ''),
#             'nin_brn': taxpayer.get('ninBrn', ''),
#             'legal_name': taxpayer.get('legalName', ''),
#             'business_name': taxpayer.get('businessName', ''),
#             'contact_number': taxpayer.get('contactNumber', ''),
#             'contact_email': taxpayer.get('contactEmail', ''),
#             'address': taxpayer.get('address', ''),
#             'taxpayer_type': taxpayer.get('taxpayerType', ''),
#             'taxpayer_type_name': self._get_taxpayer_type_name(
#                 taxpayer.get('taxpayerType', '')
#             ),
#             'government_tin': taxpayer.get('governmentTIN', '') == '1',
#             'is_individual': taxpayer.get('taxpayerType', '') == '201',
#             'is_non_individual': taxpayer.get('taxpayerType', '') == '202'
#         }
# 
#     def _get_taxpayer_type_name(self, taxpayer_type: str) -> str:
#         """Get human-readable taxpayer type name"""
#         types = {
#             '201': 'Individual',
#             '202': 'Non-Individual'
#         }
#         return types.get(taxpayer_type, 'Unknown')
# 
# class GoodsInquiryService:
#     """Service for querying goods/services (T127)"""
# 
#     def __init__(self, company):
#         self.company = company
#         self.client = EnhancedEFRISAPIClient(company)
# 
#     def query_goods(
#             self,
#             goods_code: Optional[str] = None,
#             goods_name: Optional[str] = None,
#             commodity_category_name: Optional[str] = None,
#             page_no: int = 1,
#             page_size: int = 10,
#             branch_id: Optional[str] = None,
#             service_mark: Optional[str] = None,
#             have_excise_tax: Optional[str] = None,
#             start_date: Optional[date] = None,
#             end_date: Optional[date] = None,
#             combine_keywords: Optional[str] = None,
#             goods_type_code: str = "101",
#             tin: Optional[str] = None,
#             query_type: str = "1"
#     ) -> Dict[str, Any]:
#         """
#         T127 - Query goods/services from EFRIS
# 
#         Args:
#             goods_code: Goods code to search for
#             goods_name: Goods name to search for
#             commodity_category_name: Category name filter
#             page_no: Page number (default: 1)
#             page_size: Results per page (max 100, default: 10)
#             branch_id: Branch ID filter
#             service_mark: Service mark (101:yes, 102:no)
#             have_excise_tax: Has excise tax (101:yes, 102:no)
#             start_date: Start date filter
#             end_date: End date filter
#             combine_keywords: Combined search (goodsCode or goodsName)
#             goods_type_code: Goods type (101: Non-fuel, 102: Fuel)
#             tin: TIN for agent goods query
#             query_type: Query type (1: Normal, 0: Agent)
# 
#         Returns:
#             Dict containing paginated goods list and metadata
#         """
#         try:
#             # Validate pagination
#             if page_size > 100:
#                 return {
#                     "success": False,
#                     "error": "Page size cannot exceed 100"
#                 }
# 
#             # Validate query type
#             if query_type not in ['0', '1']:
#                 return {
#                     "success": False,
#                     "error": "Query type must be '0' (agent) or '1' (normal)"
#                 }
# 
#             # Validate agent query requirements
#             if query_type == '0':
#                 if not tin or not branch_id:
#                     return {
#                         "success": False,
#                         "error": "TIN and branch ID required for agent goods query"
#                     }
# 
#             # Ensure authentication
#             auth_result = self.client.ensure_authenticated()
#             if not auth_result.get("success"):
#                 return {
#                     "success": False,
#                     "error": f"Authentication failed: {auth_result.get('error')}"
#                 }
# 
#             # Build request content
#             content = self._build_query_content(
#                 goods_code=goods_code,
#                 goods_name=goods_name,
#                 commodity_category_name=commodity_category_name,
#                 page_no=page_no,
#                 page_size=page_size,
#                 branch_id=branch_id,
#                 service_mark=service_mark,
#                 have_excise_tax=have_excise_tax,
#                 start_date=start_date,
#                 end_date=end_date,
#                 combine_keywords=combine_keywords,
#                 goods_type_code=goods_type_code,
#                 tin=tin,
#                 query_type=query_type
#             )
# 
#             # Create encrypted request
#             private_key = self.client._load_private_key()
#             request_data = self.client.security_manager.create_signed_encrypted_request(
#                 "T127", content, private_key
#             )
# 
#             logger.info(f"Querying goods (page {page_no}, size {page_size})")
#             response = self.client._make_http_request(request_data)
# 
#             if response.status_code != 200:
#                 return {
#                     "success": False,
#                     "error": f"HTTP {response.status_code}",
#                     "goods": []
#                 }
# 
#             response_data = response.json()
#             return_info = response_data.get('returnStateInfo', {})
#             return_code = return_info.get('returnCode', '99')
# 
#             if return_code == '00':
#                 # Decrypt response
#                 data_section = response_data.get('data', {})
#                 decrypted_content = self.client._decrypt_response_content(data_section)
# 
#                 if decrypted_content:
#                     goods_list = decrypted_content.get('records', [])
#                     pagination = decrypted_content.get('page', {})
# 
#                     logger.info(
#                         f"Goods query successful: {len(goods_list)} items",
#                         page=pagination.get('pageNo'),
#                         total=pagination.get('totalSize')
#                     )
# 
#                     return {
#                         "success": True,
#                         "goods": [self._normalize_goods_data(g) for g in goods_list],
#                         "pagination": {
#                             "page_no": int(pagination.get('pageNo', page_no)),
#                             "page_size": int(pagination.get('pageSize', page_size)),
#                             "total_size": int(pagination.get('totalSize', 0)),
#                             "page_count": int(pagination.get('pageCount', 0))
#                         },
#                         "raw_data": decrypted_content
#                     }
#                 else:
#                     return {
#                         "success": False,
#                         "error": "Failed to decrypt goods response",
#                         "goods": []
#                     }
#             else:
#                 error_message = return_info.get('returnMessage', 'T127 query failed')
#                 logger.warning(f"T127 failed: {return_code} - {error_message}")
# 
#                 return {
#                     "success": False,
#                     "error": error_message,
#                     "error_code": return_code,
#                     "goods": []
#                 }
# 
#         except Exception as e:
#             logger.error(f"Goods query failed: {e}", exc_info=True)
#             return {
#                 "success": False,
#                 "error": str(e),
#                 "goods": []
#             }
# 
#     def _build_query_content(self, **kwargs) -> Dict[str, Any]:
#         """Build T127 query content from parameters"""
#         content = {
#             "pageNo": str(kwargs['page_no']),
#             "pageSize": str(kwargs['page_size'])
#         }
# 
#         # Add optional fields
#         if kwargs.get('goods_code'):
#             content['goodsCode'] = kwargs['goods_code']
# 
#         if kwargs.get('goods_name'):
#             content['goodsName'] = kwargs['goods_name']
# 
#         if kwargs.get('commodity_category_name'):
#             content['commodityCategoryName'] = kwargs['commodity_category_name']
# 
#         if kwargs.get('branch_id'):
#             content['branchId'] = kwargs['branch_id']
# 
#         if kwargs.get('service_mark'):
#             content['serviceMark'] = kwargs['service_mark']
# 
#         if kwargs.get('have_excise_tax'):
#             content['haveExciseTax'] = kwargs['have_excise_tax']
# 
#         if kwargs.get('start_date'):
#             content['startDate'] = kwargs['start_date'].strftime('%Y-%m-%d')
# 
#         if kwargs.get('end_date'):
#             content['endDate'] = kwargs['end_date'].strftime('%Y-%m-%d')
# 
#         if kwargs.get('combine_keywords'):
#             content['combineKeywords'] = kwargs['combine_keywords']
# 
#         if kwargs.get('goods_type_code'):
#             content['goodsTypeCode'] = kwargs['goods_type_code']
# 
#         if kwargs.get('tin'):
#             content['tin'] = kwargs['tin']
# 
#         if kwargs.get('query_type'):
#             content['queryType'] = kwargs['query_type']
# 
#         return content
# 
#     def _normalize_goods_data(self, goods: Dict[str, Any]) -> Dict[str, Any]:
#         """Normalize goods data structure"""
#         normalized = {
#             'id': goods.get('id', ''),
#             'goods_name': goods.get('goodsName', ''),
#             'goods_code': goods.get('goodsCode', ''),
#             'measure_unit': goods.get('measureUnit', ''),
#             'unit_price': float(goods.get('unitPrice', 0)),
#             'currency': goods.get('currency', ''),
#             'stock': float(goods.get('stock', 0)),
#             'stock_prewarning': float(goods.get('stockPrewarning', 0)),
#             'source': goods.get('source', ''),
#             'status_code': goods.get('statusCode', ''),
#             'commodity_category_code': goods.get('commodityCategoryCode', ''),
#             'commodity_category_name': goods.get('commodityCategoryName', ''),
#             'tax_rate': float(goods.get('taxRate', 0)),
#             'is_zero_rate': goods.get('isZeroRate', '') == '101',
#             'is_exempt': goods.get('isExempt', '') == '101',
#             'have_excise_tax': goods.get('haveExciseTax', '') == '101',
#             'excise_duty_code': goods.get('exciseDutyCode', ''),
#             'excise_duty_name': goods.get('exciseDutyName', ''),
#             'excise_rate': float(goods.get('exciseRate', 0)) if goods.get('exciseRate') else 0,
#             'pack': int(goods.get('pack', 0)) if goods.get('pack') else 0,
#             'stick': int(goods.get('stick', 0)) if goods.get('stick') else 0,
#             'remarks': goods.get('remarks', ''),
#             'have_piece_unit': goods.get('havePieceUnit', '') == '101',
#             'piece_unit_price': float(goods.get('pieceUnitPrice', 0)) if goods.get('pieceUnitPrice') else 0,
#             'piece_measure_unit': goods.get('pieceMeasureUnit', ''),
#             'package_scaled_value': float(goods.get('packageScaledValue', 0)) if goods.get('packageScaledValue') else 0,
#             'piece_scaled_value': float(goods.get('pieceScaledValue', 0)) if goods.get('pieceScaledValue') else 0,
#             'exclusion': goods.get('exclusion', ''),
#             'have_other_unit': goods.get('haveOtherUnit', '') == '101',
#             'service_mark': goods.get('serviceMark', ''),
#             'goods_type_code': goods.get('goodsTypeCode', ''),
#             'update_date': goods.get('updateDateStr', ''),
#             'tank_no': goods.get('tankNo', '')
#         }
# 
#         # Add customs information if present
#         customs_entity = goods.get('commodityGoodsExtendEntity')
#         if customs_entity:
#             normalized['customs_info'] = {
#                 'measure_unit': customs_entity.get('customsMeasureUnit', ''),
#                 'unit_price': float(customs_entity.get('customsUnitPrice', 0)) if customs_entity.get(
#                     'customsUnitPrice') else 0,
#                 'package_scaled_value': float(customs_entity.get('packageScaledValueCustoms', 0)) if customs_entity.get(
#                     'packageScaledValueCustoms') else 0,
#                 'scaled_value': float(customs_entity.get('customsScaledValue', 0)) if customs_entity.get(
#                     'customsScaledValue') else 0
#             }
# 
#         # Add other units if present
#         other_units = goods.get('goodsOtherUnits', [])
#         if other_units:
#             normalized['other_units'] = [
#                 {
#                     'id': unit.get('id', ''),
#                     'other_unit': unit.get('otherUnit', ''),
#                     'other_price': float(unit.get('otherPrice', 0)) if unit.get('otherPrice') else 0,
#                     'other_scaled': float(unit.get('otherScaled', 0)) if unit.get('otherScaled') else 0,
#                     'package_scaled': float(unit.get('packageScaled', 0)) if unit.get('packageScaled') else 0
#                 }
#                 for unit in other_units
#             ]
# 
#         return normalized
# 
#     def search_goods_by_keywords(
#             self,
#             keywords: str,
#             page_no: int = 1,
#             page_size: int = 10
#     ) -> Dict[str, Any]:
#         """
#         Convenience method to search goods by combined keywords
# 
#         Args:
#             keywords: Search keywords (searches goodsCode or goodsName)
#             page_no: Page number
#             page_size: Results per page
#         """
#         return self.query_goods(
#             combine_keywords=keywords,
#             page_no=page_no,
#             page_size=page_size
#         )
# 
#     def get_goods_by_code(self, goods_code: str) -> Dict[str, Any]:
#         """
#         Convenience method to get specific goods by code
# 
#         Args:
#             goods_code: Goods code to retrieve
#         """
#         result = self.query_goods(
#             goods_code=goods_code,
#             page_size=1
#         )
# 
#         if result.get('success') and result.get('goods'):
#             return {
#                 "success": True,
#                 "goods": result['goods'][0]
#             }
# 
#         return {
#             "success": False,
#             "error": "Goods not found",
#             "goods": None
#         }
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
#                 auth_response = client.ensure_authenticated()
#                 return {
#                     'healthy': auth_response['success'],
#                     'authenticated': client._is_authenticated,
#                     'error': auth_response.get('error') if not auth_response['success'] else None,
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
# __version__ = "2.0.0"
# __author__ = "Nash Vybzes Team"
# 
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
#     'efris_client_context',
#     'SystemDictionaryManager',
#     'ZReportService',
#     'TaxpayerQueryService',
#     'GoodsInquiryService',
#     'schedule_daily_dictionary_update',
#     'schedule_daily_zreport_upload'
# ]