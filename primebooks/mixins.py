# primebooks/mixins.py
"""
Model mixins for offline functionality.
"""
import os
import logging

logger = logging.getLogger(__name__)


class OfflineIDMixin:
    """
    Automatically assigns a temporary negative PK to new model instances
    when running in desktop (offline-capable) mode.

    Negative PKs (-1, -2, -3 …) never collide with server PKs (always > 0).
    During sync the negative ID is replaced with the real server-assigned PK.

    IMPORTANT — MRO order matters:
        ✅  class Sale(OfflineIDMixin, models.Model):   # correct
        ❌  class Sale(models.Model, OfflineIDMixin):   # mixin save() never called
    """

    def save(self, *args, **kwargs):
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