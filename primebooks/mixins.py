# primebooks/mixins.py
"""
Model mixins for offline functionality
"""
from django.db import models
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class OfflineIDMixin(models.Model):
    """
    Mixin to add offline ID generation to models

    Usage:
        class Sale(OfflineIDMixin, models.Model):
            # ... your fields
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        """Override save to generate offline ID if needed"""

        # Only generate offline ID if:
        # 1. In desktop mode
        # 2. Record doesn't have a PK yet (new record)
        # 3. Not forcing a specific ID
        if (getattr(settings, 'DESKTOP_MODE', False) and
                not self.pk and
                not kwargs.get('force_insert')):
            from primebooks.offline_manager import get_offline_manager

            # Get model name
            model_name = f"{self._meta.app_label}.{self._meta.model_name}"

            # Generate temporary negative ID
            self.pk = get_offline_manager().get_next_id(model_name)

            logger.info(f"✅ Generated offline ID {self.pk} for {model_name}")

        super().save(*args, **kwargs)