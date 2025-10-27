"""
WSGI config for tenancy project.
"""
import os
from django.core.wsgi import get_wsgi_application
from pathlib import Path

# Load environment variables
from dotenv import load_dotenv
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tenancy.settings')

application = get_wsgi_application()