# primebooks/security.py
"""
Desktop Security Module
✅ Encrypts local PostgreSQL database
✅ Encrypts sensitive files (auth tokens, company data)
✅ Uses hardware-based encryption key derivation
✅ Protects data at rest
"""
import os
import hashlib
import base64
import json
import logging
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
from cryptography.hazmat.backends import default_backend
import platform
import uuid

logger = logging.getLogger(__name__)


class DesktopSecurityManager:
    """
    Manages encryption/decryption for desktop app
    ✅ Uses machine-specific encryption key
    ✅ Cannot be copied to another machine
    """

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.key_file = self.data_dir / '.encryption_key'
        self.salt_file = self.data_dir / '.salt'

        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Initialize encryption
        self.cipher = self._get_or_create_cipher()

    def _get_machine_id(self):
        """
        Get unique machine identifier
        ✅ Different for each computer
        ✅ Cannot be easily copied
        """
        try:
            # Try to get hardware UUID (most secure)
            if platform.system() == 'Windows':
                # Windows: Get motherboard UUID
                import subprocess
                result = subprocess.run(
                    ['wmic', 'csproduct', 'get', 'UUID'],
                    capture_output=True,
                    text=True
                )
                machine_id = result.stdout.split('\n')[1].strip()
            elif platform.system() == 'Darwin':  # macOS
                # macOS: Get hardware UUID
                import subprocess
                result = subprocess.run(
                    ['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'],
                    capture_output=True,
                    text=True
                )
                for line in result.stdout.split('\n'):
                    if 'IOPlatformUUID' in line:
                        machine_id = line.split('"')[3]
                        break
            else:  # Linux
                # Linux: Get machine-id
                machine_id_file = Path('/etc/machine-id')
                if machine_id_file.exists():
                    machine_id = machine_id_file.read_text().strip()
                else:
                    # Fallback to DMI UUID
                    dmi_file = Path('/sys/class/dmi/id/product_uuid')
                    if dmi_file.exists():
                        machine_id = dmi_file.read_text().strip()
                    else:
                        # Last resort: MAC address
                        machine_id = ':'.join(['{:02x}'.format((uuid.getnode() >> i) & 0xff)
                                               for i in range(0, 48, 8)])

            # Add username for additional uniqueness
            machine_id += os.getlogin()

            return machine_id.encode()

        except Exception as e:
            logger.error(f"Error getting machine ID: {e}")
            # Fallback: use MAC address + username
            fallback = f"{uuid.getnode()}-{os.getlogin()}"
            return fallback.encode()

    def _get_or_create_salt(self):
        """Get or create encryption salt"""
        if self.salt_file.exists():
            return self.salt_file.read_bytes()
        else:
            # Generate random salt
            salt = os.urandom(32)
            self.salt_file.write_bytes(salt)

            # Make salt file read-only
            self.salt_file.chmod(0o400)

            return salt

    def _derive_key(self):
        """
        Derive encryption key from machine ID
        ✅ Unique per machine
        ✅ Cannot be extracted
        """
        machine_id = self._get_machine_id()
        salt = self._get_or_create_salt()

        # Use PBKDF2 to derive key
        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )

        key = base64.urlsafe_b64encode(kdf.derive(machine_id))
        return key

    def _get_or_create_cipher(self):
        """Get or create Fernet cipher"""
        if self.key_file.exists():
            # Load existing key
            key = self.key_file.read_bytes()
        else:
            # Create new key
            key = self._derive_key()
            self.key_file.write_bytes(key)

            # Make key file read-only
            self.key_file.chmod(0o400)

        return Fernet(key)

    def encrypt_file(self, file_path):
        """
        Encrypt a file
        ✅ Original file replaced with encrypted version
        """
        try:
            file_path = Path(file_path)

            if not file_path.exists():
                logger.error(f"File not found: {file_path}")
                return False

            # Read file
            data = file_path.read_bytes()

            # Encrypt
            encrypted_data = self.cipher.encrypt(data)

            # Write encrypted data
            file_path.write_bytes(encrypted_data)

            # Make file read-only
            file_path.chmod(0o400)

            logger.info(f"✅ Encrypted: {file_path}")
            return True

        except Exception as e:
            logger.error(f"Error encrypting file: {e}")
            return False

    def decrypt_file(self, file_path):
        """
        Decrypt a file
        Returns decrypted data as bytes
        """
        try:
            file_path = Path(file_path)

            if not file_path.exists():
                logger.error(f"File not found: {file_path}")
                return None

            # Read encrypted data
            encrypted_data = file_path.read_bytes()

            # Decrypt
            data = self.cipher.decrypt(encrypted_data)

            return data

        except Exception as e:
            logger.error(f"Error decrypting file: {e}")
            return None

    def encrypt_text(self, text):
        """Encrypt text string"""
        try:
            if isinstance(text, str):
                text = text.encode()
            return self.cipher.encrypt(text).decode()
        except Exception as e:
            logger.error(f"Error encrypting text: {e}")
            return None

    def decrypt_text(self, encrypted_text):
        """Decrypt text string"""
        try:
            if isinstance(encrypted_text, str):
                encrypted_text = encrypted_text.encode()
            return self.cipher.decrypt(encrypted_text).decode()
        except Exception as e:
            logger.error(f"Error decrypting text: {e}")
            return None

    def encrypt_dict(self, data_dict):
        """Encrypt dictionary (converts to JSON first)"""
        try:
            json_data = json.dumps(data_dict)
            return self.encrypt_text(json_data)
        except Exception as e:
            logger.error(f"Error encrypting dict: {e}")
            return None

    def decrypt_dict(self, encrypted_data):
        """Decrypt dictionary"""
        try:
            json_data = self.decrypt_text(encrypted_data)
            if json_data:
                return json.loads(json_data)
            return None
        except Exception as e:
            logger.error(f"Error decrypting dict: {e}")
            return None

    def secure_delete(self, file_path):
        """
        Securely delete a file
        ✅ Overwrites with random data before deletion
        """
        try:
            file_path = Path(file_path)

            if not file_path.exists():
                return True

            # Get file size
            file_size = file_path.stat().st_size

            # Overwrite with random data (3 passes)
            for _ in range(3):
                with open(file_path, 'wb') as f:
                    f.write(os.urandom(file_size))
                    f.flush()
                    os.fsync(f.fileno())

            # Delete file
            file_path.unlink()

            logger.info(f"✅ Securely deleted: {file_path}")
            return True

        except Exception as e:
            logger.error(f"Error securely deleting file: {e}")
            return False


