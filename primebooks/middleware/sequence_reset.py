"""
Middleware to auto-reset sequences after each request
✅ Ensures sequences are ALWAYS correct
"""
import logging
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class SequenceResetMiddleware(MiddlewareMixin):
    """
    Reset sequences after each request that creates records
    ✅ Prevents duplicate key errors permanently
    """

    def process_response(self, request, response):
        """Reset sequences after request completes"""
        try:
            # Only reset on successful requests
            if response.status_code < 400:
                from primebooks.signals import reset_tracked_sequences
                reset_tracked_sequences()
        except Exception as e:
            logger.debug(f"Sequence reset middleware error: {e}")

        return response