# primebooks/offline_manager.py
"""
Offline ID Manager - Generates temporary negative IDs for offline records
✅ Prevents ID collisions when creating records offline
✅ IDs are replaced with server IDs during sync
✅ Thread-safe singleton with file locking
✅ Atomic writes — crash-safe counter file
"""
import json
import logging
import threading
import tempfile
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Module-level lock protecting singleton creation
_singleton_lock = threading.Lock()


class OfflineIDManager:
    """
    Manages temporary negative IDs for offline record creation.

    Desktop records use: -1, -2, -3, ...
    Server records use:   1,  2,  3, ...

    During sync, negative IDs are replaced with real server IDs.

    Thread-safety: all public methods are protected by a reentrant lock.
    Crash-safety:  counter file is written atomically via a temp-file rename.
    """

    def __init__(self, data_dir: Path):
        # Accept an explicit data_dir so __init__ never touches Django settings.
        # get_offline_manager() resolves the path lazily after Django is ready.
        self.counter_file = data_dir / '.offline_counters.json'
        self._lock = threading.RLock()
        logger.info(f"OfflineIDManager initialized: {self.counter_file}")

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_next_id(self, model_name: str) -> int:
        """
        Return the next temporary negative ID for *model_name*.

        Args:
            model_name: Full model name, e.g. 'sales.Sale'

        Returns:
            Negative integer (-1, -2, -3, …)
        """
        with self._lock:
            counters = self._load()
            current = counters.get(model_name, 0)
            next_id = -(current + 1)
            counters[model_name] = current + 1
            self._save(counters)

        logger.debug(f"Generated offline ID for {model_name}: {next_id}")
        return next_id

    def reset_counter(self, model_name: str) -> None:
        """Reset the counter for a specific model."""
        with self._lock:
            counters = self._load()
            if model_name in counters:
                del counters[model_name]
                self._save(counters)
                logger.info(f"Reset counter for {model_name}")

    def reset_all(self) -> None:
        """Reset all counters."""
        with self._lock:
            self._save({})
        logger.info("Reset all offline ID counters")

    def get_stats(self) -> dict:
        """Return statistics about current offline ID counters."""
        with self._lock:
            counters = self._load()
        return {
            'models': len(counters),
            'total_offline_records': sum(counters.values()),
            'counters': counters,
        }

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _load(self) -> dict:
        """
        Load counters from disk.

        On corruption, backs up the bad file and starts fresh rather than
        silently discarding data without any trace.
        """
        if not self.counter_file.exists():
            return {}

        raw = self.counter_file.read_text(encoding='utf-8')
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Counter file root must be a JSON object")
            return data
        except (json.JSONDecodeError, ValueError) as exc:
            # Back up the corrupted file so data isn't permanently lost
            backup = self.counter_file.with_suffix('.json.corrupted')
            try:
                self.counter_file.replace(backup)
                logger.error(
                    f"Corrupted counter file backed up to {backup}, "
                    f"starting fresh. Error: {exc}"
                )
            except Exception as backup_err:
                logger.error(
                    f"Counter file corrupt AND could not back it up: {backup_err}. "
                    f"Starting fresh."
                )
            return {}

    def _save(self, data: dict) -> None:
        """
        Write counters atomically: write to a temp file then rename.

        This guarantees the counter file is never partially written even if
        the process is killed mid-write.
        """
        dir_ = self.counter_file.parent
        dir_.mkdir(parents=True, exist_ok=True)

        # Write to a sibling temp file, then atomically replace
        fd, tmp_path = tempfile.mkstemp(
            dir=dir_,
            prefix='.offline_counters_',
            suffix='.tmp',
        )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())   # ensure bytes hit disk before rename
            Path(tmp_path).replace(self.counter_file)  # atomic on all OSes
        except Exception:
            # Clean up the temp file if anything went wrong
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


# ---------------------------------------------------------------------------
# Thread-safe lazy singleton
# ---------------------------------------------------------------------------

_offline_manager: "OfflineIDManager | None" = None


def get_offline_manager() -> OfflineIDManager:
    """
    Return the process-wide OfflineIDManager instance.

    Initialisation is deferred until first call so that Django settings
    (specifically DESKTOP_DATA_DIR) are guaranteed to be available.
    The double-checked locking pattern makes this safe under concurrent calls.
    """
    global _offline_manager

    if _offline_manager is None:
        with _singleton_lock:
            if _offline_manager is None:          # re-check inside the lock
                from django.conf import settings  # deferred import
                _offline_manager = OfflineIDManager(
                    Path(settings.DESKTOP_DATA_DIR)
                )

    return _offline_manager