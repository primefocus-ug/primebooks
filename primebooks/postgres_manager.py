"""
Embedded PostgreSQL Manager for Desktop Mode - FINAL WORKING VERSION
✅ Properly handles encrypted database files
✅ Excludes config files from encryption
✅ Decrypts before initialization
✅ Encrypts on shutdown
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
from primebooks.security.encryption import get_encryption_manager


logger = logging.getLogger(__name__)


class EmbeddedPostgresManager:
    """
    Manages an embedded PostgreSQL instance for desktop mode.
    Uses portable PostgreSQL binaries - no system installation needed.

    ✅ FIXED: Properly handles encryption/decryption with config file exclusion
    """

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.postgres_dir = self.data_dir / 'postgresql'
        self.data_subdir = self.postgres_dir / 'data'
        self.bin_dir = self.postgres_dir / 'bin'
        self.port = 5433  # Non-standard port to avoid conflicts
        self.db_name = 'primebooks'
        self.db_user = 'primebooks_user'
        self.log_file = self.data_dir / 'postgresql.log'

        # Files to EXCLUDE from encryption (configuration files)
        self.encryption_exclude = [
            'postgresql.conf',
            'pg_hba.conf',
            'pg_ident.conf',
            'postgresql.auto.conf',
            'PG_VERSION',
        ]

        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.encryption = get_encryption_manager(self.data_dir)

    def _should_encrypt_file(self, file_path):
        """Check if a file should be encrypted"""
        # Skip config files
        if file_path.name in self.encryption_exclude:
            return False

        # Skip already encrypted files
        if file_path.suffix == '.enc':
            return False

        # Skip log files
        if file_path.suffix == '.log':
            return False

        # Skip temporary files
        if file_path.suffix == '.tmp':
            return False

        return True

    def get_postgres_url(self):
        """Get the download URL for PostgreSQL binaries for this platform"""
        system = platform.system()
        machine = platform.machine()

        # PostgreSQL 15.x portable binaries
        base_url = "https://get.enterprisedb.com/postgresql"

        if system == "Linux":
            if "x86_64" in machine or "amd64" in machine:
                return "https://ftp.postgresql.org/pub/binary/v15.5/linux/x64/postgresql-15.5-linux-x64-binaries.tar.gz"
            elif "aarch64" in machine or "arm64" in machine:
                return "https://ftp.postgresql.org/pub/binary/v15.5/linux/arm64/postgresql-15.5-linux-arm64-binaries.tar.gz"

        elif system == "Darwin":  # macOS
            return f"{base_url}/postgresql-15.5-1-osx-binaries.zip"
        elif system == "Windows":
            return f"{base_url}/postgresql-15.5-1-windows-x64-binaries.zip"

        raise Exception(f"Unsupported platform: {system} {machine}")

    def is_installed(self):
        """Check if PostgreSQL binaries are installed"""
        pg_ctl = self.bin_dir / ('pg_ctl.exe' if platform.system() == 'Windows' else 'pg_ctl')
        postgres = self.bin_dir / ('postgres.exe' if platform.system() == 'Windows' else 'postgres')
        return pg_ctl.exists() and postgres.exists()

    def install(self, progress_callback=None):
        """Download and install PostgreSQL binaries"""
        if self.is_installed():
            logger.info("PostgreSQL already installed")
            return True

        try:
            system = platform.system()

            if system == "Linux":
                # Use system package manager for Linux
                return self._install_linux_package(progress_callback)
            else:
                # Use portable binaries for Windows/macOS
                return self._install_portable(progress_callback)

        except Exception as e:
            logger.error(f"Failed to install PostgreSQL: {e}")
            if progress_callback:
                progress_callback(f"Error: {e}")
            return False

    def _install_linux_package(self, progress_callback=None):
        """Install PostgreSQL via system package manager on Linux"""
        logger.info("Installing PostgreSQL via system package manager...")
        if progress_callback:
            progress_callback("Installing PostgreSQL...")

        try:
            # Detect distribution
            distro = "ubuntu"  # You can enhance this with distro detection

            # Add PostgreSQL repository
            logger.info("Adding PostgreSQL repository...")
            subprocess.run([
                'sudo', 'apt', 'install', '-y',
                'postgresql-common', 'ca-certificates'
            ], check=True)

            # Use the automated repository setup script
            subprocess.run([
                'sudo', '/usr/share/postgresql-common/pgdg/apt.postgresql.org.sh', '-y'
            ], check=True)

            # Update package lists
            subprocess.run(['sudo', 'apt', 'update'], check=True)

            # Install PostgreSQL 16 (or whatever version you prefer)
            logger.info("Installing PostgreSQL 16...")
            subprocess.run([
                'sudo', 'apt', 'install', '-y',
                'postgresql-16', 'postgresql-client-16'
            ], check=True)

            # Copy binaries to our local directory for consistency
            self.postgres_dir.mkdir(parents=True, exist_ok=True)
            self.bin_dir.mkdir(parents=True, exist_ok=True)

            # Create symlinks to system binaries
            system_bin = Path('/usr/lib/postgresql/16/bin')
            for binary in system_bin.glob('*'):
                if binary.is_file():
                    link_path = self.bin_dir / binary.name
                    if not link_path.exists():
                        link_path.symlink_to(binary)

            logger.info("✅ PostgreSQL installed successfully")
            if progress_callback:
                progress_callback("PostgreSQL installed successfully")

            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to install PostgreSQL: {e}")
            return False

    def _install_portable(self, progress_callback=None):
        """Install portable PostgreSQL binaries for Windows/macOS"""
        logger.info("Downloading PostgreSQL binaries...")
        if progress_callback:
            progress_callback("Downloading PostgreSQL...")

        url = self.get_postgres_url()
        download_path = self.data_dir / 'postgres_download.tmp'

        # Download with progress
        response = requests.get(url, stream=True)
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

        # Extract based on file type
        if download_path.suffix == '.gz' or str(download_path).endswith('.tar.gz'):
            with tarfile.open(download_path, 'r:gz') as tar:
                tar.extractall(self.postgres_dir)
        else:
            with zipfile.ZipFile(download_path, 'r') as zip_ref:
                zip_ref.extractall(self.postgres_dir)

        # Move binaries to correct location if needed
        pgsql_dir = self.postgres_dir / 'pgsql'
        if pgsql_dir.exists():
            # Move contents up one level
            for item in pgsql_dir.iterdir():
                shutil.move(str(item), str(self.postgres_dir / item.name))
            pgsql_dir.rmdir()

        # Make binaries executable on Unix
        if platform.system() != 'Windows':
            for binary in self.bin_dir.glob('*'):
                if binary.is_file():
                    os.chmod(binary, 0o755)

        # Clean up download
        download_path.unlink()

        logger.info("✅ PostgreSQL installed successfully")
        if progress_callback:
            progress_callback("PostgreSQL installed successfully")

        return True

    def is_initialized(self):
        """Check if database cluster is initialized"""
        pg_version = self.data_subdir / 'PG_VERSION'
        return pg_version.exists()

    def _has_encrypted_files(self):
        """
        Check if data directory contains encrypted (.enc) files

        Returns:
            tuple: (has_encrypted: bool, file_count: int)
        """
        if not self.data_subdir.exists():
            return False, 0

        # Look for .enc files specifically
        enc_files = list(self.data_subdir.rglob('*.enc'))

        if enc_files:
            logger.info(f"Found {len(enc_files)} .enc files")
            return True, len(enc_files)

        return False, 0

    def _configure_postgres(self):
        """Configure PostgreSQL settings"""
        pg_conf = self.data_subdir / 'postgresql.conf'

        # Create a local directory for Unix sockets
        socket_dir = self.postgres_dir / 'sockets'
        socket_dir.mkdir(parents=True, exist_ok=True)

        # Read existing config if it exists
        if pg_conf.exists():
            with open(pg_conf, 'r') as f:
                existing_config = f.read()

            # Remove any existing custom settings
            if '# PrimeBooks Desktop Settings' in existing_config:
                existing_config = existing_config.split('# PrimeBooks Desktop Settings')[0]
        else:
            existing_config = ""

        # Write config with custom settings
        with open(pg_conf, 'w') as f:
            f.write(existing_config)
            f.write(f"""
