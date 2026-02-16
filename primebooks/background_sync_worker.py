"""
Background Sync Worker - Non-blocking sync with detailed progress
✅ Runs sync in background thread
✅ Emits detailed progress signals
✅ Allows UI to remain responsive
✅ System notifications on completion
"""
import logging
from PyQt6.QtCore import QThread, pyqtSignal
from datetime import datetime

logger = logging.getLogger(__name__)


class SyncProgressData:
    """Structured progress data for sync operations"""

    def __init__(self):
        self.phase = "idle"  # idle, upload, download, apply, finalize
        self.current_model = ""
        self.models_total = 0
        self.models_completed = 0
        self.records_total = 0
        self.records_processed = 0
        self.created_count = 0
        self.updated_count = 0
        self.errors = []
        self.warnings = []
        self.start_time = None
        self.percentage = 0

    def to_dict(self):
        return {
            'phase': self.phase,
            'current_model': self.current_model,
            'models_total': self.models_total,
            'models_completed': self.models_completed,
            'records_total': self.records_total,
            'records_processed': self.records_processed,
            'created_count': self.created_count,
            'updated_count': self.updated_count,
            'percentage': self.percentage,
            'error_count': len(self.errors),
            'warning_count': len(self.warnings),
        }


class BackgroundSyncWorker(QThread):
    """
    Background worker for data synchronization
    Runs sync without blocking the UI
    """

    # Detailed progress signals
    sync_started = pyqtSignal(dict)  # {timestamp, type, tenant}
    phase_changed = pyqtSignal(str, str)  # (phase, message)
    model_started = pyqtSignal(str, int, int)  # (model_name, index, total)
    model_progress = pyqtSignal(str, int, int, int)  # (model, created, updated, total)
    model_completed = pyqtSignal(str, int, int)  # (model, created, updated)
    overall_progress = pyqtSignal(int, str)  # (percentage, status_message)
    error_occurred = pyqtSignal(str, str)  # (context, error_message)
    warning_occurred = pyqtSignal(str, str)  # (context, warning_message)
    sync_completed = pyqtSignal(bool, dict)  # (success, summary_data)

    def __init__(self, tenant_id, schema_name, auth_token, sync_type="full"):
        """
        Args:
            tenant_id: Tenant ID
            schema_name: Schema name
            auth_token: Auth token
            sync_type: 'full', 'download', or 'upload'
        """
        super().__init__()
        self.tenant_id = tenant_id
        self.schema_name = schema_name
        self.auth_token = auth_token
        self.sync_type = sync_type

        self.progress_data = SyncProgressData()
        self.is_cancelled = False

    def cancel(self):
        """Cancel the sync operation"""
        self.is_cancelled = True
        logger.info("🛑 Sync cancellation requested")

    def run(self):
        """Execute sync in background thread"""
        try:
            self.progress_data.start_time = datetime.now()

            # Emit sync started
            self.sync_started.emit({
                'timestamp': self.progress_data.start_time.isoformat(),
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

            # Check if online
            self.phase_changed.emit("connection", "Checking server connection...")
            self.overall_progress.emit(5, "Checking connection...")

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

            # Determine sync strategy
            if self.sync_type == "full":
                self._run_full_sync(sync_manager)
            elif self.sync_type == "download":
                self._run_download_sync(sync_manager)
            elif self.sync_type == "upload":
                self._run_upload_sync(sync_manager)
            else:
                raise ValueError(f"Unknown sync type: {self.sync_type}")

        except Exception as e:
            logger.error(f"❌ Background sync error: {e}", exc_info=True)
            self.error_occurred.emit("Sync", str(e))
            self.sync_completed.emit(False, {
                'error': 'exception',
                'message': str(e)
            })

    def _run_full_sync(self, sync_manager):
        """Run full bidirectional sync"""
        try:
            # Phase 1: Upload local changes
            self.progress_data.phase = "upload"
            self.phase_changed.emit("upload", "📤 Uploading local changes...")
            self.overall_progress.emit(10, "Uploading local changes...")

            self._upload_with_progress(sync_manager)

            if self.is_cancelled:
                self._handle_cancellation()
                return

            # Phase 2: Download server changes
            self.progress_data.phase = "download"
            self.phase_changed.emit("download", "📥 Downloading server changes...")
            self.overall_progress.emit(40, "Downloading server changes...")

            self._download_with_progress(sync_manager)

            if self.is_cancelled:
                self._handle_cancellation()
                return

            # Phase 3: Finalize
            self.progress_data.phase = "finalize"
            self.phase_changed.emit("finalize", "✨ Finalizing sync...")
            self.overall_progress.emit(95, "Finalizing...")

            sync_manager.update_last_sync_time()

            # Complete
            self.overall_progress.emit(100, "✅ Sync complete!")

            summary = {
                'success': True,
                'duration': (datetime.now() - self.progress_data.start_time).total_seconds(),
                'created': self.progress_data.created_count,
                'updated': self.progress_data.updated_count,
                'errors': len(self.progress_data.errors),
                'warnings': len(self.progress_data.warnings),
            }

            self.sync_completed.emit(True, summary)

        except Exception as e:
            logger.error(f"Full sync error: {e}", exc_info=True)
            self.error_occurred.emit("Full Sync", str(e))
            self.sync_completed.emit(False, {'error': str(e)})

    def _run_download_sync(self, sync_manager):
        """Run download-only sync"""
        try:
            self.progress_data.phase = "download"
            self.phase_changed.emit("download", "📥 Downloading data...")

            success = self._download_with_progress(sync_manager)

            if success and not self.is_cancelled:
                summary = {
                    'success': True,
                    'duration': (datetime.now() - self.progress_data.start_time).total_seconds(),
                    'created': self.progress_data.created_count,
                    'updated': self.progress_data.updated_count,
                }
                self.sync_completed.emit(True, summary)
            elif self.is_cancelled:
                self._handle_cancellation()
            else:
                self.sync_completed.emit(False, {'error': 'Download failed'})

        except Exception as e:
            logger.error(f"Download sync error: {e}", exc_info=True)
            self.sync_completed.emit(False, {'error': str(e)})

    def _run_upload_sync(self, sync_manager):
        """Run upload-only sync"""
        try:
            self.progress_data.phase = "upload"
            self.phase_changed.emit("upload", "📤 Uploading data...")

            success = self._upload_with_progress(sync_manager)

            if success and not self.is_cancelled:
                summary = {
                    'success': True,
                    'duration': (datetime.now() - self.progress_data.start_time).total_seconds(),
                    'uploaded': self.progress_data.records_processed,
                }
                self.sync_completed.emit(True, summary)
            elif self.is_cancelled:
                self._handle_cancellation()
            else:
                self.sync_completed.emit(False, {'error': 'Upload failed'})

        except Exception as e:
            logger.error(f"Upload sync error: {e}", exc_info=True)
            self.sync_completed.emit(False, {'error': str(e)})

    def _upload_with_progress(self, sync_manager):
        """Upload with detailed progress tracking"""
        last_sync = sync_manager.get_last_sync_time()
        changes = sync_manager.collect_local_changes(last_sync)

        if not changes:
            self.overall_progress.emit(40, "No local changes to upload")
            return True

        total_records = sum(len(records) for records in changes.values())
        self.progress_data.records_total = total_records
        self.progress_data.models_total = len(changes)

        self.overall_progress.emit(15, f"Uploading {total_records} records...")

        # Upload to server
        url = f"{sync_manager.server_url}/api/desktop/sync/upload/"
        upload_data = {
            "tenant_id": self.tenant_id,
            "schema_name": self.schema_name,
            "changes": changes,
            "last_sync": last_sync.isoformat() if last_sync else None,
        }

        response = sync_manager._make_request(url, method='POST', data=upload_data)

        if not response or response.status_code != 200:
            return False

        result = response.json()
        return result.get("success", False)

    def _download_with_progress(self, sync_manager):
        """Download with detailed progress tracking"""
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

        self.progress_data.records_total = total_records
        self.progress_data.models_total = len(changes)

        # Apply changes with progress
        return self._apply_with_progress(sync_manager, changes)

    def _apply_with_progress(self, sync_manager, all_data):
        """Apply data with detailed model-by-model progress"""
        from django_tenants.utils import schema_context
        from primebooks.sync import suppress_signals

        total_models = len(all_data)

        try:
            with suppress_signals():
                with schema_context(self.schema_name):
                    for index, (model_name, records) in enumerate(all_data.items()):
                        if self.is_cancelled:
                            return False

                        # Emit model started
                        self.model_started.emit(model_name, index + 1, total_models)
                        self.progress_data.current_model = model_name
                        self.progress_data.models_completed = index

                        # Calculate progress percentage
                        base_progress = 50  # Start at 50% (after download)
                        progress_range = 45  # Use 45% for applying data
                        model_progress = int(base_progress + (index / total_models) * progress_range)

                        self.overall_progress.emit(
                            model_progress,
                            f"Applying {model_name} ({index + 1}/{total_models})..."
                        )

                        # Apply model data
                        try:
                            created, updated = sync_manager.apply_model_data(model_name, records)

                            # Update counters
                            self.progress_data.created_count += created
                            self.progress_data.updated_count += updated
                            self.progress_data.records_processed += len(records)

                            # Emit model completed
                            self.model_completed.emit(model_name, created, updated)

                            # Emit detailed progress
                            self.model_progress.emit(
                                model_name,
                                created,
                                updated,
                                len(records)
                            )

                        except Exception as e:
                            error_msg = str(e)[:200]
                            self.error_occurred.emit(model_name, error_msg)
                            self.progress_data.errors.append(f"{model_name}: {error_msg}")
                            logger.error(f"Error applying {model_name}: {e}")

            return True

        except Exception as e:
            logger.error(f"Apply error: {e}", exc_info=True)
            return False

    def _handle_cancellation(self):
        """Handle sync cancellation"""
        logger.info("🛑 Sync cancelled by user")
        self.sync_completed.emit(False, {
            'cancelled': True,
            'message': 'Sync cancelled by user',
            'partial_data': self.progress_data.to_dict()
        })