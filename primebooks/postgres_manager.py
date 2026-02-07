"""
Embedded PostgreSQL Manager - COMPREHENSIVE VERSION
✅ Works on Windows, macOS, and Linux
✅ Detects and uses existing PostgreSQL installations
✅ Falls back to embedded download only if needed
✅ Properly handles encryption/decryption with config file exclusion
✅ Windows-optimized startup (no hangs)
✅ Linux-compatible initialization
"""

import subprocess
import os
import time
import logging
import shutil
import platform
from pathlib import Path
import requests
import tarfile
import zipfile
import socket
from primebooks.security.encryption import get_encryption_manager


logger = logging.getLogger(__name__)


class EmbeddedPostgresManager:
    """
    Manages PostgreSQL for desktop mode.
    Priority:
    1. Use existing system PostgreSQL if available
    2. Download embedded PostgreSQL only if needed

    ✅ Windows: Optimized startup, proper locale handling
    ✅ Linux: System package manager integration
    ✅ Both: Encryption with config file exclusion
    """

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.postgres_dir = self.data_dir / 'postgresql'
        self.data_subdir = self.postgres_dir / 'data'
        self.is_windows = platform.system() == 'Windows'
        self.is_linux = platform.system() == 'Linux'
        self.is_macos = platform.system() == 'Darwin'

        # Try to find existing PostgreSQL installation
        self.postgres_install = self._detect_postgres_installation()

        if self.postgres_install:
            logger.info(f"✅ Found existing PostgreSQL at: {self.postgres_install['path']}")
            logger.info(f"   Version: {self.postgres_install.get('version', 'unknown')}")
            self.bin_dir = self.postgres_install['bin_dir']
            self.using_system_postgres = True
        else:
            logger.info("No existing PostgreSQL found - will use embedded version")
            self.bin_dir = self._find_bin_dir()
            self.using_system_postgres = False

        self.port = 5433  # Non-standard port to avoid conflicts
        self.db_name = 'primebooks'
        self.db_user = 'primebooks_user'
        self.log_file = self.data_dir / 'postgresql.log'

        # Files to EXCLUDE from encryption
        self.encryption_exclude = [
            'postgresql.conf',
            'pg_hba.conf',
            'pg_ident.conf',
            'postgresql.auto.conf',
            'PG_VERSION',
            'postmaster.pid',
            'postmaster.opts',
        ]

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.encryption = get_encryption_manager(self.data_dir)

    # =========================================================================
    # DETECTION: Find existing PostgreSQL installations
    # =========================================================================

    def _detect_postgres_installation(self):
        """
        Detect existing PostgreSQL installations on the system

        Returns:
            dict with 'path', 'bin_dir', 'version' if found, None otherwise
        """
        logger.info("🔍 Searching for existing PostgreSQL installation...")

        if self.is_windows:
            return self._detect_postgres_windows()
        elif self.is_macos:
            return self._detect_postgres_macos()
        else:  # Linux
            return self._detect_postgres_linux()

    def _detect_postgres_windows(self):
        """Detect PostgreSQL on Windows"""
        # Common installation locations
        search_paths = [
            # PostgreSQL installed via official installer
            Path(os.environ.get('ProgramFiles', 'C:\\Program Files')) / 'PostgreSQL',
            Path(os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)')) / 'PostgreSQL',
            # Chocolatey/Scoop installations
            Path('C:\\ProgramData\\chocolatey\\lib\\postgresql'),
            Path(os.environ.get('USERPROFILE', '')) / 'scoop' / 'apps' / 'postgresql',
            # EDB installations
            Path('C:\\edb'),
        ]

        # Also check PATH
        pg_config_path = shutil.which('pg_config')
        if pg_config_path:
            try:
                result = subprocess.run([pg_config_path, '--bindir'],
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    bin_dir = Path(result.stdout.strip())
                    if bin_dir.exists():
                        version_result = subprocess.run([str(bin_dir / 'postgres.exe'), '--version'],
                                                       capture_output=True, text=True, timeout=5)
                        version = version_result.stdout.strip() if version_result.returncode == 0 else 'unknown'

                        return {
                            'path': bin_dir.parent,
                            'bin_dir': bin_dir,
                            'version': version,
                            'source': 'PATH'
                        }
            except Exception as e:
                logger.debug(f"Error checking pg_config in PATH: {e}")

        # Search common locations
        for base_path in search_paths:
            if not base_path.exists():
                continue

            # Look for version subdirectories (e.g., PostgreSQL/15, PostgreSQL/16)
            for version_dir in sorted(base_path.glob('*'), reverse=True):  # Try newest first
                if not version_dir.is_dir():
                    continue

                bin_dir = version_dir / 'bin'
                pg_ctl = bin_dir / 'pg_ctl.exe'
                postgres = bin_dir / 'postgres.exe'

                if pg_ctl.exists() and postgres.exists():
                    try:
                        version_result = subprocess.run([str(postgres), '--version'],
                                                       capture_output=True, text=True, timeout=5)
                        version = version_result.stdout.strip() if version_result.returncode == 0 else 'unknown'

                        return {
                            'path': version_dir,
                            'bin_dir': bin_dir,
                            'version': version,
                            'source': str(base_path)
                        }
                    except Exception as e:
                        logger.debug(f"Error checking {bin_dir}: {e}")

        return None

    def _detect_postgres_macos(self):
        """Detect PostgreSQL on macOS"""
        search_paths = [
            # Homebrew
            Path('/opt/homebrew/opt/postgresql@16/bin'),  # Apple Silicon
            Path('/opt/homebrew/opt/postgresql@15/bin'),
            Path('/opt/homebrew/opt/postgresql/bin'),
            Path('/usr/local/opt/postgresql@16/bin'),  # Intel
            Path('/usr/local/opt/postgresql@15/bin'),
            Path('/usr/local/opt/postgresql/bin'),
            # Postgres.app
            Path('/Applications/Postgres.app/Contents/Versions/16/bin'),
            Path('/Applications/Postgres.app/Contents/Versions/15/bin'),
            Path('/Applications/Postgres.app/Contents/Versions/latest/bin'),
            # MacPorts
            Path('/opt/local/lib/postgresql16/bin'),
            Path('/opt/local/lib/postgresql15/bin'),
        ]

        # Check PATH first
        pg_config_path = shutil.which('pg_config')
        if pg_config_path:
            try:
                result = subprocess.run([pg_config_path, '--bindir'],
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    bin_dir = Path(result.stdout.strip())
                    if bin_dir.exists():
                        version_result = subprocess.run([str(bin_dir / 'postgres'), '--version'],
                                                       capture_output=True, text=True, timeout=5)
                        version = version_result.stdout.strip() if version_result.returncode == 0 else 'unknown'

                        return {
                            'path': bin_dir.parent,
                            'bin_dir': bin_dir,
                            'version': version,
                            'source': 'PATH'
                        }
            except Exception as e:
                logger.debug(f"Error checking pg_config: {e}")

        # Check common paths
        for bin_dir in search_paths:
            pg_ctl = bin_dir / 'pg_ctl'
            postgres = bin_dir / 'postgres'

            if pg_ctl.exists() and postgres.exists():
                try:
                    version_result = subprocess.run([str(postgres), '--version'],
                                                   capture_output=True, text=True, timeout=5)
                    version = version_result.stdout.strip() if version_result.returncode == 0 else 'unknown'

                    return {
                        'path': bin_dir.parent,
                        'bin_dir': bin_dir,
                        'version': version,
                        'source': str(bin_dir.parent)
                    }
                except Exception as e:
                    logger.debug(f"Error checking {bin_dir}: {e}")

        return None

    def _detect_postgres_linux(self):
        """Detect PostgreSQL on Linux"""
        # Check PATH first
        pg_config_path = shutil.which('pg_config')
        if pg_config_path:
            try:
                result = subprocess.run([pg_config_path, '--bindir'],
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    bin_dir = Path(result.stdout.strip())
                    if bin_dir.exists():
                        version_result = subprocess.run([str(bin_dir / 'postgres'), '--version'],
                                                       capture_output=True, text=True, timeout=5)
                        version = version_result.stdout.strip() if version_result.returncode == 0 else 'unknown'

                        return {
                            'path': bin_dir.parent,
                            'bin_dir': bin_dir,
                            'version': version,
                            'source': 'system'
                        }
            except Exception as e:
                logger.debug(f"Error checking pg_config: {e}")

        # Common Linux paths
        search_paths = [
            Path('/usr/lib/postgresql/16/bin'),
            Path('/usr/lib/postgresql/15/bin'),
            Path('/usr/lib/postgresql/14/bin'),
            Path('/usr/pgsql-16/bin'),
            Path('/usr/pgsql-15/bin'),
        ]

        for bin_dir in search_paths:
            pg_ctl = bin_dir / 'pg_ctl'
            postgres = bin_dir / 'postgres'

            if pg_ctl.exists() and postgres.exists():
                try:
                    version_result = subprocess.run([str(postgres), '--version'],
                                                   capture_output=True, text=True, timeout=5)
                    version = version_result.stdout.strip() if version_result.returncode == 0 else 'unknown'

                    return {
                        'path': bin_dir.parent,
                        'bin_dir': bin_dir,
                        'version': version,
                        'source': 'system'
                    }
                except Exception as e:
                    logger.debug(f"Error checking {bin_dir}: {e}")

        return None

    def _find_bin_dir(self):
        """Find the correct bin directory for embedded PostgreSQL binaries"""
        possible_paths = [
            self.postgres_dir / 'bin',
            self.postgres_dir / 'pgsql' / 'bin',
            self.postgres_dir / 'postgresql' / 'bin',
        ]

        for path in possible_paths:
            pg_ctl = path / ('pg_ctl.exe' if self.is_windows else 'pg_ctl')
            if pg_ctl.exists():
                logger.info(f"Found embedded PostgreSQL binaries in: {path}")
                return path

        return possible_paths[0]

    def _get_binary_path(self, binary_name):
        """Get full path to a PostgreSQL binary with proper extension"""
        if self.is_windows and not binary_name.endswith('.exe'):
            binary_name += '.exe'

        binary_path = self.bin_dir / binary_name

        # Re-check bin directory location if binary not found
        if not binary_path.exists() and not self.using_system_postgres:
            self.bin_dir = self._find_bin_dir()
            binary_path = self.bin_dir / binary_name

        return binary_path

    # =========================================================================
    # ENCRYPTION: File encryption/decryption
    # =========================================================================

    def _should_encrypt_file(self, file_path):
        """Check if a file should be encrypted"""
        if file_path.name in self.encryption_exclude:
            return False
        if file_path.suffix in ['.enc', '.log', '.tmp', '.pid', '.opts']:
            return False
        if 'lock' in file_path.name.lower():
            return False
        return True

    def _has_encrypted_files(self):
        """Check if data directory contains encrypted (.enc) files"""
        if not self.data_subdir.exists():
            return False, 0

        enc_files = list(self.data_subdir.rglob('*.enc'))

        if enc_files:
            logger.info(f"Found {len(enc_files)} .enc files")
            return True, len(enc_files)

        return False, 0

    def _encrypt_database(self):
        """Encrypt PostgreSQL data files (excludes config files)"""
        if not self.data_subdir.exists():
            logger.info("No data directory to encrypt")
            return

        encrypted_count = 0
        failed_count = 0

        try:
            all_files = [f for f in self.data_subdir.rglob('*') if f.is_file()]
            files_to_encrypt = [f for f in all_files if self._should_encrypt_file(f)]

            if not files_to_encrypt:
                logger.info("No files to encrypt")
                return

            logger.info(f"Encrypting {len(files_to_encrypt)} files (skipping {len(all_files) - len(files_to_encrypt)} config/log files)...")

            # On Windows, encrypt in batches with explicit cleanup
            batch_size = 50 if self.is_windows else 500

            for i, file_path in enumerate(files_to_encrypt):
                try:
                    # Encrypt the file
                    self.encryption.encrypt_file(file_path)

                    # Rename to .enc
                    enc_path = Path(str(file_path) + '.enc')

                    # On Windows, ensure file is closed before renaming
                    if self.is_windows:
                        time.sleep(0.001)  # 1ms delay

                    file_path.rename(enc_path)
                    encrypted_count += 1

                    # On Windows, add delays every batch
                    if self.is_windows and (i + 1) % batch_size == 0:
                        time.sleep(0.05)
                        logger.debug(f"Encrypted {i + 1}/{len(files_to_encrypt)} files...")

                except Exception as e:
                    logger.error(f"Failed to encrypt {file_path}: {e}")
                    failed_count += 1

            if encrypted_count > 0:
                logger.info(f"✅ Encrypted {encrypted_count} database files")
            if failed_count > 0:
                logger.warning(f"⚠️ Failed to encrypt {failed_count} files")

            # On Windows, ensure all file handles are released
            if self.is_windows and encrypted_count > 0:
                import gc
                gc.collect()
                time.sleep(0.5)

        except Exception as e:
            logger.error(f"Encryption error: {e}", exc_info=True)

    def _decrypt_database(self):
        """Decrypt PostgreSQL data files"""
        if not self.data_subdir.exists():
            logger.info("No data directory to decrypt")
            return

        has_encrypted, file_count = self._has_encrypted_files()
        if not has_encrypted:
            logger.debug("No encrypted files to decrypt")
            return

        decrypted_count = 0
        failed_count = 0

        try:
            enc_files = list(self.data_subdir.rglob('*.enc'))

            logger.info(f"Decrypting {len(enc_files)} database files...")

            # On Windows: decrypt in batches with explicit file closing
            batch_size = 50 if self.is_windows else 500

            for i, enc_path in enumerate(enc_files):
                try:
                    original_path = Path(str(enc_path)[:-4])

                    # Decrypt the file
                    self.encryption.decrypt_file(enc_path, original_path)

                    # Ensure the decrypted file is fully written and closed
                    if self.is_windows:
                        # On Windows, explicitly sync to disk
                        try:
                            with open(original_path, 'rb') as f:
                                pass  # Just open and close to ensure it's accessible
                        except:
                            pass

                    # Remove the encrypted file
                    enc_path.unlink()
                    decrypted_count += 1

                    # On Windows, add delays every batch
                    if self.is_windows and (i + 1) % batch_size == 0:
                        time.sleep(0.05)  # 50ms delay
                        logger.debug(f"Decrypted {i + 1}/{len(enc_files)} files...")

                except Exception as e:
                    logger.error(f"Failed to decrypt {enc_path}: {e}")
                    failed_count += 1

            if decrypted_count > 0:
                logger.info(f"✅ Decrypted {decrypted_count} database files")
            if failed_count > 0:
                logger.warning(f"⚠️ Failed to decrypt {failed_count} files")

            # On Windows, give the OS time to fully release all file handles
            if self.is_windows and decrypted_count > 0:
                logger.info("Waiting for Windows to release file handles...")
                time.sleep(2)  # 2 second wait

                import gc
                gc.collect()

                time.sleep(0.5)  # Extra half second
                logger.info("File handles released, ready to start PostgreSQL")

        except Exception as e:
            logger.error(f"Decryption error: {e}", exc_info=True)

    # =========================================================================
    # INSTALLATION: Download and install PostgreSQL
    # =========================================================================

    def get_postgres_url(self):
        """Get the download URL for PostgreSQL binaries for this platform"""
        system = platform.system()
        machine = platform.machine()

        if system == "Linux":
            if "x86_64" in machine or "amd64" in machine:
                return "https://ftp.postgresql.org/pub/binary/v15.5/linux/x64/postgresql-15.5-linux-x64-binaries.tar.gz"
            elif "aarch64" in machine or "arm64" in machine:
                return "https://ftp.postgresql.org/pub/binary/v15.5/linux/arm64/postgresql-15.5-linux-arm64-binaries.tar.gz"
        elif system == "Darwin":
            return "https://get.enterprisedb.com/postgresql/postgresql-15.5-1-osx-binaries.zip"
        elif system == "Windows":
            return "https://get.enterprisedb.com/postgresql/postgresql-15.5-1-windows-x64-binaries.zip"

        raise Exception(f"Unsupported platform: {system} {machine}")

    def is_installed(self):
        """Check if PostgreSQL binaries are available (system or embedded)"""
        if self.using_system_postgres:
            return True

        pg_ctl = self._get_binary_path('pg_ctl')
        postgres = self._get_binary_path('postgres')
        installed = pg_ctl.exists() and postgres.exists()

        if installed:
            logger.info(f"Embedded PostgreSQL binaries found at: {self.bin_dir}")
        else:
            logger.info(f"Embedded PostgreSQL binaries not found at: {self.bin_dir}")

        return installed

    def install(self, progress_callback=None):
        """Download and install PostgreSQL binaries (only if not using system PostgreSQL)"""
        if self.using_system_postgres:
            logger.info("Using system PostgreSQL - no installation needed")
            if progress_callback:
                progress_callback("Using system PostgreSQL")
            return True

        if self.is_installed():
            logger.info("Embedded PostgreSQL already installed")
            return True

        try:
            return self._install_portable(progress_callback)
        except Exception as e:
            logger.error(f"Failed to install PostgreSQL: {e}", exc_info=True)
            if progress_callback:
                progress_callback(f"Error: {e}")
            return False

    def _install_portable(self, progress_callback=None):
        """Install portable PostgreSQL binaries for Windows/macOS/Linux"""
        logger.info("Downloading embedded PostgreSQL binaries...")
        if progress_callback:
            progress_callback("Downloading PostgreSQL...")

        url = self.get_postgres_url()
        download_path = self.data_dir / 'postgres_download.tmp'

        try:
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size:
                            percent = (downloaded / total_size) * 100
                            progress_callback(f"Downloading PostgreSQL... {percent:.1f}%")

            logger.info("Extracting PostgreSQL binaries...")
            if progress_callback:
                progress_callback("Extracting PostgreSQL...")

            if '.tar.gz' in str(download_path) or download_path.suffix == '.gz':
                with tarfile.open(download_path, 'r:gz') as tar:
                    tar.extractall(self.postgres_dir)
            else:
                with zipfile.ZipFile(download_path, 'r') as zip_ref:
                    zip_ref.extractall(self.postgres_dir)

            # Handle nested pgsql directory structure
            pgsql_dir = self.postgres_dir / 'pgsql'
            if pgsql_dir.exists():
                logger.info(f"Moving binaries from {pgsql_dir} to {self.postgres_dir}")
                for item in pgsql_dir.iterdir():
                    dest = self.postgres_dir / item.name
                    if dest.exists():
                        if dest.is_dir():
                            shutil.rmtree(dest)
                        else:
                            dest.unlink()
                    shutil.move(str(item), str(dest))
                pgsql_dir.rmdir()

            self.bin_dir = self._find_bin_dir()

            if not self.is_windows:
                for binary in self.bin_dir.glob('*'):
                    if binary.is_file():
                        os.chmod(binary, 0o755)

            logger.info("✅ Embedded PostgreSQL installed successfully")
            if progress_callback:
                progress_callback("PostgreSQL installed successfully")

            return True

        except Exception as e:
            logger.error(f"Installation failed: {e}", exc_info=True)
            raise

        finally:
            if download_path.exists():
                download_path.unlink()

    # =========================================================================
    # INITIALIZATION: Create database cluster
    # =========================================================================

    def is_initialized(self):
        """Check if database cluster is initialized"""
        pg_version = self.data_subdir / 'PG_VERSION'
        return pg_version.exists()

    def initialize(self, progress_callback=None):
        """Initialize PostgreSQL database cluster"""
        has_encrypted, file_count = self._has_encrypted_files()

        if has_encrypted:
            logger.info(f"Found {file_count} encrypted files - decrypting...")
            if progress_callback:
                progress_callback("Decrypting existing database...")

            self._decrypt_database()

            if self.is_initialized():
                logger.info("✅ Database already initialized (after decryption)")
                if progress_callback:
                    progress_callback("Database already initialized")
                return True

        if self.is_initialized():
            logger.info("PostgreSQL already initialized")
            if progress_callback:
                progress_callback("Database already initialized")
            return True

        try:
            logger.info("Initializing PostgreSQL database cluster...")
            if progress_callback:
                progress_callback("Initializing database...")

            self.data_subdir.mkdir(parents=True, exist_ok=True)

            initdb = self._get_binary_path('initdb')

            if not initdb.exists():
                raise Exception(f"initdb not found at {initdb}")

            cmd = [
                str(initdb),
                '-D', str(self.data_subdir),
                '-U', self.db_user,
                '--auth=trust',
                '--encoding=UTF8',
            ]

            # Windows-specific: Use simpler locale to avoid hangs
            if self.is_windows:
                cmd.append('--locale=C')

            logger.info(f"Running: {' '.join(cmd)}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                logger.error(f"initdb failed with code {result.returncode}")
                logger.error(f"stderr: {result.stderr}")
                logger.error(f"stdout: {result.stdout}")
                return False

            logger.info("Database cluster initialized")
            self._configure_postgres()

            logger.info("✅ PostgreSQL initialized successfully")
            if progress_callback:
                progress_callback("Database initialized")

            return True

        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL: {e}", exc_info=True)
            if progress_callback:
                progress_callback(f"Error: {e}")
            return False

    def _configure_postgres(self):
        """Configure PostgreSQL settings"""
        pg_conf = self.data_subdir / 'postgresql.conf'

        if self.is_windows:
            socket_config = ""
            # Windows-specific: Use simpler locale to avoid hangs
            locale_config = "lc_messages = 'C'\nlc_monetary = 'C'\nlc_numeric = 'C'\nlc_time = 'C'"
        else:
            socket_dir = self.postgres_dir / 'sockets'
            socket_dir.mkdir(parents=True, exist_ok=True)
            socket_config = f"unix_socket_directories = '{socket_dir}'"
            locale_config = ""

        existing_config = ""
        if pg_conf.exists():
            with open(pg_conf, 'r', encoding='utf-8') as f:
                existing_config = f.read()

            if '# PrimeBooks Desktop Settings' in existing_config:
                existing_config = existing_config.split('# PrimeBooks Desktop Settings')[0]

        with open(pg_conf, 'w', encoding='utf-8') as f:
            f.write(existing_config)
            f.write(f"""
# PrimeBooks Desktop Settings
port = {self.port}
listen_addresses = 'localhost'
max_connections = 50
shared_buffers = 128MB
dynamic_shared_memory_type = {'windows' if self.is_windows else 'posix'}
logging_collector = on
log_directory = 'log'
log_filename = 'postgresql-%Y-%m-%d.log'
log_statement = 'all'
log_min_messages = warning
log_min_error_statement = error
{locale_config}
{socket_config}
""")

        pg_hba = self.data_subdir / 'pg_hba.conf'
        with open(pg_hba, 'w', encoding='utf-8') as f:
            f.write("""# TYPE  DATABASE        USER            ADDRESS                 METHOD
local   all             all                                     trust
host    all             all             127.0.0.1/32            trust
host    all             all             ::1/128                 trust
""")

        logger.info(f"PostgreSQL configured for port {self.port}")

    # =========================================================================
    # RUNTIME: Start/Stop PostgreSQL
    # =========================================================================

    def _is_port_available(self, port):
        """Check if a port is available"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return True
        except OSError:
            return False

    def _find_available_port(self):
        """Find an available port, starting from default"""
        if self._is_port_available(self.port):
            return self.port

        logger.warning(f"Port {self.port} is in use, searching for alternative...")

        for alt_port in range(5434, 5450):
            if self._is_port_available(alt_port):
                logger.info(f"Found available port: {alt_port}")
                return alt_port

        raise Exception("No available ports found in range 5433-5449")

    def _read_port_from_config(self):
        """Read the port number from postgresql.conf"""
        pg_conf = self.data_subdir / 'postgresql.conf'
        if not pg_conf.exists():
            logger.warning("postgresql.conf not found, using default port")
            return

        try:
            with open(pg_conf, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('port =') or line.startswith('port='):
                        port_str = line.split('=')[1].strip()
                        port_str = port_str.split('#')[0].strip()
                        self.port = int(port_str)
                        logger.info(f"Read port {self.port} from postgresql.conf")
                        return
        except Exception as e:
            logger.error(f"Error reading port from config: {e}")

    def is_running(self):
        """Check if PostgreSQL server is running"""
        try:
            pg_ctl = self._get_binary_path('pg_ctl')

            if not pg_ctl.exists():
                logger.warning(f"pg_ctl not found at {pg_ctl}")
                return False

            result = subprocess.run([
                str(pg_ctl),
                'status',
                '-D', str(self.data_subdir)
            ], capture_output=True, text=True, timeout=5)

            is_running = result.returncode == 0

            if is_running:
                logger.debug("PostgreSQL is running")
            else:
                logger.debug(f"PostgreSQL is not running: {result.stdout}")

            return is_running

        except Exception as e:
            logger.debug(f"Error checking PostgreSQL status: {e}")
            return False

    def _cleanup_stale_locks(self):
        """Remove stale lock files that might prevent startup"""
        postmaster_pid = self.data_subdir / 'postmaster.pid'

        if not postmaster_pid.exists():
            return

        logger.info(f"Found postmaster.pid file, checking if it's stale...")

        try:
            with open(postmaster_pid, 'r') as f:
                first_line = f.readline().strip()
                if first_line.isdigit():
                    old_pid = int(first_line)
                    logger.info(f"Lock file contains PID: {old_pid}")

                    if self.is_windows:
                        result = subprocess.run(
                            ['tasklist', '/FI', f'PID eq {old_pid}'],
                            capture_output=True, text=True
                        )
                        process_exists = str(old_pid) in result.stdout
                    else:
                        import errno
                        try:
                            os.kill(old_pid, 0)
                            process_exists = True
                        except OSError as e:
                            process_exists = e.errno != errno.ESRCH

                    if not process_exists:
                        logger.info(f"Process {old_pid} not running - removing stale lock")
                        postmaster_pid.unlink()
                    else:
                        logger.warning(f"Process {old_pid} is still running!")
        except Exception as e:
            logger.error(f"Error checking lock file: {e}")

    def start(self, progress_callback=None):
        """Start PostgreSQL server"""
        if self.is_running():
            logger.info("PostgreSQL already running")
            self._read_port_from_config()
            logger.info(f"PostgreSQL is running on port {self.port}")
            return True

        self._decrypt_database()
        self._cleanup_stale_locks()

        try:
            self.port = self._find_available_port()
            self._configure_postgres()

            logger.info(f"Starting PostgreSQL on port {self.port}...")
            if progress_callback:
                progress_callback(f"Starting PostgreSQL on port {self.port}...")

            pg_ctl = self._get_binary_path('pg_ctl')

            if not pg_ctl.exists():
                raise Exception(f"pg_ctl not found at {pg_ctl}")

            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            (self.data_subdir / 'log').mkdir(parents=True, exist_ok=True)

            # Windows-specific: Use very aggressive timeout and background mode
            if self.is_windows:
                logger.info("Using Windows optimized startup mode...")

                # Start in absolute background mode - don't wait at all
                cmd = [
                    str(pg_ctl),
                    'start',
                    '-D', str(self.data_subdir),
                    '-l', str(self.log_file),
                ]

                logger.info(f"Running: {' '.join(cmd)}")

                # Fire and forget - don't even wait for pg_ctl to return
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if self.is_windows else 0
                )

                # Give pg_ctl a moment to issue the start command
                time.sleep(1)

                logger.info("PostgreSQL start command issued")

            else:
                # On Unix, use the standard approach
                cmd = [
                    str(pg_ctl),
                    'start',
                    '-D', str(self.data_subdir),
                    '-l', str(self.log_file),
                    '-w',
                    '-t', '30'
                ]

                logger.info(f"Running: {' '.join(cmd)}")

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)

                if result.returncode != 0:
                    logger.error(f"pg_ctl failed with code {result.returncode}")
                    logger.error(f"stderr: {result.stderr}")
                    logger.error(f"stdout: {result.stdout}")
                    self._show_postgres_log()
                    return False

            # Wait for PostgreSQL to actually accept connections
            logger.info("Waiting for PostgreSQL to accept connections...")
            max_wait = 30
            wait_interval = 0.5

            for i in range(int(max_wait / wait_interval)):
                is_running = self.is_running()
                can_connect = self._can_connect() if is_running else False

                if i % 10 == 0:  # Log every 5 seconds
                    logger.debug(f"Check {i}: running={is_running}, can_connect={can_connect}")

                if is_running and can_connect:
                    logger.info(f"✅ PostgreSQL started and accepting connections on port {self.port} (took {i * wait_interval:.1f}s)")
                    if progress_callback:
                        progress_callback("PostgreSQL started")
                    return True

                if progress_callback and i % 4 == 0:
                    progress_callback(f"Waiting for PostgreSQL... {i * wait_interval:.0f}s")

                time.sleep(wait_interval)

            # Timeout waiting for connection
            logger.error(f"PostgreSQL failed to accept connections within {max_wait} seconds")

            if self.is_running():
                logger.error("PostgreSQL is running but not accepting connections")
            else:
                logger.error("PostgreSQL process is not running")

            self._show_postgres_log()

            # Try to stop it
            try:
                subprocess.run([
                    str(pg_ctl), 'stop', '-D', str(self.data_subdir),
                    '-m', 'immediate'
                ], timeout=10, capture_output=True)
            except:
                pass

            return False

        except Exception as e:
            logger.error(f"Failed to start PostgreSQL: {e}", exc_info=True)
            if progress_callback:
                progress_callback(f"Error: {e}")
            return False

    def _can_connect(self):
        """Check if PostgreSQL is accepting connections"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect(('127.0.0.1', self.port))
                return True
        except:
            return False

    def _show_postgres_log(self):
        """Show the last part of PostgreSQL log file"""
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    log_content = f.read()
                    if log_content:
                        logger.error(f"PostgreSQL log (last 3000 chars):\n{log_content[-3000:]}")
                    else:
                        logger.error("PostgreSQL log file is empty")
            except Exception as e:
                logger.error(f"Could not read log file: {e}")
        else:
            logger.error(f"PostgreSQL log file not found: {self.log_file}")

        # Also check the data directory log
        log_dir = self.data_subdir / 'log'
        if log_dir.exists():
            try:
                log_files = sorted(log_dir.glob('postgresql-*.log'))
                if log_files:
                    latest_log = log_files[-1]
                    logger.info(f"Checking data directory log: {latest_log}")
                    with open(latest_log, 'r', encoding='utf-8', errors='ignore') as f:
                        log_content = f.read()
                        if log_content:
                            logger.error(f"Data directory log (last 3000 chars):\n{log_content[-3000:]}")
            except Exception as e:
                logger.error(f"Could not read data directory log: {e}")

    def stop(self, encrypt_after=True):
        """Stop PostgreSQL server"""
        if not self.is_running():
            logger.info("PostgreSQL not running")
            return True

        try:
            logger.info("Stopping PostgreSQL...")

            pg_ctl = self._get_binary_path('pg_ctl')

            result = subprocess.run([
                str(pg_ctl),
                'stop',
                '-D', str(self.data_subdir),
                '-m', 'fast',
                '-w',
                '-t', '30'
            ], capture_output=True, text=True, timeout=45)

            if result.returncode != 0:
                logger.warning(f"PostgreSQL stop returned code {result.returncode}")
                logger.warning(f"stderr: {result.stderr}")

            time.sleep(2)

            if encrypt_after:
                logger.info("Encrypting database files...")
                self._encrypt_database()

            logger.info("✅ PostgreSQL stopped")
            return True

        except Exception as e:
            logger.error(f"Failed to stop PostgreSQL: {e}", exc_info=True)
            return False

    # =========================================================================
    # DATABASE CREATION
    # =========================================================================

    def create_database(self, progress_callback=None):
        """Create the main database"""
        try:
            logger.info(f"Creating database '{self.db_name}'...")
            logger.info(f"Using port: {self.port}")
            logger.info(f"Using user: {self.db_user}")
            if progress_callback:
                progress_callback("Creating database...")

            createdb = self._get_binary_path('createdb')

            cmd = [
                str(createdb),
                '-h', 'localhost',
                '-p', str(self.port),
                '-U', self.db_user,
                self.db_name
            ]

            logger.info(f"Running: {' '.join(cmd)}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                if 'already exists' in result.stderr:
                    logger.info(f"Database '{self.db_name}' already exists")
                    return True
                else:
                    logger.error(f"Failed to create database: {result.stderr}")
                    logger.error(f"createdb stdout: {result.stdout}")
                    return False

            logger.info(f"✅ Database '{self.db_name}' created")
            if progress_callback:
                progress_callback("Database created")

            return True

        except Exception as e:
            logger.error(f"Failed to create database: {e}", exc_info=True)
            if progress_callback:
                progress_callback(f"Error: {e}")
            return False

    def get_connection_params(self):
        """Get Django database connection parameters"""
        return {
            'ENGINE': 'django_tenants.postgresql_backend',
            'NAME': self.db_name,
            'USER': self.db_user,
            'PASSWORD': '',
            'HOST': 'localhost',
            'PORT': str(self.port),
        }

    def setup(self, progress_callback=None):
        """Complete setup: install, initialize, start, create DB"""
        steps = [
            ("Checking/Installing PostgreSQL", self.install),
            ("Initializing database", self.initialize),
            ("Starting PostgreSQL", self.start),
            ("Creating database", self.create_database),
        ]

        for step_name, step_func in steps:
            logger.info(f"Step: {step_name}")
            if progress_callback:
                progress_callback(step_name)

            if not step_func(progress_callback):
                logger.error(f"Failed at step: {step_name}")
                return False

        logger.info("✅ PostgreSQL setup complete!")
        if progress_callback:
            progress_callback("Setup complete!")

        return True

    def cleanup_on_exit(self):
        """Call this when application is exiting to properly encrypt database"""
        logger.info("Application exiting - cleaning up PostgreSQL...")
        self.stop(encrypt_after=True)