# PrimeBooks Desktop Settings
port = {self.port}
listen_addresses = 'localhost'
max_connections = 50
shared_buffers = 128MB
dynamic_shared_memory_type = posix
logging_collector = on
log_directory = 'log'
log_filename = 'postgresql-%Y-%m-%d.log'
log_statement = 'all'
unix_socket_directories = '{socket_dir}'
""")

        # Configure authentication
        pg_hba = self.data_subdir / 'pg_hba.conf'
        with open(pg_hba, 'w') as f:
            f.write("""
# TYPE  DATABASE        USER            ADDRESS                 METHOD
local   all             all                                     trust
host    all             all             127.0.0.1/32            trust
host    all             all             ::1/128                 trust
""")

    def is_running(self):
        """Check if PostgreSQL server is running"""
        try:
            pg_ctl = self.bin_dir / ('pg_ctl.exe' if platform.system() == 'Windows' else 'pg_ctl')

            result = subprocess.run([
                str(pg_ctl),
                'status',
                '-D', str(self.data_subdir)
            ], capture_output=True, text=True)

            return result.returncode == 0

        except Exception:
            return False

    def start(self, progress_callback=None):
        """Start PostgreSQL server"""
        if self.is_running():
            logger.info("PostgreSQL already running")
            return True

        # ✅ CRITICAL: Decrypt database files before starting
        self._decrypt_database()

        try:
            logger.info(f"Starting PostgreSQL on port {self.port}...")
            if progress_callback:
                progress_callback("Starting PostgreSQL...")

            pg_ctl = self.bin_dir / ('pg_ctl.exe' if platform.system() == 'Windows' else 'pg_ctl')

            # Ensure log directory exists
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

            # Check if port is available
            if not self._is_port_available(self.port):
                logger.warning(f"Port {self.port} is in use, trying alternative ports...")
                for alt_port in range(5434, 5440):
                    if self._is_port_available(alt_port):
                        self.port = alt_port
                        self._configure_postgres()  # Update config with new port
                        logger.info(f"Using alternative port {self.port}")
                        break
                else:
                    raise Exception("No available ports found")

            result = subprocess.run([
                str(pg_ctl),
                'start',
                '-D', str(self.data_subdir),
                '-l', str(self.log_file),
                '-w',  # Wait for startup
                '-t', '30',  # Timeout 30 seconds
                '-o', f'-p {self.port}'  # Explicitly set port
            ], capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(f"Failed to start PostgreSQL: {result.stderr}")
                # Try to read the log file for more details
                if self.log_file.exists():
                    with open(self.log_file, 'r') as f:
                        log_content = f.read()
                        logger.error(f"PostgreSQL log:\n{log_content}")
                return False

            # Wait a bit more to ensure it's fully ready
            time.sleep(2)

            logger.info("✅ PostgreSQL started successfully")
            if progress_callback:
                progress_callback("PostgreSQL started")

            return True

        except Exception as e:
            logger.error(f"Failed to start PostgreSQL: {e}")
            if progress_callback:
                progress_callback(f"Error: {e}")
            return False

    def _encrypt_database(self):
        """
        Encrypt PostgreSQL data files
        ✅ Encrypts files and adds .enc extension
        ✅ EXCLUDES config files from encryption
        """
        if not self.data_subdir.exists():
            logger.info("No data directory to encrypt")
            return

        encrypted_count = 0
        skipped_count = 0
        failed_count = 0

        try:
            # Get all files in data directory
            all_files = [f for f in self.data_subdir.rglob('*') if f.is_file()]

            # Filter files to encrypt
            files_to_encrypt = [
                f for f in all_files
                if self._should_encrypt_file(f)
            ]

            if not files_to_encrypt:
                logger.info("No files to encrypt")
                return

            logger.info(f"Encrypting {len(files_to_encrypt)} database files (skipping {len(all_files) - len(files_to_encrypt)} config files)...")

            for file_path in files_to_encrypt:
                try:
                    # Encrypt the file in place
                    self.encryption.encrypt_file(file_path)

                    # Rename to .enc
                    enc_path = Path(str(file_path) + '.enc')
                    file_path.rename(enc_path)

                    encrypted_count += 1

                except Exception as e:
                    logger.error(f"Failed to encrypt {file_path}: {e}")
                    failed_count += 1

            if encrypted_count > 0:
                logger.info(f"✅ Encrypted {encrypted_count} database files")
            if failed_count > 0:
                logger.warning(f"⚠️ Failed to encrypt {failed_count} files")

        except Exception as e:
            logger.error(f"Encryption error: {e}", exc_info=True)

    def _decrypt_database(self):
        """
        Decrypt PostgreSQL data files
        ✅ Decrypts .enc files and removes .enc extension
        """
        if not self.data_subdir.exists():
            logger.info("No data directory to decrypt")
            return

        # Check if there are encrypted files
        has_encrypted, file_count = self._has_encrypted_files()
        if not has_encrypted:
            logger.info("No encrypted files to decrypt")
            return

        decrypted_count = 0
        failed_count = 0

        try:
            # Get all .enc files
            enc_files = list(self.data_subdir.rglob('*.enc'))

            logger.info(f"Decrypting {len(enc_files)} database files...")

            for enc_path in enc_files:
                try:
                    # Get the original filename (remove .enc extension)
                    original_path = Path(str(enc_path)[:-4])  # Remove last 4 chars (.enc)

                    # Decrypt to original location
                    self.encryption.decrypt_file(enc_path, original_path)

                    # Remove the .enc file
                    enc_path.unlink()

                    decrypted_count += 1

                except Exception as e:
                    logger.error(f"Failed to decrypt {enc_path}: {e}")
                    failed_count += 1

            if decrypted_count > 0:
                logger.info(f"✅ Decrypted {decrypted_count} database files")
            if failed_count > 0:
                logger.warning(f"⚠️ Failed to decrypt {failed_count} files")

        except Exception as e:
            logger.error(f"Decryption error: {e}", exc_info=True)

    def _is_port_available(self, port):
        """Check if a port is available"""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return True
        except OSError:
            return False

    def initialize(self, progress_callback=None):
        """
        Initialize PostgreSQL database cluster
        ✅ FIXED: Properly handles encrypted files before initialization
        """
        # ✅ CRITICAL FIX: Decrypt any existing encrypted files FIRST
        has_encrypted, file_count = self._has_encrypted_files()

        if has_encrypted:
            logger.info(f"Found {file_count} encrypted .enc files - decrypting before initialization...")
            if progress_callback:
                progress_callback("Decrypting existing database files...")

            self._decrypt_database()

            # After decryption, check if database is now properly initialized
            if self.is_initialized():
                logger.info("✅ Database is already initialized (after decryption)")
                if progress_callback:
                    progress_callback("Database already initialized")
                return True

        # Check if already initialized (after potential decryption)
        if self.is_initialized():
            logger.info("PostgreSQL already initialized")
            if progress_callback:
                progress_callback("Database already initialized")
            return True

        try:
            logger.info("Initializing PostgreSQL database cluster...")
            if progress_callback:
                progress_callback("Initializing database...")

            # Ensure data directory exists with correct permissions
            self.data_subdir.mkdir(parents=True, exist_ok=True)

            initdb = self.bin_dir / ('initdb.exe' if platform.system() == 'Windows' else 'initdb')

            result = subprocess.run([
                str(initdb),
                '-D', str(self.data_subdir),
                '-U', self.db_user,
                '--auth=trust',
                '--encoding=UTF8',
                '--locale=C'
            ], capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(f"initdb failed: {result.stderr}")
                logger.error(f"initdb stdout: {result.stdout}")
                return False

            # Configure PostgreSQL
            self._configure_postgres()

            logger.info("✅ PostgreSQL initialized successfully")
            if progress_callback:
                progress_callback("Database initialized")

            return True

        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL: {e}")
            if progress_callback:
                progress_callback(f"Error: {e}")
            return False

    def stop(self):
        """
        Stop PostgreSQL server
        ✅ FIXED: Properly encrypts database after stopping (excludes config files)
        """
        if not self.is_running():
            logger.info("PostgreSQL not running")
            return True

        try:
            logger.info("Stopping PostgreSQL...")

            pg_ctl = self.bin_dir / ('pg_ctl.exe' if platform.system() == 'Windows' else 'pg_ctl')

            result = subprocess.run([
                str(pg_ctl),
                'stop',
                '-D', str(self.data_subdir),
                '-m', 'fast'
            ], capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                logger.warning(f"PostgreSQL stop warning: {result.stderr}")
                # Continue anyway - might already be stopped

            # Wait for PostgreSQL to fully stop
            time.sleep(2)

            # ✅ Encrypt database files after stopping
            logger.info("Encrypting database files...")
            self._encrypt_database()

            logger.info("✅ PostgreSQL stopped")
            return True

        except Exception as e:
            logger.error(f"Failed to stop PostgreSQL: {e}")
            return False

    def create_database(self, progress_callback=None):
        """Create the main database"""
        try:
            logger.info(f"Creating database '{self.db_name}'...")
            if progress_callback:
                progress_callback("Creating database...")

            createdb = self.bin_dir / ('createdb.exe' if platform.system() == 'Windows' else 'createdb')

            result = subprocess.run([
                str(createdb),
                '-h', 'localhost',
                '-p', str(self.port),
                '-U', self.db_user,
                self.db_name
            ], capture_output=True, text=True)

            if result.returncode != 0:
                if 'already exists' in result.stderr:
                    logger.info(f"Database '{self.db_name}' already exists")
                    return True
                else:
                    logger.error(f"Failed to create database: {result.stderr}")
                    return False

            logger.info(f"✅ Database '{self.db_name}' created")
            if progress_callback:
                progress_callback("Database created")

            return True

        except Exception as e:
            logger.error(f"Failed to create database: {e}")
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
        """
        Complete setup: install, initialize, start, create DB
        ✅ FIXED: Proper order with encryption handling
        """
        steps = [
            ("Installing PostgreSQL", self.install),
            ("Initializing database", self.initialize),  # Now handles encrypted files
            ("Starting PostgreSQL", self.start),  # Decrypts before starting
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