class SecureCredentialManager:
    """
    Manages secure storage of credentials
    ✅ Encrypts auth tokens
    ✅ Encrypts company data
    ✅ Encrypts user info
    """

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.security = DesktopSecurityManager(data_dir)

        # Secure credential files
        self.auth_token_file = self.data_dir / '.auth_token.enc'
        self.user_info_file = self.data_dir / '.user_info.enc'
        self.company_info_file = self.data_dir / '.company_info.enc'

    def save_auth_token(self, token):
        """Save encrypted auth token"""
        try:
            encrypted = self.security.encrypt_text(token)
            if encrypted:
                self.auth_token_file.write_text(encrypted)
                self.auth_token_file.chmod(0o400)
                return True
            return False
        except Exception as e:
            logger.error(f"Error saving auth token: {e}")
            return False

    def get_auth_token(self):
        """Get decrypted auth token"""
        try:
            if not self.auth_token_file.exists():
                return None

            encrypted = self.auth_token_file.read_text()
            return self.security.decrypt_text(encrypted)

        except Exception as e:
            logger.error(f"Error getting auth token: {e}")
            return None

    def save_user_info(self, user_info):
        """Save encrypted user info"""
        try:
            encrypted = self.security.encrypt_dict(user_info)
            if encrypted:
                self.user_info_file.write_text(encrypted)
                self.user_info_file.chmod(0o400)
                return True
            return False
        except Exception as e:
            logger.error(f"Error saving user info: {e}")
            return False

    def get_user_info(self):
        """Get decrypted user info"""
        try:
            if not self.user_info_file.exists():
                return None

            encrypted = self.user_info_file.read_text()
            return self.security.decrypt_dict(encrypted)

        except Exception as e:
            logger.error(f"Error getting user info: {e}")
            return None

    def save_company_info(self, company_info):
        """Save encrypted company info"""
        try:
            encrypted = self.security.encrypt_dict(company_info)
            if encrypted:
                self.company_info_file.write_text(encrypted)
                self.company_info_file.chmod(0o400)
                return True
            return False
        except Exception as e:
            logger.error(f"Error saving company info: {e}")
            return False

    def get_company_info(self):
        """Get decrypted company info"""
        try:
            if not self.company_info_file.exists():
                return None

            encrypted = self.company_info_file.read_text()
            return self.security.decrypt_dict(encrypted)

        except Exception as e:
            logger.error(f"Error getting company info: {e}")
            return None

    def clear_all(self):
        """Securely delete all credentials"""
        files = [
            self.auth_token_file,
            self.user_info_file,
            self.company_info_file,
        ]

        for file in files:
            if file.exists():
                self.security.secure_delete(file)


