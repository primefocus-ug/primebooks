"""
Utilities for managing Django signals during tenant creation.
Add this to public_router/signal_utils.py
"""

from contextlib import contextmanager
from django.db.models.signals import post_save, pre_save, post_delete, pre_delete
import logging

logger = logging.getLogger(__name__)


@contextmanager
def disable_signals(model=None, signals=None):
    """
    Context manager to temporarily disable Django signals.

    Usage:
        with disable_signals(model=Company):
            company = Company.objects.create(...)

    Args:
        model: Model class to disable signals for (if None, disables for all models)
        signals: List of signals to disable (default: [pre_save, post_save])
    """
    if signals is None:
        signals = [pre_save, post_save, post_delete, pre_delete]

    # Store original receivers for each signal
    original_receivers = {}

    try:
        for signal in signals:
            # Store original receivers
            original_receivers[signal] = signal.receivers[:]

            if model is not None:
                # Disconnect only for specific model
                disconnected = []
                for receiver in signal.receivers[:]:
                    # Check if this receiver is for our model
                    if hasattr(receiver[1], '__self__'):
                        sender = getattr(receiver[1].__self__, 'sender', None)
                        if sender == model:
                            signal.disconnect(receiver=receiver[1], sender=model)
                            disconnected.append(receiver)
                    elif len(receiver) > 1 and hasattr(receiver[1], 'keywords'):
                        sender = receiver[1].keywords.get('sender')
                        if sender == model:
                            signal.disconnect(receiver=receiver[1], sender=model)
                            disconnected.append(receiver)

                logger.debug(f"Disabled {len(disconnected)} {signal} receivers for {model.__name__}")
            else:
                # Disconnect all receivers
                signal.receivers = []
                logger.debug(f"Disabled all {signal} receivers")

        yield

    finally:
        # Restore original receivers
        for signal, receivers in original_receivers.items():
            signal.receivers = receivers
            logger.debug(f"Restored {signal} receivers")


@contextmanager
def suppress_signals():
    """
    Context manager to suppress all signals during tenant setup.

    Usage:
        with suppress_signals():
            company = Company.objects.create(...)
    """
    import threading

    if not hasattr(threading.current_thread(), '_suppress_signals'):
        threading.current_thread()._suppress_signals = False

    original_value = threading.current_thread()._suppress_signals
    threading.current_thread()._suppress_signals = True

    try:
        yield
    finally:
        threading.current_thread()._suppress_signals = original_value


# Keep the old name for backward compatibility
suppress_audit_logs = suppress_signals


def should_suppress_signals():
    """
    Check if signals should be suppressed for current thread.
    Call this in your signal handlers.
    """
    import threading
    return getattr(threading.current_thread(), '_suppress_signals', False)


# Keep the old name for backward compatibility
should_suppress_audit_logs = should_suppress_signals