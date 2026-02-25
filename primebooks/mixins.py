# primebooks/mixins.py
"""
Model mixins for offline functionality.
"""
import os
import logging
from django.db import models

logger = logging.getLogger(__name__)


class OfflineIDMixin(models.Model):
    """
    Automatically assigns a temporary negative PK to new model instances
    when running in desktop (offline-capable) mode.

    Negative PKs (-1, -2, -3 …) never collide with server PKs (always > 0).
    During sync the negative ID is replaced with the real server-assigned PK.

    IMPORTANT — MRO order matters:
        ✅  class Sale(OfflineIDMixin, models.Model):   # correct
        ❌  class Sale(models.Model, OfflineIDMixin):   # mixin save() never called
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Only generate an offline ID when:
        #   1. Running in desktop mode  (DESKTOP_MODE env var set by main.py)
        #   2. This is a genuinely new record  (pk is None, not just falsy)
        if os.environ.get('DESKTOP_MODE') and self.pk is None:
            try:
                from primebooks.offline_manager import get_offline_manager

                model_name = f"{self._meta.app_label}.{self._meta.model_name}"
                self.pk = get_offline_manager().get_next_id(model_name)
                logger.debug(f"Assigned offline ID {self.pk} for {model_name}")

            except Exception as exc:
                raise RuntimeError(
                    f"Could not generate offline ID for "
                    f"{self._meta.app_label}.{self._meta.model_name}: {exc}"
                ) from exc

        super().save(*args, **kwargs)