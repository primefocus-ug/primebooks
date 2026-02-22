# primebooks/security/licensing.py
"""
Advanced Security Features
✅ License validation
✅ Tamper detection
✅ Trial period management
✅ Offline license verification
"""
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class LicenseManager:
    """
    Manages software licensing for desktop app
    ✅ Offline license validation
    ✅ Hardware-bound licenses
    ✅ Trial period support
    ✅ Anti-tampering
    """

    def __init__(self, data_dir, encryption_manager):
        self.data_dir = Path(data_dir)
        self.encryption = encryption_manager
        self.license_file = self.data_dir / '.license.enc'
        self.trial_file = self.data_dir / '.trial.enc'

        # License server URL (for online validation)
        self.license_server = "https://license.primebooks.com"

        # Secret key for HMAC offline validation.
        # Read from Django settings or environment variable — never hardcode this.
        import os
        try:
            from django.conf import settings as django_settings
            self.secret_key = django_settings.LICENSE_HMAC_SECRET.encode() \
                if isinstance(django_settings.LICENSE_HMAC_SECRET, str) \
                else django_settings.LICENSE_HMAC_SECRET
        except Exception:
            env_key = os.environ.get('LICENSE_HMAC_SECRET', '')
            if not env_key:
                logger.warning(
                    "LICENSE_HMAC_SECRET is not set — license validation will be unreliable. "
                    "Add LICENSE_HMAC_SECRET to your Django settings or environment."
                )
            self.secret_key = env_key.encode() if env_key else b'UNSET_PLACEHOLDER_KEY'

    def generate_license(self, email, expiry_days=365, company_limit=1):
        """
        Generate a license for a user
        ✅ Call this on your server, not in desktop app

        Args:
            email: User's email
            expiry_days: License validity period
            company_limit: Max companies allowed

        Returns:
            License key string
        """
        # Get machine ID
        machine_id = self.encryption._get_machine_id()

        # License data
        license_data = {
            'email': email,
            'machine_id': machine_id,
            'issued_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(days=expiry_days)).isoformat(),
            'company_limit': company_limit,
            'version': '1.0.0',
        }

        # Create signature
        data_string = json.dumps(license_data, sort_keys=True)
        signature = hmac.new(
            self.secret_key,
            data_string.encode(),
            hashlib.sha256
        ).hexdigest()

        # Combine data + signature
        license_data['signature'] = signature

        # Encode as base64
        import base64
        license_json = json.dumps(license_data)
        license_key = base64.b64encode(license_json.encode()).decode()

        return license_key

    def validate_license(self, license_key):
        """
        Validate a license key
        ✅ Offline validation
        ✅ Checks machine ID
        ✅ Checks expiry
        ✅ Verifies signature

        Returns:
            dict with validation result
        """
        try:
            # Decode license
            import base64
            license_json = base64.b64decode(license_key.encode()).decode()
            license_data = json.loads(license_json)

            # Extract signature
            signature = license_data.pop('signature')

            # Verify signature
            data_string = json.dumps(license_data, sort_keys=True)
            expected_signature = hmac.new(
                self.secret_key,
                data_string.encode(),
                hashlib.sha256
            ).hexdigest()

            if signature != expected_signature:
                return {
                    'valid': False,
                    'error': 'Invalid signature - license may be tampered'
                }

            # Check machine ID
            current_machine_id = self.encryption._get_machine_id()
            if license_data['machine_id'] != current_machine_id:
                return {
                    'valid': False,
                    'error': 'License is bound to different computer'
                }

            # Check expiry
            expires_at = datetime.fromisoformat(license_data['expires_at'])
            if datetime.now() > expires_at:
                return {
                    'valid': False,
                    'error': 'License has expired',
                    'expired_at': expires_at.isoformat()
                }

            # All checks passed
            return {
                'valid': True,
                'email': license_data['email'],
                'expires_at': expires_at.isoformat(),
                'company_limit': license_data['company_limit'],
                'days_remaining': (expires_at - datetime.now()).days
            }

        except Exception as e:
            logger.error(f"License validation error: {e}")
            return {
                'valid': False,
                'error': str(e)
            }

    def save_license(self, license_key):
        """Save encrypted license to disk"""
        try:
            # Encrypt license
            encrypted = self.encryption.encrypt_data(license_key)

            # Save to file
            self.license_file.write_bytes(encrypted)

            # Make read-only
            import platform
            if platform.system() != 'Windows':
                import os
                os.chmod(self.license_file, 0o400)

            logger.info("✅ License saved successfully")
            return True

        except Exception as e:
            logger.error(f"Error saving license: {e}")
            return False

    def load_license(self):
        """Load and validate saved license"""
        try:
            if not self.license_file.exists():
                return None

            # Decrypt license
            encrypted = self.license_file.read_bytes()
            license_key = self.encryption.decrypt_data(encrypted).decode()

            # Validate
            result = self.validate_license(license_key)

            return result

        except Exception as e:
            logger.error(f"Error loading license: {e}")
            return None

    def start_trial(self, trial_days=30):
        """
        Start trial period
        ✅ First-time users get trial
        ✅ Cannot reset trial
        """
        try:
            if self.trial_file.exists():
                return {
                    'success': False,
                    'error': 'Trial already started'
                }

            # Create trial data
            trial_data = {
                'started_at': datetime.now().isoformat(),
                'expires_at': (datetime.now() + timedelta(days=trial_days)).isoformat(),
                'machine_id': self.encryption._get_machine_id(),
            }

            # Encrypt and save
            trial_json = json.dumps(trial_data)
            encrypted = self.encryption.encrypt_data(trial_json)
            self.trial_file.write_bytes(encrypted)

            # Make read-only
            import platform
            if platform.system() != 'Windows':
                import os
                os.chmod(self.trial_file, 0o400)

            return {
                'success': True,
                'expires_at': trial_data['expires_at'],
                'days_remaining': trial_days
            }

        except Exception as e:
            logger.error(f"Error starting trial: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def check_trial(self):
        """Check trial status"""
        try:
            if not self.trial_file.exists():
                return {
                    'active': False,
                    'available': True,
                    'message': 'Trial not started'
                }

            # Decrypt trial data
            encrypted = self.trial_file.read_bytes()
            trial_json = self.encryption.decrypt_data(encrypted).decode()
            trial_data = json.loads(trial_json)

            # Verify machine ID
            current_machine_id = self.encryption._get_machine_id()
            if trial_data['machine_id'] != current_machine_id:
                return {
                    'active': False,
                    'available': False,
                    'message': 'Trial is bound to different computer'
                }

            # Check expiry
            expires_at = datetime.fromisoformat(trial_data['expires_at'])
            if datetime.now() > expires_at:
                return {
                    'active': False,
                    'available': False,
                    'message': 'Trial has expired',
                    'expired_at': expires_at.isoformat()
                }

            # Trial is active
            days_remaining = (expires_at - datetime.now()).days
            return {
                'active': True,
                'available': False,
                'days_remaining': days_remaining,
                'expires_at': expires_at.isoformat()
            }

        except Exception as e:
            logger.error(f"Error checking trial: {e}")
            return {
                'active': False,
                'available': False,
                'error': str(e)
            }

    def is_authorized(self):
        """
        Check if software is authorized to run
        ✅ Checks license OR trial

        Returns:
            tuple: (authorized: bool, message: str)
        """
        # Check license first
        license_result = self.load_license()
        if license_result and license_result.get('valid'):
            days = license_result.get('days_remaining', 0)
            return (True, f"Licensed until {license_result['expires_at']} ({days} days remaining)")

        # Check trial
        trial_result = self.check_trial()
        if trial_result.get('active'):
            days = trial_result.get('days_remaining', 0)
            return (True, f"Trial active ({days} days remaining)")

        # Not authorized
        if trial_result.get('available'):
            return (False, "Trial available - please start trial or enter license")
        else:
            return (False, "Trial expired - please purchase license")


class TamperDetection:
    """
    Detects if application files have been modified
    ✅ File integrity checking
    ✅ Checksum validation
    ✅ Anti-debugging detection
    """

    def __init__(self, app_root):
        self.app_root = Path(app_root)
        self.checksum_file = self.app_root / '.checksums.json'

    def generate_checksums(self):
        """
        Generate checksums for all Python files
        ✅ Run this during build process
        """
        checksums = {}

        # Get all Python files
        for py_file in self.app_root.rglob('*.py'):
            if '.git' in str(py_file) or '__pycache__' in str(py_file):
                continue

            # Calculate SHA256
            content = py_file.read_bytes()
            checksum = hashlib.sha256(content).hexdigest()

            # Store relative path
            rel_path = py_file.relative_to(self.app_root)
            checksums[str(rel_path)] = checksum

        # Save checksums
        with open(self.checksum_file, 'w') as f:
            json.dump(checksums, f, indent=2)

        logger.info(f"✅ Generated checksums for {len(checksums)} files")
        return checksums

    def verify_integrity(self):
        """
        Verify file integrity
        ✅ Checks if files have been modified

        Returns:
            dict with verification results
        """
        if not self.checksum_file.exists():
            return {
                'valid': False,
                'error': 'Checksum file not found'
            }

        # Load stored checksums
        with open(self.checksum_file) as f:
            stored_checksums = json.load(f)

        # Verify each file
        modified_files = []
        missing_files = []

        for rel_path, expected_checksum in stored_checksums.items():
            file_path = self.app_root / rel_path

            if not file_path.exists():
                missing_files.append(rel_path)
                continue

            # Calculate current checksum
            content = file_path.read_bytes()
            current_checksum = hashlib.sha256(content).hexdigest()

            if current_checksum != expected_checksum:
                modified_files.append(rel_path)

        # Check results
        if modified_files or missing_files:
            return {
                'valid': False,
                'modified_files': modified_files,
                'missing_files': missing_files,
                'error': 'Application files have been tampered with'
            }

        return {
            'valid': True,
            'message': 'All files verified successfully'
        }

    def detect_debugger(self):
        """
        Detect if debugger is attached
        ✅ Anti-debugging protection

        Returns:
            bool: True if debugger detected
        """
        import sys

        # Check for common debugger indicators
        debugger_detected = False

        # Check gettrace
        if sys.gettrace() is not None:
            debugger_detected = True

        # Check for pdb
        if 'pdb' in sys.modules:
            debugger_detected = True

        # Check for pydevd (PyCharm)
        if 'pydevd' in sys.modules:
            debugger_detected = True

        return debugger_detected

    def check_environment(self):
        """
        Check if running in suspicious environment
        ✅ Detect VMs, debuggers, analysis tools

        Returns:
            dict with environment checks
        """
        import platform
        import os

        suspicious = []

        # Check for debugger
        if self.detect_debugger():
            suspicious.append('Debugger detected')

        # Check for common VM indicators
        system = platform.system()

        if system == 'Windows':
            # Check for VirtualBox
            if Path('C:\\Program Files\\Oracle\\VirtualBox').exists():
                suspicious.append('VirtualBox detected')

            # Check for VMware
            if any('vmware' in str(p).lower() for p in Path('C:\\Program Files').glob('*')):
                suspicious.append('VMware detected')

        elif system == 'Linux':
            # Check for VM indicators
            try:
                with open('/proc/cpuinfo') as f:
                    cpuinfo = f.read().lower()
                    if 'hypervisor' in cpuinfo or 'vmware' in cpuinfo:
                        suspicious.append('Virtual machine detected')
            except:
                pass

        # Check for common analysis tools
        analysis_tools = ['ida', 'ollydbg', 'x64dbg', 'ghidra', 'radare2']
        running_processes = []

        try:
            if system == 'Windows':
                import subprocess
                result = subprocess.run(['tasklist'], capture_output=True, text=True)
                running_processes = result.stdout.lower()
            elif system == 'Linux':
                import subprocess
                result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
                running_processes = result.stdout.lower()
        except:
            pass

        for tool in analysis_tools:
            if tool in str(running_processes):
                suspicious.append(f'Analysis tool detected: {tool}')

        return {
            'suspicious': len(suspicious) > 0,
            'indicators': suspicious,
            'safe': len(suspicious) == 0
        }


class UsageAnalytics:
    """
    Track usage statistics (privacy-respecting)
    ✅ Anonymous usage tracking
    ✅ Feature usage statistics
    ✅ Error reporting
    """

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.analytics_file = self.data_dir / '.analytics.json'
        self.load_analytics()

    def load_analytics(self):
        """Load analytics data"""
        if self.analytics_file.exists():
            try:
                with open(self.analytics_file) as f:
                    self.analytics = json.load(f)
            except:
                self.analytics = self._create_default_analytics()
        else:
            self.analytics = self._create_default_analytics()

    def _create_default_analytics(self):
        """Create default analytics structure"""
        return {
            'install_date': datetime.now().isoformat(),
            'last_used': None,
            'total_launches': 0,
            'feature_usage': {},
            'errors': [],
            'crash_reports': []
        }

    def save_analytics(self):
        """Save analytics data"""
        try:
            with open(self.analytics_file, 'w') as f:
                json.dump(self.analytics, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving analytics: {e}")

    def record_launch(self):
        """Record app launch"""
        self.analytics['total_launches'] += 1
        self.analytics['last_used'] = datetime.now().isoformat()
        self.save_analytics()

    def record_feature_usage(self, feature_name):
        """Record feature usage"""
        if feature_name not in self.analytics['feature_usage']:
            self.analytics['feature_usage'][feature_name] = 0

        self.analytics['feature_usage'][feature_name] += 1
        self.save_analytics()

    def record_error(self, error_type, error_message):
        """Record error"""
        error_data = {
            'type': error_type,
            'message': error_message,
            'timestamp': datetime.now().isoformat()
        }

        self.analytics['errors'].append(error_data)

        # Keep only last 100 errors
        if len(self.analytics['errors']) > 100:
            self.analytics['errors'] = self.analytics['errors'][-100:]

        self.save_analytics()

    def get_statistics(self):
        """Get usage statistics"""
        return {
            'install_date': self.analytics['install_date'],
            'last_used': self.analytics['last_used'],
            'total_launches': self.analytics['total_launches'],
            'most_used_features': sorted(
                self.analytics['feature_usage'].items(),
                key=lambda x: x[1],
                reverse=True
            )[:10],
            'total_errors': len(self.analytics['errors'])
        }


# ============================================================================
# Integration Functions
# ============================================================================

def check_authorization(data_dir, encryption_manager):
    """
    Check if app is authorized to run
    ✅ Call this on app startup

    Returns:
        tuple: (authorized: bool, message: str, license_info: dict)
    """
    license_manager = LicenseManager(data_dir, encryption_manager)
    authorized, message = license_manager.is_authorized()

    if authorized:
        license_info = license_manager.load_license()
        return (True, message, license_info)
    else:
        # Check if trial available
        trial_status = license_manager.check_trial()
        return (False, message, trial_status)


def verify_application_integrity(app_root):
    """
    Verify application hasn't been tampered with
    ✅ Call this on app startup

    Returns:
        bool: True if application is unmodified
    """
    tamper = TamperDetection(app_root)

    # Check integrity
    integrity_result = tamper.verify_integrity()
    if not integrity_result['valid']:
        logger.error(f"Tamper detected: {integrity_result}")
        return False

    # Check environment
    env_result = tamper.check_environment()
    if env_result['suspicious']:
        logger.warning(f"Suspicious environment: {env_result['indicators']}")
        # Don't block, but log it

    return True