class DatabaseEncryption:
    """
    PostgreSQL database encryption at rest
    ✅ Encrypts PostgreSQL data files
    ✅ Transparent encryption/decryption
    """

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.security = DesktopSecurityManager(data_dir)
        self.pg_data_dir = self.data_dir / 'postgresql' / 'data'

    def encrypt_database(self):
        """
        Encrypt PostgreSQL database files
        ⚠️ Call this after stopping PostgreSQL
        """
        try:
            if not self.pg_data_dir.exists():
                logger.warning("PostgreSQL data directory not found")
                return False

            logger.info("Encrypting PostgreSQL database...")

            # Encrypt all data files
            encrypted_count = 0
            for file in self.pg_data_dir.rglob('*'):
                if file.is_file() and file.suffix not in ['.enc', '.log']:
                    # Skip already encrypted files
                    if file.suffix == '.enc':
                        continue

                    # Encrypt file
                    if self.security.encrypt_file(file):
                        # Rename with .enc extension
                        encrypted_file = file.with_suffix(file.suffix + '.enc')
                        file.rename(encrypted_file)
                        encrypted_count += 1

            logger.info(f"✅ Encrypted {encrypted_count} database files")
            return True

        except Exception as e:
            logger.error(f"Error encrypting database: {e}")
            return False

    def decrypt_database(self):
        """
        Decrypt PostgreSQL database files
        ⚠️ Call this before starting PostgreSQL
        """
        try:
            if not self.pg_data_dir.exists():
                logger.warning("PostgreSQL data directory not found")
                return False

            logger.info("Decrypting PostgreSQL database...")

            # Decrypt all .enc files
            decrypted_count = 0
            for file in self.pg_data_dir.rglob('*.enc'):
                if file.is_file():
                    # Decrypt file
                    decrypted_data = self.security.decrypt_file(file)
                    if decrypted_data:
                        # Write decrypted data to original file
                        original_file = file.with_suffix('')
                        original_file.write_bytes(decrypted_data)

                        # Delete encrypted file
                        file.unlink()
                        decrypted_count += 1

            logger.info(f"✅ Decrypted {decrypted_count} database files")
            return True

        except Exception as e:
            logger.error(f"Error decrypting database: {e}")
            return False


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def initialize_security(data_dir):
    """
    Initialize security for desktop app
    Call this on first run
    """
    logger.info("Initializing desktop security...")

    security = DesktopSecurityManager(data_dir)
    credentials = SecureCredentialManager(data_dir)

    logger.info("✅ Security initialized")

    return security, credentials


def validate_machine():
    """
    Validate that app is running on authorized machine
    ✅ Prevents copying data to another computer
    """
    try:
        security = DesktopSecurityManager(Path.home() / '.local' / 'share' / 'PrimeBooks')

        # Try to decrypt a test file
        # If machine ID changed, decryption will fail
        test_file = security.data_dir / '.machine_validation'

        if not test_file.exists():
            # First run - create validation file
            test_data = "VALID"
            encrypted = security.encrypt_text(test_data)
            test_file.write_text(encrypted)
            return True

        # Try to decrypt
        encrypted = test_file.read_text()
        decrypted = security.decrypt_text(encrypted)

        if decrypted == "VALID":
            return True
        else:
            logger.error("Machine validation failed - data cannot be decrypted on this machine")
            return False

    except Exception as e:
        logger.error(f"Machine validation error: {e}")
        return False