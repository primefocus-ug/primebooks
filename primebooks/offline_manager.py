# primebooks/offline_manager.py
"""
Offline ID Manager - Generates temporary negative IDs for offline records
✅ Prevents ID collisions when creating records offline
✅ IDs are replaced with server IDs during sync
"""
import json
import logging
from django.conf import settings
from pathlib import Path

logger = logging.getLogger(__name__)


class OfflineIDManager:
    """
    Manages temporary negative IDs for offline record creation

    Desktop records use: -1, -2, -3, ...
    Server records use: 1, 2, 3, ...

    During sync, negative IDs are replaced with real server IDs
    """

    def __init__(self):
        self.counter_file = settings.DESKTOP_DATA_DIR / '.offline_counters.json'
        logger.info(f"OfflineIDManager initialized: {self.counter_file}")

    def get_next_id(self, model_name):
        """
        Get next temporary negative ID for a model

        Args:
            model_name: Full model name (e.g., 'sales.Sale')

        Returns:
            Negative integer ID (e.g., -1, -2, -3)
        """
        counters = self._load()

        # Get current counter for this model
        current = counters.get(model_name, 0)

        # Generate negative ID
        next_id = -(current + 1)

        # Update counter
        counters[model_name] = current + 1
        self._save(counters)

        logger.debug(f"Generated offline ID for {model_name}: {next_id}")

        return next_id

    def reset_counter(self, model_name):
        """Reset counter for a specific model"""
        counters = self._load()
        if model_name in counters:
            del counters[model_name]
            self._save(counters)
            logger.info(f"Reset counter for {model_name}")

    def reset_all(self):
        """Reset all counters"""
        self.counter_file.write_text('{}')
        logger.info("Reset all offline ID counters")

    def get_stats(self):
        """Get statistics about offline IDs"""
        counters = self._load()
        return {
            'models': len(counters),
            'total_offline_records': sum(counters.values()),
            'counters': counters
        }

    def _load(self):
        """Load counters from file"""
        if self.counter_file.exists():
            try:
                return json.loads(self.counter_file.read_text())
            except json.JSONDecodeError:
                logger.error("Corrupted counter file, resetting")
                return {}
        return {}

    def _save(self, data):
        """Save counters to file"""
        self.counter_file.write_text(json.dumps(data, indent=2))


# Global singleton instance
_offline_manager = None


def get_offline_manager():
    """Get the global OfflineIDManager instance"""
    global _offline_manager
    if _offline_manager is None:
        _offline_manager = OfflineIDManager()
    return _offline_manager