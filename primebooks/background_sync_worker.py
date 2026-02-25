"""
Enhanced Background Sync Worker
✅ Pause/Resume support
✅ Detailed progress tracking
✅ Better error handling
✅ Cancellation support
✅ Progress persistence
"""
import logging
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition
from datetime import datetime
import time

logger = logging.getLogger(__name__)


class BackgroundSyncWorker(QThread):
    """
    Enhanced background worker for data synchronization
    Supports pause/resume and detailed progress tracking
    """

    # Signals
    sync_started = pyqtSignal(dict)
    phase_changed = pyqtSignal(str, str)
    model_started = pyqtSignal(str, int, int)
    model_progress = pyqtSignal(str, int, int, int)
    model_completed = pyqtSignal(str, int, int)
    overall_progress = pyqtSignal(int, str)
    error_occurred = pyqtSignal(str, str)
    warning_occurred = pyqtSignal(str, str)
    sync_completed = pyqtSignal(bool, dict)

    # Additional signals
    paused = pyqtSignal()
    resumed = pyqtSignal()

    def __init__(self, tenant_id, schema_name, auth_token, sync_type="full"):
        super().__init__()

        self.tenant_id = tenant_id
        self.schema_name = schema_name
        self.auth_token = auth_token
        self.sync_type = sync_type

        # Control flags
        self._is_cancelled = False
        self._is_paused = False

        # Thread synchronization
        self._pause_mutex = QMutex()
        self._pause_condition = QWaitCondition()

        # Progress tracking
        self.start_time = None
        self.total_created = 0
        self.total_updated = 0
        self.total_errors = 0

        # Model tracking
        self.current_model = ""
        self.models_total = 0
        self.models_completed = 0

    def cancel(self):
        """Cancel the sync operation"""
        self._is_cancelled = True
        logger.info("🛑 Sync cancellation requested")

        # Wake up if paused
        if self._is_paused:
            self.resume()

    def pause(self):
        """Pause the sync operation"""
        if not self._is_paused:
            self._is_paused = True
            logger.info("⏸️ Sync paused")
            self.paused.emit()

    def resume(self):
        """Resume the sync operation"""
        if self._is_paused:
            self._is_paused = False
            self._pause_mutex.lock()
            self._pause_condition.wakeAll()
            self._pause_mutex.unlock()
            logger.info("▶️ Sync resumed")
            self.resumed.emit()

    def check_pause(self):
        """Check if paused and wait if necessary. Guards the flag read with the mutex."""
        self._pause_mutex.lock()
        is_paused = self._is_paused
        self._pause_mutex.unlock()

        if is_paused:
            self._pause_mutex.lock()
            self._pause_condition.wait(self._pause_mutex)
            self._pause_mutex.unlock()

    def check_cancelled(self):
        """Check if cancelled"""
        return self._is_cancelled

    def run(self):
        """Execute sync in background thread"""
        try:
            self.start_time = datetime.now()

            # Emit sync started
            self.sync_started.emit({
                'timestamp': self.start_time.isoformat(),
                'type': self.sync_type,
                'tenant': self.schema_name,
            })

            # Initialize sync manager
            from primebooks.sync import SyncManager

            sync_manager = SyncManager(
                tenant_id=self.tenant_id,
                schema_name=self.schema_name,
                auth_token=self.auth_token
            )

            # Check connection
            self.phase_changed.emit("connection", "🔌 Checking server connection...")
            self.overall_progress.emit(5, "Checking connection...")

            if self.check_cancelled():
                self._handle_cancellation()
                return

            if not sync_manager.is_online():
                self.error_occurred.emit(
                    "Connection",
                    "Server is not reachable. Please check your internet connection."
                )
                self.sync_completed.emit(False, {
                    'error': 'offline',
                    'message': 'Server not reachable'
                })
                return

            # Execute sync based on type
            if self.sync_type == "full":
                self._run_full_sync(sync_manager)
            elif self.sync_type == "download":
                self._run_download_sync(sync_manager)
            elif self.sync_type == "upload":
                self._run_upload_sync(sync_manager)
            else:
                raise ValueError(f"Unknown sync type: {self.sync_type}")

        except Exception as e:
            logger.error(f"❌ Sync error: {e}", exc_info=True)
            self.error_occurred.emit("Sync", str(e))
            self.sync_completed.emit(False, {
                'error': 'exception',
                'message': str(e)
            })

    def _run_full_sync(self, sync_manager):
        """Run full bidirectional sync"""
        try:
            # Phase 1: Upload
            self.phase_changed.emit("upload", "📤 Uploading local changes")
            self.overall_progress.emit(10, "Uploading local changes...")

            self.check_pause()
            if self.check_cancelled():
                self._handle_cancellation()
                return

            upload_success = self._upload_with_progress(sync_manager)

            if not upload_success:
                # Warn but continue — download may still succeed and upload
                # will be retried on the next sync cycle.
                logger.warning("⚠️ Upload failed — continuing with download anyway")
                self.warning_occurred.emit("Upload", "Failed to upload local changes — will retry next sync")

            # Phase 2: Download
            self.phase_changed.emit("download", "📥 Downloading server changes")
            self.overall_progress.emit(40, "Downloading server changes...")

            self.check_pause()
            if self.check_cancelled():
                self._handle_cancellation()
                return

            download_success = self._download_with_progress(sync_manager)

            if not download_success:
                self.error_occurred.emit("Download", "Failed to download server changes")
                self.sync_completed.emit(False, {'error': 'download_failed'})
                return

            # Phase 3: Finalize
            self.phase_changed.emit("finalize", "✨ Finalizing synchronization")
            self.overall_progress.emit(95, "Finalizing...")

            sync_manager.update_last_sync_time()

            # Complete
            self.overall_progress.emit(100, "✅ Sync complete!")

            duration = (datetime.now() - self.start_time).total_seconds()

            summary = {
                'success': True,
                'duration': duration,
                'created': self.total_created,
                'updated': self.total_updated,
                'errors': self.total_errors,
                'upload_failed': not upload_success,
            }

            self.sync_completed.emit(True, summary)

        except Exception as e:
            logger.error(f"Full sync error: {e}", exc_info=True)
            self.error_occurred.emit("Full Sync", str(e))
            self.sync_completed.emit(False, {'error': str(e)})

    def _run_download_sync(self, sync_manager):
        """Run download-only sync"""
        try:
            self.phase_changed.emit("download", "📥 Downloading data")

            success = self._download_with_progress(sync_manager)

            if success and not self.check_cancelled():
                duration = (datetime.now() - self.start_time).total_seconds()
                summary = {
                    'success': True,
                    'duration': duration,
                    'created': self.total_created,
                    'updated': self.total_updated,
                }
                self.sync_completed.emit(True, summary)
            elif self.check_cancelled():
                self._handle_cancellation()
            else:
                self.sync_completed.emit(False, {'error': 'Download failed'})

        except Exception as e:
            logger.error(f"Download sync error: {e}", exc_info=True)
            self.sync_completed.emit(False, {'error': str(e)})

    def _run_upload_sync(self, sync_manager):
        """Run upload-only sync"""
        try:
            self.phase_changed.emit("upload", "📤 Uploading data")

            success = self._upload_with_progress(sync_manager)

            if success and not self.check_cancelled():
                duration = (datetime.now() - self.start_time).total_seconds()
                summary = {
                    'success': True,
                    'duration': duration,
                    'uploaded': self.total_created + self.total_updated,
                }
                self.sync_completed.emit(True, summary)
            elif self.check_cancelled():
                self._handle_cancellation()
            else:
                self.sync_completed.emit(False, {'error': 'Upload failed'})

        except Exception as e:
            logger.error(f"Upload sync error: {e}", exc_info=True)
            self.sync_completed.emit(False, {'error': str(e)})

    def _upload_with_progress(self, sync_manager):
        from django_tenants.utils import schema_context

        try:
            last_sync = sync_manager.get_last_sync_time()
            logger.info(f"📤 _upload_with_progress — last_sync={last_sync}")

            changes = sync_manager.collect_local_changes(last_sync)

            if not changes:
                logger.info("📤 No local changes to upload")
                self.overall_progress.emit(40, "No local changes to upload")
                return True

            total_records = sum(len(records) for records in changes.values())
            logger.info(f"📤 Uploading {total_records} records across {len(changes)} models")
            self.overall_progress.emit(15, f"Uploading {total_records} records...")

            url = f"{sync_manager.server_url}/api/desktop/sync/upload/"
            upload_data = {
                "tenant_id": self.tenant_id,
                "schema_name": self.schema_name,
                "changes": changes,
                "last_sync": last_sync.isoformat() if last_sync else None,
            }

            logger.info(f"📡 POST {url}")
            response = sync_manager._make_request(url, method='POST', data=upload_data)

            if not response:
                logger.error("❌ Upload failed: no response (connection error or timeout)")
                return False

            logger.info(f"📥 Upload response: HTTP {response.status_code}")

            if response.status_code != 200:
                logger.error(f"❌ Upload HTTP {response.status_code}: {response.text[:300]}")
                return False

            try:
                result = response.json()
            except Exception as e:
                logger.error(f"❌ Could not parse upload response: {e} — raw: {response.text[:300]}")
                return False

            logger.info(f"📥 Upload result: success={result.get('success')}")

            if not result.get('success'):
                logger.error(f"❌ Server rejected upload: {result.get('error', 'no error message')}")
                logger.error(f"   Full response: {result}")
                return False

            # Mark records as synced ONLY after server confirms
            logger.info("✅ Upload confirmed — marking records as synced")
            with schema_context(self.schema_name):
                for model_name, records in changes.items():
                    ids = [r['pk'] for r in records]
                    sync_manager._mark_as_synced(model_name, ids)

            # Save the sync timestamp so next collect_local_changes uses the right window
            sync_manager.update_last_sync_time()

            logger.info(f"✅ Upload complete: {total_records} records")
            return True

        except Exception as e:
            logger.error(f"❌ Upload error: {e}", exc_info=True)
            return False

    def _download_with_progress(self, sync_manager):
        """Download with progress tracking"""
        try:
            last_sync = sync_manager.get_last_sync_time()

            # Get changes from server
            url = f"{sync_manager.server_url}/api/desktop/sync/changes/"
            params = {'since': last_sync.isoformat()} if last_sync else {}

            response = sync_manager._make_request(url, method='GET', params=params)

            if not response or response.status_code != 200:
                return False

            data = response.json()
            if not data.get('success', True):
                return False

            changes = data.get('data', {})
            total_records = sum(len(records) for records in changes.values())

            if total_records == 0:
                self.overall_progress.emit(70, "No server changes to download")
                return True

            self.models_total = len(changes)

            # Apply changes
            return self._apply_with_progress(sync_manager, changes)

        except Exception as e:
            logger.error(f"Download error: {e}")
            return False

    def _apply_with_progress(self, sync_manager, all_data):
        """Apply data with detailed progress tracking"""
        from django_tenants.utils import schema_context
        from primebooks.sync import suppress_signals

        total_models = len(all_data)

        try:
            with suppress_signals():
                with schema_context(self.schema_name):
                    for index, (model_name, records) in enumerate(all_data.items()):
                        # Check pause
                        self.check_pause()

                        # Check cancel
                        if self.check_cancelled():
                            return False

                        self.current_model = model_name
                        self.models_completed = index

                        # Emit model started
                        self.model_started.emit(model_name, index + 1, total_models)

                        # Calculate progress
                        base_progress = 50
                        progress_range = 45
                        model_progress = int(base_progress + (index / total_models) * progress_range)

                        self.overall_progress.emit(
                            model_progress,
                            f"Applying {model_name} ({index + 1}/{total_models})..."
                        )

                        # Apply model data
                        try:
                            created, updated = sync_manager.apply_model_data(model_name, records)

                            self.total_created += created
                            self.total_updated += updated

                            # Emit progress
                            self.model_progress.emit(model_name, created, updated, len(records))

                            # Emit completed
                            self.model_completed.emit(model_name, created, updated)

                            # Small delay to allow UI updates
                            self.msleep(50)

                        except Exception as e:
                            error_msg = str(e)[:200]
                            self.error_occurred.emit(model_name, error_msg)
                            self.total_errors += 1
                            logger.error(f"Error applying {model_name}: {e}")

            return True

        except Exception as e:
            logger.error(f"Apply error: {e}", exc_info=True)
            return False

    def _handle_cancellation(self):
        """Handle sync cancellation"""
        logger.info("🛑 Sync cancelled by user")

        duration = (datetime.now() - self.start_time).total_seconds()

        self.sync_completed.emit(False, {
            'cancelled': True,
            'message': 'Sync cancelled by user',
            'duration': duration,
            'created': self.total_created,
            'updated': self.total_updated,
            'errors': self.total_errors,
        })