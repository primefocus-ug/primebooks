from __future__ import absolute_import, unicode_literals
import os

if os.environ.get("PRIMEBOOKS_DESKTOP") != "1":
    from .aelery import app as celery_app
    __all__ = ("celery_app",)
else:
    __all__ = ()
