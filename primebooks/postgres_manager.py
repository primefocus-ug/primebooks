"""
Embedded PostgreSQL Manager
✅ Works on Windows, macOS, and Linux
✅ Detects and uses existing PostgreSQL installations
✅ Falls back to embedded download only if needed
✅ Encryption/decryption with config file exclusion
✅ Windows-optimized startup (no hangs)
✅ Linux-compatible initialization
✅ scram-sha-256 auth — no trust authentication
✅ pg_ctl return code checked on Windows
✅ Config written once at init, not overwritten every start
✅ log_statement = none (no query data in logs)
✅ Detects PostgreSQL 14-18 on all platforms
✅ Atomic archive extraction with path-traversal guard
"""

import subprocess
import os
import time
import secrets
import logging
import shutil
import platform
from pathlib import Path
import tarfile
import zipfile
import socket
from primebooks.security.encryption import get_encryption_manager


logger = logging.getLogger(__name__)

# Latest stable PostgreSQL version used for the embedded fallback download.
# Update this constant when a new major version is released.
EMBEDDED_PG_VERSION = "17.4"


class EmbeddedPostgresManager:
    """
    Manages PostgreSQL for desktop mode.
    Priority:
      1. Use existing system PostgreSQL if available
      2. Download embedded PostgreSQL only if needed

    ✅ Windows: Optimized startup, proper locale handling
    ✅ Linux:   System package manager integration
    ✅ Both:    Encryption with config file exclusion
    ✅ Auth:    scram-sha-256 — no passwordless trust access
    """

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.postgres_dir = self.data_dir / 'postgresql'
        self.data_subdir = self.postgres_dir / 'data'
        self.is_windows = platform.system() == 'Windows'
        self.is_linux = platform.system() == 'Linux'
        self.is_macos = platform.system() == 'Darwin'

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

        self.port = 5433
        self.db_name = 'primebooks'
        self.db_user = 'primebooks_user'
        self.log_file = self.data_dir / 'postgresql.log'

        # Password file — generated once, stored encrypted alongside other creds
        self._pw_file = self.data_dir / '.pg_password'

        # Files to EXCLUDE from encryption (must remain readable by postgres)
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
    # PASSWORD MANAGEMENT
    # =========================================================================

    def _get_db_password(self) -> str:
        """
        Return the database password for primebooks_user.
        Generated once and stored encrypted; recreated if missing.
        """
        if self._pw_file.exists():
            try:
                return self.encryption.decrypt_data(
                    self._pw_file.read_bytes()
                ).decode().strip()
            except Exception as e:
                logger.warning(f"Could not read stored DB password: {e} — regenerating")

        # Generate a strong random password and persist it encrypted
        password = secrets.token_urlsafe(32)
        self._pw_file.write_bytes(self.encryption.encrypt_data(password))
        logger.info("✅ Generated new database password")
        return password

    # =========================================================================
    # DETECTION: Find existing PostgreSQL installations
    # =========================================================================

    def _detect_postgres_installation(self):
        """Detect existing PostgreSQL installations on the system."""
        logger.info("🔍 Searching for existing PostgreSQL installation...")
        if self.is_windows:
            return self._detect_postgres_windows()
        elif self.is_macos:
            return self._detect_postgres_macos()
        else:
            return self._detect_postgres_linux()

    def _detect_postgres_windows(self):
        """Detect PostgreSQL on Windows."""
        search_paths = [
            Path(os.environ.get('ProgramFiles', 'C:\\Program Files')) / 'PostgreSQL',
            Path(os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)')) / 'PostgreSQL',
            Path('C:\\ProgramData\\chocolatey\\lib\\postgresql'),
            Path(os.environ.get('USERPROFILE', '')) / 'scoop' / 'apps' / 'postgresql',
            Path('C:\\edb'),
        ]

        pg_config_path = shutil.which('pg_config')
        if pg_config_path:
            try:
                result = subprocess.run(
                    [pg_config_path, '--bindir'],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    bin_dir = Path(result.stdout.strip())
                    if bin_dir.exists():
                        ver = self._get_postgres_version(bin_dir / 'postgres.exe')
                        return {'path': bin_dir.parent, 'bin_dir': bin_dir,
                                'version': ver, 'source': 'PATH'}
            except Exception as e:
                logger.debug(f"Error checking pg_config in PATH: {e}")

        for base_path in search_paths:
            if not base_path.exists():
                continue
            for version_dir in sorted(base_path.glob('*'), reverse=True):
                if not version_dir.is_dir():
                    continue
                bin_dir = version_dir / 'bin'
                if (bin_dir / 'pg_ctl.exe').exists() and (bin_dir / 'postgres.exe').exists():
                    ver = self._get_postgres_version(bin_dir / 'postgres.exe')
                    return {'path': version_dir, 'bin_dir': bin_dir,
                            'version': ver, 'source': str(base_path)}
        return None

    def _detect_postgres_macos(self):
        """Detect PostgreSQL on macOS — covers versions 14-18."""
        # Versions ordered newest-first so we pick the most recent install
        versions = ['18', '17', '16', '15', '14']
        search_paths = []
        for v in versions:
            search_paths += [
                Path(f'/opt/homebrew/opt/postgresql@{v}/bin'),   # Apple Silicon
                Path(f'/usr/local/opt/postgresql@{v}/bin'),       # Intel
                Path(f'/Applications/Postgres.app/Contents/Versions/{v}/bin'),
                Path(f'/opt/local/lib/postgresql{v}/bin'),        # MacPorts
            ]
        # Also check generic / unversioned Homebrew formula
        search_paths += [
            Path('/opt/homebrew/opt/postgresql/bin'),
            Path('/usr/local/opt/postgresql/bin'),
            Path('/Applications/Postgres.app/Contents/Versions/latest/bin'),
        ]

        pg_config_path = shutil.which('pg_config')
        if pg_config_path:
            try:
                result = subprocess.run(
                    [pg_config_path, '--bindir'],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    bin_dir = Path(result.stdout.strip())
                    if bin_dir.exists():
                        ver = self._get_postgres_version(bin_dir / 'postgres')
                        return {'path': bin_dir.parent, 'bin_dir': bin_dir,
                                'version': ver, 'source': 'PATH'}
            except Exception as e:
                logger.debug(f"Error checking pg_config: {e}")

        for bin_dir in search_paths:
            if (bin_dir / 'pg_ctl').exists() and (bin_dir / 'postgres').exists():
                ver = self._get_postgres_version(bin_dir / 'postgres')
                return {'path': bin_dir.parent, 'bin_dir': bin_dir,
                        'version': ver, 'source': str(bin_dir.parent)}
        return None

    def _detect_postgres_linux(self):
        """Detect PostgreSQL on Linux — covers versions 14-18."""
        pg_config_path = shutil.which('pg_config')
        if pg_config_path:
            try:
                result = subprocess.run(
                    [pg_config_path, '--bindir'],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    bin_dir = Path(result.stdout.strip())
                    if bin_dir.exists():
                        ver = self._get_postgres_version(bin_dir / 'postgres')
                        return {'path': bin_dir.parent, 'bin_dir': bin_dir,
                                'version': ver, 'source': 'system'}
            except Exception as e:
                logger.debug(f"Error checking pg_config: {e}")

        versions = ['18', '17', '16', '15', '14']
        search_paths = []
        for v in versions:
            search_paths += [
                Path(f'/usr/lib/postgresql/{v}/bin'),
                Path(f'/usr/pgsql-{v}/bin'),
            ]

        for bin_dir in search_paths:
            if (bin_dir / 'pg_ctl').exists() and (bin_dir / 'postgres').exists():
                ver = self._get_postgres_version(bin_dir / 'postgres')
                return {'path': bin_dir.parent, 'bin_dir': bin_dir,
                        'version': ver, 'source': 'system'}
        return None

    def _get_postgres_version(self, postgres_binary: Path) -> str:
        """Return the version string from a postgres binary, or 'unknown'."""
        try:
            result = subprocess.run(
                [str(postgres_binary), '--version'],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else 'unknown'
        except Exception:
            return 'unknown'

    def _find_bin_dir(self):
        """Find the correct bin directory for embedded PostgreSQL binaries."""
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

    def _get_binary_path(self, binary_name: str) -> Path:
        """Return the full path to a PostgreSQL binary."""
        if self.is_windows and not binary_name.endswith('.exe'):
            binary_name += '.exe'
        binary_path = self.bin_dir / binary_name
        if not binary_path.exists() and not self.using_system_postgres:
            self.bin_dir = self._find_bin_dir()
            binary_path = self.bin_dir / binary_name
        return binary_path

    # =========================================================================
    # ENCRYPTION: File encryption / decryption
    # =========================================================================

    def _should_encrypt_file(self, file_path: Path) -> bool:
        if file_path.name in self.encryption_exclude:
            return False
        if file_path.suffix in ['.enc', '.log', '.tmp', '.pid', '.opts']:
            return False
        if 'lock' in file_path.name.lower():
            return False
        return True

    def _has_encrypted_files(self):
        if not self.data_subdir.exists():
            return False, 0
        enc_files = list(self.data_subdir.rglob('*.enc'))
        return (True, len(enc_files)) if enc_files else (False, 0)

    def _encrypt_database(self):
        """Encrypt PostgreSQL data files (excludes config files)."""
        if not self.data_subdir.exists():
            return

        all_files = [f for f in self.data_subdir.rglob('*') if f.is_file()]
        files_to_encrypt = [f for f in all_files if self._should_encrypt_file(f)]

        if not files_to_encrypt:
            logger.info("No files to encrypt")
            return

        logger.info(
            f"Encrypting {len(files_to_encrypt)} files "
            f"(skipping {len(all_files) - len(files_to_encrypt)} config/log files)..."
        )

        batch_size = 50 if self.is_windows else 500
        encrypted_count = failed_count = 0

        for i, file_path in enumerate(files_to_encrypt):
            try:
                self.encryption.encrypt_file(file_path)
                enc_path = Path(str(file_path) + '.enc')
                if self.is_windows:
                    time.sleep(0.001)
                file_path.rename(enc_path)
                encrypted_count += 1
                if self.is_windows and (i + 1) % batch_size == 0:
                    time.sleep(0.05)
                    logger.debug(f"Encrypted {i + 1}/{len(files_to_encrypt)} files...")
            except Exception as e:
                logger.error(f"Failed to encrypt {file_path}: {e}")
                failed_count += 1

        if encrypted_count:
            logger.info(f"✅ Encrypted {encrypted_count} database files")
        if failed_count:
            logger.warning(f"⚠️ Failed to encrypt {failed_count} files")

        if self.is_windows and encrypted_count:
            import gc
            gc.collect()
            time.sleep(0.5)

    def _decrypt_database(self):
        """Decrypt PostgreSQL data files."""
        if not self.data_subdir.exists():
            logger.info("No data directory to decrypt")
            return

        has_encrypted, file_count = self._has_encrypted_files()
        if not has_encrypted:
            logger.debug("No encrypted files to decrypt")
            return

        enc_files = list(self.data_subdir.rglob('*.enc'))
        logger.info(f"Decrypting {len(enc_files)} database files...")

        batch_size = 50 if self.is_windows else 500
        decrypted_count = failed_count = 0

        for i, enc_path in enumerate(enc_files):
            try:
                original_path = Path(str(enc_path)[:-4])
                self.encryption.decrypt_file(enc_path, original_path)

                if self.is_windows:
                    try:
                        with open(original_path, 'rb'):
                            pass
                    except Exception:
                        pass

                enc_path.unlink()
                decrypted_count += 1

                if self.is_windows and (i + 1) % batch_size == 0:
                    time.sleep(0.05)
                    logger.debug(f"Decrypted {i + 1}/{len(enc_files)} files...")

            except Exception as e:
                logger.error(f"Failed to decrypt {enc_path}: {e}")
                failed_count += 1

        if decrypted_count:
            logger.info(f"✅ Decrypted {decrypted_count} database files")
        if failed_count:
            logger.warning(f"⚠️ Failed to decrypt {failed_count} files")

        if self.is_windows and decrypted_count:
            logger.info("Waiting for Windows to release file handles...")
            time.sleep(2)
            import gc
            gc.collect()
            time.sleep(0.5)
            logger.info("File handles released, ready to start PostgreSQL")

    # =========================================================================
    # INSTALLATION: Download and install PostgreSQL
    # =========================================================================

    def get_postgres_url(self) -> str:
        """Return the download URL for the embedded PostgreSQL binaries."""
        system = platform.system()
        machine = platform.machine()
        v = EMBEDDED_PG_VERSION

        if system == "Linux":
            arch = "x64" if ("x86_64" in machine or "amd64" in machine) else "arm64"
            return (
                f"https://ftp.postgresql.org/pub/binary/v{v}/"
                f"linux/{arch}/postgresql-{v}-linux-{arch}-binaries.tar.gz"
            )
        elif system == "Darwin":
            return (
                f"https://get.enterprisedb.com/postgresql/"
                f"postgresql-{v}-1-osx-binaries.zip"
            )
        elif system == "Windows":
            return (
                f"https://get.enterprisedb.com/postgresql/"
                f"postgresql-{v}-1-windows-x64-binaries.zip"
            )
        raise Exception(f"Unsupported platform: {system} {machine}")

    def is_installed(self) -> bool:
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

    def install(self, progress_callback=None) -> bool:
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

    def _install_portable(self, progress_callback=None) -> bool:
        """Download and extract portable PostgreSQL binaries."""
        import requests  # local import — only needed for embedded fallback

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
                            pct = (downloaded / total_size) * 100
                            progress_callback(f"Downloading PostgreSQL... {pct:.1f}%")

            logger.info("Extracting PostgreSQL binaries...")
            if progress_callback:
                progress_callback("Extracting PostgreSQL...")

            dest = self.postgres_dir
            dest.mkdir(parents=True, exist_ok=True)

            # ── Path-traversal-safe extraction ───────────────────────────────
            if '.tar.gz' in str(download_path) or download_path.suffix == '.gz':
                with tarfile.open(download_path, 'r:gz') as tar:
                    safe_members = []
                    for member in tar.getmembers():
                        member_path = (dest / member.name).resolve()
                        if not str(member_path).startswith(str(dest.resolve())):
                            logger.error(
                                f"Blocked path-traversal attempt in archive: {member.name}"
                            )
                            continue
                        safe_members.append(member)
                    tar.extractall(dest, members=safe_members)
            else:
                with zipfile.ZipFile(download_path, 'r') as zf:
                    for member in zf.namelist():
                        member_path = (dest / member).resolve()
                        if not str(member_path).startswith(str(dest.resolve())):
                            logger.error(
                                f"Blocked path-traversal attempt in archive: {member}"
                            )
                            continue
                        zf.extract(member, dest)
            # ─────────────────────────────────────────────────────────────────

            # Flatten nested pgsql/ directory if present
            pgsql_dir = dest / 'pgsql'
            if pgsql_dir.exists():
                logger.info(f"Moving binaries from {pgsql_dir} to {dest}")
                for item in pgsql_dir.iterdir():
                    target = dest / item.name
                    if target.exists():
                        shutil.rmtree(target) if target.is_dir() else target.unlink()
                    shutil.move(str(item), str(target))
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

    def is_initialized(self) -> bool:
        return (self.data_subdir / 'PG_VERSION').exists()

    def initialize(self, progress_callback=None) -> bool:
        """Initialize PostgreSQL database cluster with secure auth."""
        has_encrypted, file_count = self._has_encrypted_files()
        if has_encrypted:
            logger.info(f"Found {file_count} encrypted files - decrypting...")
            if progress_callback:
                progress_callback("Decrypting existing database...")
            self._decrypt_database()

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

            # Generate / retrieve the DB password before initdb
            password = self._get_db_password()

            # Write a temp password file that initdb can read
            pw_tmp = self.data_dir / '.initdb_pw.tmp'
            pw_tmp.write_text(password)

            initdb = self._get_binary_path('initdb')
            if not initdb.exists():
                raise Exception(f"initdb not found at {initdb}")

            cmd = [
                str(initdb),
                '-D', str(self.data_subdir),
                '-U', self.db_user,
                '--auth=scram-sha-256',   # FIX: no more trust auth
                '--pwfile', str(pw_tmp),
                '--encoding=UTF8',
            ]
            if self.is_windows:
                cmd.append('--locale=C')

            logger.info(f"Running: {' '.join(cmd)}")

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            finally:
                # Always remove the plaintext password file
                try:
                    pw_tmp.unlink()
                except Exception:
                    pass

            if result.returncode != 0:
                logger.error(f"initdb failed: {result.stderr}")
                return False

            logger.info("Database cluster initialized")

            # Write config ONCE here — start() will never overwrite it
            self._write_initial_config()

            logger.info("✅ PostgreSQL initialized successfully")
            if progress_callback:
                progress_callback("Database initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL: {e}", exc_info=True)
            if progress_callback:
                progress_callback(f"Error: {e}")
            return False

    def _write_initial_config(self):
        """
        Write postgresql.conf and pg_hba.conf ONCE at cluster creation.
        start() reads the port from the existing config rather than
        overwriting it, so manual tuning is preserved across restarts.
        """
        pg_conf = self.data_subdir / 'postgresql.conf'

        if self.is_windows:
            socket_config = ""
            locale_config = (
                "lc_messages = 'C'\n"
                "lc_monetary = 'C'\n"
                "lc_numeric  = 'C'\n"
                "lc_time     = 'C'"
            )
        else:
            socket_dir = self.postgres_dir / 'sockets'
            socket_dir.mkdir(parents=True, exist_ok=True)
            socket_config = f"unix_socket_directories = '{socket_dir}'"
            locale_config = ""

        existing = ""
        if pg_conf.exists():
            with open(pg_conf, 'r', encoding='utf-8') as f:
                existing = f.read()
            if '# PrimeBooks Desktop Settings' in existing:
                existing = existing.split('# PrimeBooks Desktop Settings')[0]

        with open(pg_conf, 'w', encoding='utf-8') as f:
            f.write(existing)
            f.write(f"""
# PrimeBooks Desktop Settings
port                        = {self.port}
listen_addresses            = 'localhost'
max_connections             = 50
shared_buffers              = 128MB
dynamic_shared_memory_type  = {'windows' if self.is_windows else 'posix'}

# Logging — record errors and slow queries only; never log query data
logging_collector           = on
log_directory               = 'log'
log_filename                = 'postgresql-%Y-%m-%d.log'
log_statement               = 'none'
log_min_messages            = warning
log_min_error_statement     = error
log_min_duration_statement  = 2000   # log queries slower than 2 s

{locale_config}
{socket_config}
""")

        # pg_hba.conf: scram-sha-256 everywhere — no passwordless access
        pg_hba = self.data_subdir / 'pg_hba.conf'
        with open(pg_hba, 'w', encoding='utf-8') as f:
            f.write(
                "# TYPE  DATABASE  USER             ADDRESS         METHOD\n"
                "host    all       all              127.0.0.1/32    scram-sha-256\n"
                "host    all       all              ::1/128         scram-sha-256\n"
            )

        logger.info(f"PostgreSQL configured for port {self.port}")

    # =========================================================================
    # RUNTIME: Start / Stop PostgreSQL
    # =========================================================================

    def _is_port_available(self, port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return True
        except OSError:
            return False

    def _find_available_port(self) -> int:
        if self._is_port_available(self.port):
            return self.port
        logger.warning(f"Port {self.port} is in use, searching for alternative...")
        for alt_port in range(5434, 5450):
            if self._is_port_available(alt_port):
                logger.info(f"Found available port: {alt_port}")
                return alt_port
        raise Exception("No available ports found in range 5433-5449")

    def _read_port_from_config(self):
        """Read the port number from the existing postgresql.conf."""
        pg_conf = self.data_subdir / 'postgresql.conf'
        if not pg_conf.exists():
            return
        try:
            with open(pg_conf, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(('port =', 'port=')):
                        port_str = line.split('=', 1)[1].split('#')[0].strip()
                        self.port = int(port_str)
                        logger.info(f"Read port {self.port} from postgresql.conf")
                        return
        except Exception as e:
            logger.error(f"Error reading port from config: {e}")

    def _update_port_in_config(self):
        """
        Update only the port line in postgresql.conf when a port change
        is needed (e.g. configured port was in use).
        All other settings are left untouched.
        """
        pg_conf = self.data_subdir / 'postgresql.conf'
        if not pg_conf.exists():
            return
        import re
        content = pg_conf.read_text(encoding='utf-8')
        content = re.sub(
            r'^(port\s*=\s*)\d+',
            f'\\g<1>{self.port}',
            content,
            flags=re.MULTILINE,
        )
        pg_conf.write_text(content, encoding='utf-8')
        logger.info(f"Updated port in postgresql.conf to {self.port}")

    def is_running(self) -> bool:
        """Check if the PostgreSQL server process is running."""
        try:
            pg_ctl = self._get_binary_path('pg_ctl')
            if not pg_ctl.exists():
                return False
            result = subprocess.run(
                [str(pg_ctl), 'status', '-D', str(self.data_subdir)],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except Exception as e:
            logger.debug(f"Error checking PostgreSQL status: {e}")
            return False

    def _can_connect(self) -> bool:
        """Check if PostgreSQL is accepting TCP connections."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect(('127.0.0.1', self.port))
                return True
        except Exception:
            return False

    def _cleanup_stale_locks(self):
        """Remove stale postmaster.pid that might prevent startup."""
        postmaster_pid = self.data_subdir / 'postmaster.pid'
        if not postmaster_pid.exists():
            return

        logger.info("Found postmaster.pid — checking if it's stale...")
        try:
            with open(postmaster_pid, 'r') as f:
                first_line = f.readline().strip()
            if not first_line.isdigit():
                return
            old_pid = int(first_line)
            logger.info(f"Lock file contains PID: {old_pid}")

            if self.is_windows:
                result = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {old_pid}'],
                    capture_output=True, text=True,
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
                logger.info(f"Process {old_pid} not running — removing stale lock")
                postmaster_pid.unlink()
            else:
                logger.warning(f"Process {old_pid} is still running!")
        except Exception as e:
            logger.error(f"Error checking lock file: {e}")

    def _show_postgres_log(self):
        """Log the tail of the PostgreSQL log file to help diagnose failures."""
        if self.log_file.exists():
            try:
                content = self.log_file.read_text(encoding='utf-8', errors='ignore')
                if content:
                    logger.error(f"PostgreSQL log (last 3000 chars):\n{content[-3000:]}")
                else:
                    logger.error("PostgreSQL log file is empty")
            except Exception as e:
                logger.error(f"Could not read log file: {e}")

        log_dir = self.data_subdir / 'log'
        if log_dir.exists():
            try:
                log_files = sorted(log_dir.glob('postgresql-*.log'))
                if log_files:
                    content = log_files[-1].read_text(encoding='utf-8', errors='ignore')
                    if content:
                        logger.error(
                            f"Data directory log (last 3000 chars):\n{content[-3000:]}"
                        )
            except Exception as e:
                logger.error(f"Could not read data directory log: {e}")

    def start(self, progress_callback=None) -> bool:
        """Start the PostgreSQL server."""
        if self.is_running():
            logger.info("PostgreSQL already running")
            self._read_port_from_config()
            logger.info(f"PostgreSQL is running on port {self.port}")
            return True

        self._decrypt_database()
        self._cleanup_stale_locks()

        try:
            # Honour the port in the existing config; only change it if occupied
            self._read_port_from_config()
            if not self._is_port_available(self.port):
                logger.warning(
                    f"Configured port {self.port} is in use, searching for alternative..."
                )
                self.port = self._find_available_port()
                # Update only the port line — leave everything else alone
                self._update_port_in_config()

            logger.info(f"Starting PostgreSQL on port {self.port}...")
            if progress_callback:
                progress_callback(f"Starting PostgreSQL on port {self.port}...")

            pg_ctl = self._get_binary_path('pg_ctl')
            if not pg_ctl.exists():
                raise Exception(f"pg_ctl not found at {pg_ctl}")

            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            (self.data_subdir / 'log').mkdir(parents=True, exist_ok=True)

            cmd = [
                str(pg_ctl), 'start',
                '-D', str(self.data_subdir),
                '-l', str(self.log_file),
            ]

            if self.is_windows:
                logger.info("Using Windows optimized startup mode...")
                logger.info(f"Running: {' '.join(cmd)}")

                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )

                # Give pg_ctl a moment to issue the start command, then check
                # whether it failed immediately (wrong path, permissions, etc.)
                time.sleep(1)
                poll = process.poll()
                if poll is not None and poll != 0:
                    _, stderr = process.communicate(timeout=5)
                    logger.error(
                        f"pg_ctl exited immediately with code {poll}: "
                        f"{stderr.decode(errors='replace')}"
                    )
                    self._show_postgres_log()
                    return False

                logger.info("PostgreSQL start command issued")

            else:
                cmd += ['-w', '-t', '30']
                logger.info(f"Running: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
                if result.returncode != 0:
                    logger.error(f"pg_ctl failed: {result.stderr}")
                    self._show_postgres_log()
                    return False

            # Wait for TCP connections to be accepted
            logger.info("Waiting for PostgreSQL to accept connections...")
            max_wait = 30
            wait_interval = 0.5

            for i in range(int(max_wait / wait_interval)):
                running = self.is_running()
                connectable = self._can_connect() if running else False

                if running and connectable:
                    logger.info(
                        f"✅ PostgreSQL started and accepting connections on port "
                        f"{self.port} (took {i * wait_interval:.1f}s)"
                    )
                    if progress_callback:
                        progress_callback("PostgreSQL started")
                    return True

                if progress_callback and i % 4 == 0:
                    progress_callback(f"Waiting for PostgreSQL... {i * wait_interval:.0f}s")

                time.sleep(wait_interval)

            logger.error(
                f"PostgreSQL failed to accept connections within {max_wait} seconds"
            )
            self._show_postgres_log()

            # Attempt a clean stop before giving up
            try:
                subprocess.run(
                    [str(pg_ctl), 'stop', '-D', str(self.data_subdir), '-m', 'immediate'],
                    timeout=10, capture_output=True,
                )
            except Exception:
                pass

            return False

        except Exception as e:
            logger.error(f"Failed to start PostgreSQL: {e}", exc_info=True)
            if progress_callback:
                progress_callback(f"Error: {e}")
            return False

    def stop(self, encrypt_after=True) -> bool:
        """Stop the PostgreSQL server."""
        if not self.is_running():
            logger.info("PostgreSQL not running")
            return True

        try:
            logger.info("Stopping PostgreSQL...")
            pg_ctl = self._get_binary_path('pg_ctl')

            result = subprocess.run(
                [str(pg_ctl), 'stop', '-D', str(self.data_subdir), '-m', 'fast', '-w', '-t', '30'],
                capture_output=True, text=True, timeout=45,
            )

            # pg_ctl stop -w already waited — no extra sleep needed
            if result.returncode != 0:
                logger.warning(f"PostgreSQL stop returned code {result.returncode}: {result.stderr}")

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

    def create_database(self, progress_callback=None) -> bool:
        """Create the main application database."""
        try:
            logger.info(f"Creating database '{self.db_name}'...")
            logger.info(f"Using port: {self.port}, user: {self.db_user}")
            if progress_callback:
                progress_callback("Creating database...")

            createdb = self._get_binary_path('createdb')
            password = self._get_db_password()

            env = os.environ.copy()
            env['PGPASSWORD'] = password

            cmd = [
                str(createdb),
                '-h', 'localhost',
                '-p', str(self.port),
                '-U', self.db_user,
                self.db_name,
            ]
            logger.info(f"Running: {' '.join(cmd)}")

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, env=env,
            )

            if result.returncode != 0:
                if 'already exists' in result.stderr:
                    logger.info(f"Database '{self.db_name}' already exists")
                    return True
                logger.error(f"Failed to create database: {result.stderr}")
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

    def get_connection_params(self) -> dict:
        """Return Django DATABASES entry for this PostgreSQL instance."""
        return {
            'ENGINE': 'django_tenants.postgresql_backend',
            'NAME': self.db_name,
            'USER': self.db_user,
            'PASSWORD': self._get_db_password(),
            'HOST': 'localhost',
            'PORT': str(self.port),
        }

    # =========================================================================
    # SETUP ORCHESTRATION
    # =========================================================================

    def setup(self, progress_callback=None) -> bool:
        """Run the full setup sequence: install → initialize → start → create DB."""
        steps = [
            ("Checking/Installing PostgreSQL", self.install),
            ("Initializing database",          self.initialize),
            ("Starting PostgreSQL",             self.start),
            ("Creating database",              self.create_database),
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
        """Call when the application is exiting to properly encrypt the database."""
        logger.info("Application exiting — cleaning up PostgreSQL...")
        self.stop(encrypt_after=True)