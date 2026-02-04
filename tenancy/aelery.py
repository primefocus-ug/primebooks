from __future__ import absolute_import, unicode_literals
import os
from celery import Celery

# Set default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tenancy.settings')

# Create Celery app instance
app = Celery('tenancy')

# Load config from Django settings with CELERY_ prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from installed apps
app.autodiscover_tasks()

# Optional debug task
@app.task(bind=True)
def debug_task(self):
    print('Request: {0!r}'.format(self.request))
